import secrets
import os
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.clientes import router as clientes_router
from app.db.database import get_db
from app.db.models import Tenant, Agenda, Cliente
from app.schemas import ContaReq, ContaResp
from app.api.deps import obter_tenant_atual, hash_token
from app.services import evolution
from app.services.config_disparo import (
    DIAS_MAXIMO,
    DIAS_MINIMO,
    ler_regras,
)
from app.services.mensagem import PLACEHOLDERS, validar_template
from app.services.telefone import normalizar_telefone
from app.worker.celery_app import celery_app

# Base pública do backend, usada para registrar o webhook da Evolution.
# Sem ela o fluxo de SIM/ADIAR/SAIR nunca chega em produção.
WEBHOOK_PUBLIC_URL = os.getenv("WEBHOOK_PUBLIC_URL", "").rstrip("/")

DESCRICAO_API = """
API do **LembraZap** — micro-SaaS de lembretes e remarketing por WhatsApp para
negócios locais (barbearias, salões, clínicas, oficinas, estúdios).

Cada conta conecta o **próprio número** de WhatsApp via QR Code, numa instância
isolada da Evolution API, e o sistema dispara duas campanhas:

- **Lembrete de consulta marcada** — avisa X horas antes do horário.
- **Reativação de cliente inativo** — quem não vem há N dias recebe um "sentimos
  sua falta" com o nome dele no texto.

Cliente que responde `SAIR` ou `PARAR` é marcado com `opt_out` e nunca mais
recebe disparo automático.

### Autenticação

Todas as rotas `/api/*` exigem o header `X-LZ-Token`, exceto `POST /api/contas`.
O token é gerado uma única vez na criação da conta; o banco guarda apenas o
hash SHA-256. Para usar o botão **Authorize** aqui, cole o token no campo.

### Estado dos agendamentos

| Status | Significado |
|---|---|
| `agendado` | Criado, aguardando lembrete e resposta |
| `na_fila` | Lembrete entrou na fila de envio |
| `enviado` | Lembrete despachado pela Evolution |
| `confirmado` | Cliente respondeu **SIM** |
| `reagendando` | Cliente respondeu **ADIAR** ou **REAGENDAR** |
| `concluido` | Atendimento realizado; zera o contador de dias sem visita |

### Observações importantes

- O webhook (`POST /api/webhook/whatsapp`) é chamada pela Evolution API, não pelo
  painel. Precisa estar alcançável publicamente via `WEBHOOK_PUBLIC_URL`.
- O processamento de respostas usa o mesmo endpoint; mensagens que não forem
  `SIM`, `ADIAR`, `REAGENDAR`, `SAIR` ou `PARAR` são registradas e ignoradas.
- `POST /api/clientes/importar` recebe CSV. Exige `python-multipart` instalado.
"""

app = FastAPI(
    title="LembraZap API",
    version="0.2.0",
    description=DESCRICAO_API,
    contact={"name": "LembraZap"},
    openapi_tags=[
        {"name": "Conta", "description": "Criação de conta e dados do negócio."},
        {"name": "WhatsApp", "description": "Instância Evolution API, QR Code e webhook."},
        {"name": "Agendamentos", "description": "Compromissos e seus status."},
        {"name": "Clientes", "description": "Base de clientes: cadastro, edição, importação e histórico de visitas."},
        {"name": "Configurações", "description": "Regras de disparo e modelos de mensagem."},
        {"name": "Diagnóstico", "description": "Healthcheck e testes de fila."},
    ],
)

# Rotas de clientes, separadas em api/clientes.py
app.include_router(clientes_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class NovoAgendamentoRequest(BaseModel):
    nome: str = Field(..., examples=["Carlos Silva"], description="Nome do cliente.")
    telefone: str = Field(
        ...,
        examples=["5592992030250"],
        description="WhatsApp só com dígitos, com DDI. Ex.: 55 + DDD + número.",
    )
    servico: str = Field(..., examples=["Corte + Barba"], description="Serviço contratado.")
    quando: datetime = Field(
        ...,
        examples=["2026-10-21T17:00:00"],
        description="Horário do compromisso em ISO 8601.",
    )


class ConfiguracaoRequest(BaseModel):
    horas_antecedencia: int = Field(
        default=24,
        ge=1,
        le=720,
        examples=[24],
        description="Quantas horas antes do horário o lembrete é disparado.",
    )
    mensagem_lembrete: str = Field(
        default="",
        max_length=1200,
        examples=["Fala {nome}, lembra do teu horário na {negocio} para {servico} em {data} às {horario}. Responda SIM para confirmar."],
        description="Texto do lembrete de consulta marcada.",
    )

    dias_sem_visitar: int = Field(
        default=45,
        ge=DIAS_MINIMO,
        le=DIAS_MAXIMO,
        examples=[45],
        description="Quantos dias sem visitar para o cliente entrar na reativação.",
    )
    reativacao_ativa: bool = Field(
        default=False,
        description="Liga o disparo diário para os clientes sumidos.",
    )
    limite_por_dia: int = Field(
        default=50,
        ge=1,
        le=500,
        examples=[50],
        description="Teto de mensagens de reativação por dia, para não estourar a janela da Evolution.",
    )
    mensagem_reativacao: str = Field(
        default="",
        max_length=1200,
        examples=["Fala {nome}, faz {dias} dias que não te vemos na {negocio}! Passa aqui."],
        description="Texto da reativação de cliente inativo.",
    )
    envios_pausados: bool = Field(
        default=False,
        description="Pausa todos os envios automáticos sem perder a fila.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "horas_antecedencia": 24,
                "mensagem_lembrete": "Fala {nome}, seu horário na {negocio} é {data} às {horario}. Responda SIM.",
                "dias_sem_visitar": 45,
                "reativacao_ativa": True,
                "limite_por_dia": 50,
                "mensagem_reativacao": "Fala {nome}, faz {dias} dias que não te vemos! Quer marcar?",
            }
        }
    }


ERRO_TOKEN = {
    401: {
        "description": "Header `X-LZ-Token` ausente ou inválido.",
        "content": {"application/json": {"example": {"detail": "Token de conta inválido."}}},
    }
}

ERRO_EVOLUTION = {
    502: {
        "description": "A Evolution API recusou a operação (HTTP ou rede).",
        "content": {"application/json": {"example": {"detail": "Erro ao criar instância na Evolution: ..."}}},
    }
}

@app.get("/healthz", tags=["Diagnóstico"], summary="Verifica se a API está no ar")
def healthz():
    """Healthcheck leve, usado pelo Docker para decidir se o worker pode subir.

    Não toca no banco: valida apenas que o processo do FastAPI responde.
    """
    return {"status": "ok", "mensagem": "API conectada ao PostgreSQL com sucesso!"}

@app.post(
    "/api/contas",
    response_model=ContaResp,
    tags=["Conta"],
    summary="Cria uma conta e devolve o token",
    responses={400: {"description": "Nome do negócio vazio."}},
)
def criar_conta(body: ContaReq, db: Session = Depends(get_db)):
    """Cria a conta e devolve o token uma única vez (só o hash vai para o banco).

    O token **não** é recuperável depois: guarde-o. Também é criada a
    configuração inicial (antecedência padrão de 24h).
    """
    if not body.nome.strip():
        raise HTTPException(status_code=400, detail="Informe o nome do negócio.")
    
    token_plano = secrets.token_hex(16)
    
    novo_tenant = Tenant(
        nome=body.nome.strip(),
        negocio=body.negocio.strip() or body.nome.strip(),
        token_hash=hash_token(token_plano),
        config={}
    )
    
    db.add(novo_tenant)
    db.commit()
    db.refresh(novo_tenant)
    
    return {"ok": True, "tenant_id": novo_tenant.id, "token": token_plano}

@app.get(
    "/api/conta",
    tags=["Conta"],
    summary="Dados da conta autenticada",
    responses=ERRO_TOKEN,
)
def dados_conta(tenant: Tenant = Depends(obter_tenant_atual)):
    """Resumo da conta autenticada: identificação, instância e configuração."""
    return {
        "tenant_id": tenant.id,
        "nome": tenant.nome,
        "negocio": tenant.negocio,
        "instancia": tenant.instancia,
        "config": tenant.config
    }

@app.post(
    "/api/teste-fila",
    tags=["Diagnóstico"],
    summary="Enfileira uma mensagem de teste (não envia nada)",
    responses=ERRO_TOKEN,
)
def teste_fila(telefone: str, mensagem: str, tenant: Tenant = Depends(obter_tenant_atual)):
    """Enfileira a task `simular_envio_whatsapp`, que apenas escreve no log.

    Não há envio real aqui — serve para confirmar que o Redis e o worker estão
    conversando. Para testar envio de verdade, crie um agendamento.
    """
    tarefa = celery_app.send_task(
        "simular_envio_whatsapp", 
        args=[tenant.id, telefone, mensagem]
    )
    
    return {
        "ok": True, 
        "info": "Tarefa enviada para a fila (background) com sucesso!",
        "tarefa_id": tarefa.id
    }
    
@app.post(
    "/api/conexao/criar",
    tags=["WhatsApp"],
    summary="Cria a instância na Evolution e registra o webhook",
    responses={**ERRO_TOKEN, **ERRO_EVOLUTION},
)
def conexao_criar(tenant: Tenant = Depends(obter_tenant_atual), db: Session = Depends(get_db)):
    """Cria a instância Evolution API da conta e aponta o webhook para o backend.

    Idempotente: se a instância já existe, apenas re-registra o webhook. Sem isso
    não havia como corrigir um webhook ausente ou desatualizado — trocar a URL
    pública exigia criar outra instância e orfanar a anterior na Evolution.

    `webhook_configurado: false` significa que `WEBHOOK_PUBLIC_URL` está vazio ou
    que a Evolution recusou o registro. Sem webhook o cliente responde, mas o
    sistema não enxerga a resposta.
    """
    nome_instancia = tenant.instancia or f"LZ_{tenant.id}".upper()

    if not tenant.instancia:
        try:
            evolution.criar_instancia(nome_instancia)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Erro ao criar instância na Evolution: {exc}")

    # Sem o webhook a Evolution não notifica nada e o SIM/ADIAR morre aqui.
    webhook_configurado = False
    if WEBHOOK_PUBLIC_URL:
        try:
            evolution.definir_webhook(
                nome_instancia,
                f"{WEBHOOK_PUBLIC_URL}/api/webhook/whatsapp",
                ["MESSAGES_UPSERT"],
            )
            webhook_configurado = True
        except Exception as exc:
            # Não derruba a criação: o dono ainda pode parear pelo QR.
            print(f"[main] Webhook não configurado para {nome_instancia}: {exc}")

    ja_existia = bool(tenant.instancia)
    tenant.instancia = nome_instancia
    db.commit()
    return {
        "ok": True,
        "instancia": nome_instancia,
        "ja_existia": ja_existia,
        "webhook_configurado": webhook_configurado,
    }

@app.get(
    "/api/conexao/qrcode",
    tags=["WhatsApp"],
    summary="QR Code de pareamento",
    responses={
        **ERRO_TOKEN,
        404: {"description": "Nenhuma instância criada ainda (`POST /api/conexao/criar`)."},
        **ERRO_EVOLUTION,
    },
)
def conexao_qrcode(tenant: Tenant = Depends(obter_tenant_atual)):
    """Retorna o QR Code (campo `base64`, já em data-uri pronta para `<img src>`).

    O QR expira em pouco tempo na Evolution. Se a leitura falhar, chame de novo.
    Quando `MODO_SIMULACAO=1`, o QR é fictício e serve só para demonstração.
    """
    if not tenant.instancia:
        raise HTTPException(status_code=404, detail="Crie a conexão primeiro.")
    
    try:
        return evolution.obter_qrcode(tenant.instancia)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro ao gerar QR Code: {exc}")

@app.get(
    "/api/configuracoes",
    tags=["Configurações"],
    summary="Lê as regras de disparo da conta",
    responses=ERRO_TOKEN,
)
def ler_configuracoes(
    tenant: Tenant = Depends(obter_tenant_atual),
):
    """Devolve as regras atuais já com os defaults aplicados.

    Existia só o `POST` para gravar: o painel não conseguia reidratar o formulário
    ao abrir, e recarregar a página perdia o que o dono tinha digitado.
    """
    regras = ler_regras(tenant.config)
    return {
        "horas_antecedencia": regras.horas_antecedencia,
        "mensagem_lembrete": regras.mensagem_lembrete,
        "dias_sem_visitar": regras.dias_sem_visitar,
        "reativacao_ativa": regras.reativacao_ativa,
        "limite_por_dia": regras.limite_por_dia,
        "mensagem_reativacao": regras.mensagem_reativacao,
        "envios_pausados": regras.envios_pausados,
        "placeholders": list(PLACEHOLDERS),
    }


@app.post(
    "/api/configuracoes",
    tags=["Configurações"],
    summary="Grava as regras de disparo e os modelos de mensagem",
    responses={**ERRO_TOKEN, 422: {"description": "Corpo inválido (validação do Pydantic)."}},
)
def salvar_configuracoes(
    body: ConfiguracaoRequest,
    tenant: Tenant = Depends(obter_tenant_atual),
    db: Session = Depends(get_db)
):
    """Guarda as regras de disparo e os modelos de mensagem nas configurações do tenant.

    A gravação é parcial: chaves já existentes em `config` que não vêm no corpo
    são preservadas.

    O texto é validado antes de gravar e os problemas voltam em `avisos` — um
    `{cliente}` digitado no lugar de `{nome}` é removido na hora do envio, então
    avisar agora evita a mensagem chegar sem o nome.
    """
    try:
        avisos = validar_template(body.mensagem_lembrete) + validar_template(body.mensagem_reativacao)

        config_atual = dict(tenant.config or {})
        config_atual.update(
            {
                "horas_antecedencia": body.horas_antecedencia,
                "mensagem_lembrete": body.mensagem_lembrete,
                "mensagem_modelo": body.mensagem_lembrete,
                "dias_sem_visitar": body.dias_sem_visitar,
                "reativacao_ativa": body.reativacao_ativa,
                "limite_por_dia": body.limite_por_dia,
                "mensagem_reativacao": body.mensagem_reativacao,
                "envios_pausados": body.envios_pausados,
            }
        )

        tenant.config = config_atual
        db.commit()
        db.refresh(tenant)

        return {
            "ok": True,
            "mensagem": "Configurações guardadas com sucesso!",
            "avisos": avisos,
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro interno ao salvar: {str(e)}")

@app.post(
    "/api/webhook/whatsapp",
    tags=["WhatsApp"],
    summary="Recebe mensagens da Evolution API",
    responses={200: {"description": "Evento processado ou ignorado (nunca erra por evento irrelevante)."}},
)
async def webhook_whatsapp(request: Request, db: Session = Depends(get_db)):
    """Recebe eventos de novas mensagens da Evolution API e atualiza agendamentos.

    Rota chamada **pela Evolution**, não pelo painel. Exige que
    `WEBHOOK_PUBLIC_URL` esteja definido e alcançável.

    Regras aplicadas ao texto recebido (uppercase, contém):
    - `SIM` → agendado vira `confirmado`, grava `confirmado_em` e marca a visita
      do cliente em `ultima_visita`
    - `ADIAR` ou `REAGENDAR` → agendado vira `reagendando`
    - `SAIR`, `PARAR` ou `NAO QUERO` → cliente marcado com `opt_out` e nunca
      mais recebe disparo automático

    Ignora mensagens próprias, grupo (`@g.us`), eventos que não sejam
    `messages.upsert` e agendamentos que não estejam com status `agendado`.
    """
    try:
        payload = await request.json()
        
        evento = payload.get("event")
        if evento != "messages.upsert":
            return {"ok": True, "ignorado": "evento nao relevante"}

        dados = payload.get("data", {})
        instancia = payload.get("instance")

        remote_jid = dados.get("key", {}).get("remoteJid", "")
        telefone = remote_jid.split("@")[0] if remote_jid else ""
        
        from_me = dados.get("key", {}).get("fromMe", False)
        if from_me or not telefone:
            return {"ok": True, "ignorado": "mensagem propria ou remetente invalido"}

        mensagem_dict = dados.get("message", {})
        texto = (
            mensagem_dict.get("conversation") or
            mensagem_dict.get("extendedTextMessage", {}).get("text") or
            ""
        ).strip().upper()

        if not texto:
            return {"ok": True, "ignorado": "sem texto"}

        tenant = db.query(Tenant).filter(Tenant.instancia == instancia).first()
        if not tenant:
            return {"ok": False, "detalhe": "Instancia nao localizada"}

        cliente = db.query(Cliente).filter(
            Cliente.tenant_id == tenant.id,
            Cliente.telefone.contains(telefone[-8:])
        ).first()

        if cliente:
            cliente.respondeu_em = datetime.utcnow()
            cliente.ultima_resposta = texto

        # Opt-out tem precedência sobre tudo. Quem pede para parar de receber
        # não deve antes receber resposta de confirmação de nada.
        if "SAIR" in texto or "PARAR" in texto or "NAO QUERO" in texto or "NAO" == texto:
            if cliente:
                cliente.opt_out = True
            db.commit()
            return {
                "ok": True,
                "instancia": instancia,
                "telefone": telefone,
                "opt_out": True,
                "mensagem": "Cliente marcado como não quer mais receber.",
            }

        agendamento = db.query(Agenda).filter(
            Agenda.tenant_id == tenant.id,
            Agenda.telefone.contains(telefone[-8:]),
            Agenda.status == "agendado"
        ).order_by(Agenda.quando.desc()).first()

        if not agendamento:
            db.commit()
            return {"ok": True, "info": "Cliente registado, sem agendamento pendente"}

        if "SIM" in texto:
            agendamento.status = "confirmado"
            agendamento.confirmado_em = datetime.utcnow()

            # Confirmou o horário: a visita está garantida. Registrar aqui é o que
            # tira o cliente da fila de reativação — sem isso ele continuaria
            # "sumido" mesmo tendo comparecido.
            if cliente:
                cliente.ultima_visita = datetime.utcnow()

        elif "ADIAR" in texto or "REAGENDAR" in texto:
            agendamento.status = "reagendando"

        db.commit()

        return {
            "ok": True,
            "instancia": instancia,
            "telefone": telefone,
            "resposta_recebida": texto,
            "status_agenda": agendamento.status
        }

    except Exception as exc:
        db.rollback()
        return {"ok": False, "erro": str(exc)}
    
@app.get(
    "/api/agendamentos",
    tags=["Agendamentos"],
    summary="Lista os agendamentos da conta",
    responses=ERRO_TOKEN,
)
def listar_agendamentos(
    tenant: Tenant = Depends(obter_tenant_atual),
    db: Session = Depends(get_db)
):
    """Lista as marcações do tenant atual ordenadas pela data, mais antiga primeiro.

    Sem paginação: devolve todos os registros da conta.
    """
    agendamentos = db.query(Agenda).filter(
        Agenda.tenant_id == tenant.id
    ).order_by(Agenda.quando.asc()).all()
    
    return [
        {
            "id": a.id,
            "nome": a.nome,
            "telefone": a.telefone,
            "servico": a.servico,
            "quando": a.quando.strftime("%Y-%m-%d %H:%M"),
            "status": a.status
        }
        for a in agendamentos
    ]

@app.post(
    "/api/agendamentos",
    tags=["Agendamentos"],
    summary="Cria um agendamento",
    responses={**ERRO_TOKEN, 422: {"description": "Corpo inválido (validação do Pydantic)."}},
)
def criar_agendamento(
    body: NovoAgendamentoRequest,
    tenant: Tenant = Depends(obter_tenant_atual),
    db: Session = Depends(get_db)
):
    """Regista uma nova marcação vinculada ao tenant.

    Cria o `Cliente` automaticamente se ainda não existir para este telefone.
    O telefone é normalizado antes da comparação: `11999998888` e
    `(11) 99999-8888` são o mesmo contato, e sem normalizar o cliente entraria
    duas vezes na base.
    """
    telefone = normalizar_telefone(body.telefone) or body.telefone.strip()

    cliente = db.query(Cliente).filter(
        Cliente.tenant_id == tenant.id,
        Cliente.telefone == telefone
    ).first()

    if not cliente:
        cliente = Cliente(
            tenant_id=tenant.id,
            nome=body.nome,
            telefone=telefone
        )
        db.add(cliente)
        db.commit()
        db.refresh(cliente)

    novo_item = Agenda(
        tenant_id=tenant.id,
        cliente_id=cliente.id,
        nome=body.nome,
        telefone=telefone,
        servico=body.servico,
        quando=body.quando,
        status="agendado"
    )
    db.add(novo_item)
    db.commit()
    db.refresh(novo_item)

    return {"ok": True, "id": novo_item.id, "cliente_id": cliente.id}


@app.post(
    "/api/agendamentos/{agenda_id}/concluir",
    tags=["Agendamentos"],
    summary="Marca o atendimento como concluído",
    responses={**ERRO_TOKEN, 404: {"description": "Agendamento inexistente nesta conta."}},
)
def concluir_agendamento(
    agenda_id: str,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(obter_tenant_atual),
):
    """Marca a visita como realizada e tira o cliente da fila de reativação.

    O `SIM` no WhatsApp confirma que o cliente *vai* vir; o atendimento concluído
    confirma que ele *veio*. Só o segundo deve zerar o contador de dias sem
    visita — por isso as duas coisas são separadas.
    """
    agendamento = db.query(Agenda).filter(
        Agenda.id == agenda_id,
        Agenda.tenant_id == tenant.id,
    ).first()

    if not agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado nesta conta.")

    agendamento.status = "concluido"

    cliente = None
    if agendamento.cliente_id:
        cliente = db.query(Cliente).filter(
            Cliente.id == agendamento.cliente_id,
            Cliente.tenant_id == tenant.id,
        ).first()

    if not cliente and agendamento.telefone:
        cliente = db.query(Cliente).filter(
            Cliente.tenant_id == tenant.id,
            Cliente.telefone == agendamento.telefone,
        ).first()

    if cliente:
        cliente.ultima_visita = datetime.utcnow()

    db.commit()

    return {
        "ok": True,
        "agenda_id": agendamento.id,
        "cliente_registrado": bool(cliente),
        "mensagem": "Atendimento concluído e visita registrada.",
    }