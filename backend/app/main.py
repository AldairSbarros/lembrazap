import secrets
import os
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Tenant, Agenda, Cliente
from app.schemas import ContaReq, ContaResp
from app.api.deps import obter_tenant_atual, hash_token
from app.services import evolution
from app.worker.celery_app import celery_app

# Base pública do backend, usada para registrar o webhook da Evolution.
# Sem ela o fluxo de SIM/ADIAR/SAIR nunca chega em produção.
WEBHOOK_PUBLIC_URL = os.getenv("WEBHOOK_PUBLIC_URL", "").rstrip("/")

DESCRICAO_API = """
API do **LembraZap** — micro-SaaS de lembretes e remarketing por WhatsApp para
negócios locais (barbearias, salões, clínicas, oficinas, estúdios).

Cada conta conecta o **próprio número** de WhatsApp via QR Code, numa instância
isolada da Evolution API, e o sistema dispara lembretes antes dos agendamentos.

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

### Observações importantes

- O webhook (`POST /api/webhook/whatsapp`) é chamada pela Evolution API, não pelo
  painel. Precisa estar alcançável publicamente via `WEBHOOK_PUBLIC_URL`.
- O processamento de respostas usa o mesmo endpoint; mensagens que não forem
  `SIM`, `ADIAR` ou `REAGENDAR` são registradas e ignoradas.
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
        {"name": "Configurações", "description": "Regras de disparo e modelo de mensagem."},
        {"name": "Diagnóstico", "description": "Healthcheck e testes de fila."},
    ],
)

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
        ...,
        ge=1,
        le=720,
        examples=[24],
        description="Quantas horas antes do horário o lembrete é disparado.",
    )
    mensagem_modelo: str = Field(
        ...,
        examples=["Fala {nome}, lembra do teu horário na {negocio} para {servico} em {data} às {horario}. Responda SIM para confirmar."],
        description=(
            "Texto do lembrete. Placeholders aceitos: `{nome}`, `{negocio}`, "
            "`{servico}`, `{data}` (dd/mm) e `{horario}` (hh:mm). Um placeholder "
            "desconhecido faz o worker abortar o lote inteiro — ver docs/ERROS.md."
        ),
    )


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

@app.post(
    "/api/configuracoes",
    tags=["Configurações"],
    summary="Grava antecedência e modelo de mensagem",
    responses={**ERRO_TOKEN, 422: {"description": "Corpo inválido (validação do Pydantic)."}},
)
def salvar_configuracoes(
    body: ConfiguracaoRequest, 
    tenant: Tenant = Depends(obter_tenant_atual),
    db: Session = Depends(get_db)
):
    """Guarda as regras de disparo e modelo de mensagem nas configurações do tenant.

    A gravação é parcial: chaves já existentes em `config` que não vêm no corpo
    são preservadas.
    """
    try:
        config_atual = dict(tenant.config or {})
        config_atual["horas_antecedencia"] = body.horas_antecedencia
        config_atual["mensagem_modelo"] = body.mensagem_modelo
        
        tenant.config = config_atual
        db.commit()
        db.refresh(tenant)
        
        return {
            "ok": True,
            "mensagem": "Configurações guardadas com sucesso!"
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
    - `SIM` → agendado vira `confirmado` e grava `confirmado_em`
    - `ADIAR` ou `REAGENDAR` → agendado vira `reagendando`

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

    Cria o `Cliente` automaticamente se ainda não existir para este telefone
    (comparação exata). O lembrete é disparado pelo worker quando o horário entrar
    na janela de antecedência configurada.
    """
    # Garante a existência ou criação do registo do cliente
    cliente = db.query(Cliente).filter(
        Cliente.tenant_id == tenant.id,
        Cliente.telefone == body.telefone
    ).first()


    if not cliente:
        cliente = Cliente(
            tenant_id=tenant.id,
            nome=body.nome,
            telefone=body.telefone
        )
        db.add(cliente)
        db.commit()
        db.refresh(cliente)

    novo_item = Agenda(
        tenant_id=tenant.id,
        cliente_id=cliente.id,
        nome=body.nome,
        telefone=body.telefone,
        servico=body.servico,
        quando=body.quando,
        status="agendado"
    )
    db.add(novo_item)
    db.commit()
    db.refresh(novo_item)

    return {"ok": True, "id": novo_item.id}