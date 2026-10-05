"""CRUD da base de clientes do tenant.

Rotas separadas em módulo próprio porque `app/main.py` já concentra toda a API do
projeto e a base de clientes é a parte com mais rotas.

Toda consulta filtra por `tenant_id`: um negócio nunca enxerga a base de outro,
mesmo com token válido.
"""

import csv
import io
import re
import unicodedata
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import exigir_acesso_ativo, obter_tenant_atual
from app.db.database import get_db
from app.db.models import Cliente, Tenant
from app.services.config_disparo import ler_regras
from app.services.telefone import apenas_digitos, mascarar_telefone, normalizar_telefone

router = APIRouter(prefix="/api/clientes", tags=["Clientes"])

ERRO_TOKEN = {
    401: {
        "description": "Header `X-LZ-Token` ausente ou inválido.",
        "content": {"application/json": {"example": {"detail": "Token de conta inválido."}}},
    }
}

_FORMATOS_DATA = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d/%m/%y",
)

# Cabeçalhos de planilha aceitos, já sem acento e em minúscula.
_ALIAS = {
    "nome": "nome",
    "cliente": "nome",
    "nome do cliente": "nome",
    "nome completo": "nome",
    "name": "nome",
    "telefone": "telefone",
    "celular": "telefone",
    "whatsapp": "telefone",
    "telefone whats": "telefone",
    "numero": "telefone",
    "tel": "telefone",
    "fone": "telefone",
    "contato": "telefone",
    "data": "ultima_visita",
    "ultima visita": "ultima_visita",
    "ultima visita em": "ultima_visita",
    "ultimo atendimento": "ultima_visita",
    "ultimo comparecimento": "ultima_visita",
    "visita": "ultima_visita",
    "obs": "obs",
    "observacao": "obs",
    "observacoes": "obs",
    "nota": "obs",
    "anotacao": "obs",
}


def _sem_acento(texto: str) -> str:
    """Remove acentos e normaliza separadores, para casar cabeçalhos.

    Usa normalização Unicode em vez de apagar os caracteres acentuados: apagar
    transformaria "Última Visita" em "ltima visita", que não casa com o alias.
    """
    decomposto = unicodedata.normalize("NFKD", (texto or "").lower())
    sem_marcas = "".join(ch for ch in decomposto if not unicodedata.combining(ch))
    return re.sub(r"[\s_\-]+", " ", sem_marcas).strip()


def _chavear(cabecalho: str) -> str | None:
    """Traduz o cabeçalho da planilha para um campo interno."""
    return _ALIAS.get(_sem_acento(cabecalho))


def _parse_data(valor: str) -> datetime | None:
    """Converte a data da planilha, aceitando os formatos mais comuns.

    A data de "última visita" é o que decide quem entra na campanha de
    reativação. Uma data mal interpretada joga o cliente para o fim da fila ou
    o manda no primeiro disparo, então o que não dá para interpretar volta como
    `None` — cliente sem histórico, que é o estado neutro.
    """
    texto = (valor or "").strip()
    if not texto or texto.lower() in ("nunca", "-", "--", "n/a", "null", "nenhum", "primeira vez"):
        return None

    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass

    for formato in _FORMATOS_DATA:
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue

    return None


def _detectar_separador(bruto: str) -> str:
    """Escolhe o separador do CSV.

    Planilha brasileira exporta com `;` quase sempre, porque `,` é separador
    decimal em pt-BR — assumir `,` importaria um arquivo de uma coluna só. O
    sniffer do stdlib erra em arquivo pequeno, então a decisão conta os
    separadores na primeira linha.
    """
    linhas = bruto.splitlines()
    primeira = linhas[0] if linhas else ""
    contagens = {",": primeira.count(","), ";": primeira.count(";"), "\t": primeira.count("\t")}
    melhor = max(contagens, key=lambda k: contagens[k])
    return melhor if contagens[melhor] > 0 else ","


def _serializar(c: Cliente, dias_visitar: int) -> dict:
    """Representação do cliente para a interface."""
    dias = (datetime.utcnow() - c.ultima_visita).days if c.ultima_visita else None

    return {
        "id": c.id,
        "nome": c.nome,
        "telefone": c.telefone,
        "telefone_formatado": mascarar_telefone(c.telefone),
        "ultima_visita": c.ultima_visita.strftime("%Y-%m-%d %H:%M") if c.ultima_visita else None,
        "dias_sem_visitar": dias,
        "obs": c.obs,
        "opt_out": bool(c.opt_out),
        "ultima_resposta": c.ultima_resposta,
        "respondeu_em": c.respondeu_em.strftime("%Y-%m-%d %H:%M") if c.respondeu_em else None,
        "inativo": bool(dias is not None and dias >= dias_visitar),
        # Cliente sem histórico é o caso ambíguo: nunca voltou, ou veio da
        # planilha e ninguém atualizou. O painel mostra separado do "inativo",
        # porque o que fazer com eles é decisão do dono.
        "sem_historico": c.ultima_visita is None,
    }


def _buscar_cliente(db: Session, tenant: Tenant, cliente_id: str) -> Cliente:
    cliente = db.query(Cliente).filter(
        Cliente.id == cliente_id,
        Cliente.tenant_id == tenant.id,
    ).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente não encontrado nesta conta.")
    return cliente


class ClienteRequest(BaseModel):
    nome: str = Field(..., min_length=1, max_length=120, examples=["Carlos Silva"])
    telefone: str = Field(
        ...,
        examples=["(11) 99999-8888"],
        description="Com ou sem DDI, com ou sem máscara.",
    )
    ultima_visita: datetime | None = Field(
        default=None,
        examples=["2026-09-01T14:30:00"],
        description="Quando veio pela última vez. Se omitido, fica sem histórico.",
    )
    obs: str = Field(default="", max_length=500)


class ClienteUpdate(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=120)
    telefone: str | None = Field(default=None)
    ultima_visita: datetime | None = None
    obs: str | None = Field(default=None, max_length=500)
    opt_out: bool | None = Field(default=None, description="Bloqueia o recebimento de mensagens.")


class OptOutRequest(BaseModel):
    telefone: str = Field(..., description="Telefone de quem pediu para não receber mais.")


@router.get("", summary="Lista os clientes da conta", responses=ERRO_TOKEN)
def listar_clientes(
    busca: str = Query(default="", max_length=120, description="Filtra por nome ou telefone."),
    inativos: bool = Query(default=False, description="Só os que estão a mais dias sem visitar que o configurado."),
    sem_historico: bool = Query(default=False, description="Só os que nunca tiveram visita registrada."),
    limite: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(obter_tenant_atual),
):
    """Lista a base de clientes do negócio.

    Ordena pelos que vieram mais recentemente. Cliente sem histórico aparece
    depois dos com histórico, para não empurrar o resto para fora do `limite`.
    """
    regras = ler_regras(tenant.config)

    q = db.query(Cliente).filter(Cliente.tenant_id == tenant.id)

    if busca:
        termo = busca.strip()
        digitos = apenas_digitos(termo)
        if digitos:
            # Casa o sufixo para achar o número com DDI, máscara ou não.
            q = q.filter(Cliente.telefone.contains(digitos[-8:]))
        else:
            q = q.filter(Cliente.nome.ilike(f"%{termo}%"))

    clientes = q.order_by(Cliente.ultima_visita.is_(None), Cliente.ultima_visita.desc()).all()

    if inativos:
        corte = datetime.utcnow() - timedelta(days=regras.dias_sem_visitar)
        clientes = [c for c in clientes if c.ultima_visita and c.ultima_visita <= corte]

    if sem_historico:
        clientes = [c for c in clientes if c.ultima_visita is None]

    return {
        "total": len(clientes),
        "dias_sem_visitar": regras.dias_sem_visitar,
        "reativacao_ativa": regras.reativacao_ativa,
        "clientes": [_serializar(c, regras.dias_sem_visitar) for c in clientes[:limite]],
    }


@router.post(
    "",
    summary="Cadastra um cliente",
    responses={**ERRO_TOKEN, 422: {"description": "Corpo inválido (validação do Pydantic)."}},
)
def criar_cliente(
    body: ClienteRequest,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(obter_tenant_atual),
):
    """Cadastra um cliente na base do negócio.

    Se já existir cliente com o mesmo telefone nesta conta, atualiza nome,
    observação e histórico em vez de duplicar — o mesmo contato não pode entrar
    duas vezes, senão o motor de inatividade conta ele como duas pessoas.
    """
    telefone = normalizar_telefone(body.telefone)
    if not telefone:
        raise HTTPException(
            status_code=422,
            detail=(
                "Telefone inválido. Use celular com DDD: 11 dígitos "
                "(ex.: 11 99999-8888), com ou sem o +55. "
                "Telefone fixo não recebe WhatsApp."
            ),
        )

    existente = db.query(Cliente).filter(
        Cliente.tenant_id == tenant.id,
        Cliente.telefone == telefone,
    ).first()

    if existente:
        existente.nome = body.nome
        if body.obs:
            existente.obs = body.obs
        if body.ultima_visita:
            existente.ultima_visita = body.ultima_visita
        db.commit()
        db.refresh(existente)
        return {
            "ok": True,
            "id": existente.id,
            "atualizado": True,
            "mensagem": "Cliente já existia nesta conta e foi atualizado.",
            "cliente": _serializar(existente, ler_regras(tenant.config).dias_sem_visitar),
        }

    cliente = Cliente(
        tenant_id=tenant.id,
        nome=body.nome,
        telefone=telefone,
        ultima_visita=body.ultima_visita,
        obs=body.obs,
    )
    db.add(cliente)
    db.commit()
    db.refresh(cliente)

    return {"ok": True, "id": cliente.id, "atualizado": False}


@router.put(
    "/{cliente_id}",
    summary="Atualiza um cliente",
    responses={**ERRO_TOKEN, 404: {"description": "Cliente inexistente nesta conta."}},
)
def atualizar_cliente(
    cliente_id: str,
    body: ClienteUpdate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(obter_tenant_atual),
):
    """Atualiza parcialmente um cliente. Campos omitidos ficam como estão.

    É esta rota que o painel usa para registrar a visita depois do atendimento e
    para reativar manualmente quem pediu para não receber mais mensagens.
    """
    cliente = _buscar_cliente(db, tenant, cliente_id)

    if body.nome is not None:
        cliente.nome = body.nome
    if body.obs is not None:
        cliente.obs = body.obs
    if body.opt_out is not None:
        cliente.opt_out = body.opt_out
    if body.ultima_visita is not None:
        cliente.ultima_visita = body.ultima_visita

    if body.telefone is not None:
        telefone = normalizar_telefone(body.telefone)
        if not telefone:
            raise HTTPException(status_code=422, detail="Telefone inválido.")
        if telefone != cliente.telefone:
            outro = db.query(Cliente).filter(
                Cliente.tenant_id == tenant.id,
                Cliente.telefone == telefone,
                Cliente.id != cliente.id,
            ).first()
            if outro:
                raise HTTPException(
                    status_code=409,
                    detail="Outro cliente desta conta já usa esse telefone.",
                )
            cliente.telefone = telefone

    db.commit()
    db.refresh(cliente)

    return {"ok": True, "cliente": _serializar(cliente, ler_regras(tenant.config).dias_sem_visitar)}


@router.delete(
    "/{cliente_id}",
    summary="Remove um cliente",
    responses={**ERRO_TOKEN, 404: {"description": "Cliente inexistente nesta conta."}},
)
def remover_cliente(
    cliente_id: str,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(obter_tenant_atual),
):
    """Remove o cliente da base.

    Os agendamentos antigos são mantidos — o `cliente_id` fica nulo, mas o
    histórico de atendimento continua no registro. Excluir um cliente não deve
    apagar o passado de visitas que realmente aconteceram.
    """
    cliente = _buscar_cliente(db, tenant, cliente_id)
    db.delete(cliente)
    db.commit()
    return {"ok": True, "mensagem": "Cliente removido."}


@router.post("/opt-out", summary="Bloqueia envios para um telefone", responses=ERRO_TOKEN)
def registrar_opt_out(
    body: OptOutRequest,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(obter_tenant_atual),
):
    """Marca o telefone como não querendo receber mensagens.

    Chamado pelo webhook quando o cliente responde SAIR/NÃO, e pelo painel
    quando o pedido chega pelo telefone. O motor de reativação pula quem está
    marcado.
    """
    telefone = normalizar_telefone(body.telefone)
    if not telefone:
        raise HTTPException(status_code=422, detail="Telefone inválido.")

    cliente = db.query(Cliente).filter(
        Cliente.tenant_id == tenant.id,
        Cliente.telefone.contains(telefone[-8:]),
    ).first()

    if not cliente:
        return {
            "ok": True,
            "encontrado": False,
            "mensagem": "Telefone não está na base desta conta. Nenhuma mensagem foi enviada a ele.",
        }

    cliente.opt_out = True
    cliente.ultima_resposta = "OPT_OUT"
    cliente.respondeu_em = datetime.utcnow()
    db.commit()

    return {"ok": True, "encontrado": True, "id": cliente.id}


@router.post(
    "/importar",
    summary="Importa clientes de uma planilha CSV",
    responses={**ERRO_TOKEN, 422: {"description": "Arquivo ausente, ilegível ou sem colunas reconhecidas."}},
)
async def importar_clientes(
    arquivo: UploadFile = File(..., description="Arquivo .csv exportado da agenda ou da planilha."),
    atualizar_existentes: bool = Query(
        default=True,
        description="Se marcado, atualiza nome/observação/histórico dos que já existem.",
    ),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(exigir_acesso_ativo),
):
    """Importa a base de clientes de um CSV exportado da agenda do negócio.

    O separador é detectado automaticamente entre `,`, `;` e tabulação.

    ### Cabeçalhos reconhecidos

    | Campo | Aceita |
    |---|---|
    | nome | `nome`, `cliente`, `nome do cliente`, `nome completo` |
    | telefone | `telefone`, `celular`, `whatsapp`, `fone`, `contato`, `numero` |
    | última visita | `ultima visita`, `ultimo atendimento`, `data`, `visita` |
    | observação | `obs`, `observacao`, `nota`, `anotacao` |

    Linha sem nome ou com telefone inválido é pulada e contada em `ignorados`,
    com o motivo — o dono vê o que não entrou em vez de a importação inteira
    falhar por causa de uma linha suja.

    Telefone repetido dentro do próprio arquivo é unido em um registro só
    (`duplicados_no_arquivo`), preferindo a linha que traz o nome e a data mais
    recente. Planilha de histórico costuma repetir o contato.

    ### Limite do plano

    O teto de clientes do plano é conferido **antes** de gravar: o que passar do
    limite é ignorado e devolvido em `excedente_limite`, em vez de estourar o plano
    pela metade e deixar o cliente discoverto no meio do arquivo.
    """
    from app.config.planos import limite_clientes

    teto = limite_clientes(tenant.plano)
    ja_cadastrados = db.query(Cliente).filter(Cliente.tenant_id == tenant.id).count()

    if ja_cadastrados >= teto:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Seu plano {tenant.plano} comporta {teto} clientes e você já tem "
                f"{ja_cadastrados}. Faça upgrade para continuar importando."
            ),
        )

    bruto = (await arquivo.read() or b"").decode("utf-8-sig", errors="replace")

    if not bruto.strip():
        raise HTTPException(status_code=422, detail="O arquivo enviado está vazio.")

    try:
        leitura = csv.DictReader(io.StringIO(bruto), delimiter=_detectar_separador(bruto))
        cabecalhos = list(leitura.fieldnames or [])
    except csv.Error as exc:
        raise HTTPException(status_code=422, detail=f"CSV ilegível: {exc}")

    mapa: dict[str, str] = {}
    for coluna in cabecalhos:
        destino = _chavear(coluna)
        if destino and destino not in mapa:
            mapa[destino] = coluna

    if "nome" not in mapa or "telefone" not in mapa:
        raise HTTPException(
            status_code=422,
            detail=(
                "O CSV precisa ter colunas de nome e telefone. "
                f"Encontradas: {', '.join(cabecalhos) or '(nenhuma)'}"
            ),
        )

    criados = atualizados = ignorados = duplicados_no_arquivo = 0
    excedente = 0
    problemas: list[str] = []

    # Planilha real repete o mesmo telefone em linhas diferentes — e nem sempre a
    # linha boa vem primeiro. Guardar por telefone e mesclar no fim evita que a
    # linha sem nome vença a linha com o nome do cliente.
    merged: dict[str, dict] = {}
    ordem: list[str] = []

    try:
        for linha in leitura:
            if linha is None:
                continue

            nome = (linha.get(mapa.get("nome", ""), "") or "").strip()
            telefone_bruto = (linha.get(mapa.get("telefone", ""), "") or "").strip()

            if not nome and not telefone_bruto:
                ignorados += 1
                continue

            telefone = normalizar_telefone(telefone_bruto)
            if not telefone:
                ignorados += 1
                if len(problemas) < 10:
                    problemas.append(f"{nome or '(sem nome)'}: telefone '{telefone_bruto}' inválido")
                continue

            visita = _parse_data(linha.get(mapa["ultima_visita"], "") or "") if "ultima_visita" in mapa else None
            obs = (linha.get(mapa["obs"], "") or "").strip() if "obs" in mapa else ""

            if telefone not in merged:
                merged[telefone] = {"nome": nome, "visita": visita, "obs": obs}
                ordem.append(telefone)
            else:
                duplicados_no_arquivo += 1
                alvo = merged[telefone]
                if not alvo["nome"] and nome:
                    alvo["nome"] = nome
                if visita and (not alvo["visita"] or visita > alvo["visita"]):
                    alvo["visita"] = visita
                if not alvo["obs"] and obs:
                    alvo["obs"] = obs

        for telefone in ordem:
            dados = merged[telefone]

            existente = db.query(Cliente).filter(
                Cliente.tenant_id == tenant.id,
                Cliente.telefone == telefone,
            ).first()

            if existente:
                if atualizar_existentes:
                    if dados["nome"] and (not existente.nome or existente.nome == "Cliente"):
                        existente.nome = dados["nome"]
                    if dados["obs"]:
                        existente.obs = dados["obs"]
                    # Só avança o histórico: uma linha antiga da planilha não
                    # pode fazer o cliente parecer mais recente do que é.
                    if dados["visita"] and (not existente.ultima_visita or dados["visita"] > existente.ultima_visita):
                        existente.ultima_visita = dados["visita"]
                    atualizados += 1
                else:
                    ignorados += 1
            else:
                # O teto é conferido só aqui, no caminho de criação. Atualizar quem já
                # existe não gasta cota, então barrar isso junto com a criação
                # deixaria o cliente sem poder corrigir um nome errado.
                if criados + ja_cadastrados >= teto:
                    excedente += 1
                    continue

                db.add(
                    Cliente(
                        tenant_id=tenant.id,
                        nome=dados["nome"] or "Cliente",
                        telefone=telefone,
                        ultima_visita=dados["visita"],
                        obs=dados["obs"],
                    )
                )
                criados += 1

        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao gravar a importação: {exc}")

    if excedente:
        problemas.append(
            f"{excedente} linha(s) ficaram de fora: o plano {tenant.plano} comporta "
            f"{teto} clientes no total."
        )

    return {
        "ok": True,
        "criados": criados,
        "atualizados": atualizados,
        "ignorados": ignorados,
        "duplicados_no_arquivo": duplicados_no_arquivo,
        "excedente_limite": excedente,
        "limite_clientes": teto,
        "colunas_reconhecidas": sorted(mapa.keys()),
        "problemas": problemas,
        "mensagem": (
            f"{criados} cliente(s) importado(s), {atualizados} atualizado(s), "
            f"{ignorados} ignorado(s)."
            + (
                f" {duplicados_no_arquivo} telefone(s) repetido(s) foram unidos."
                if duplicados_no_arquivo
                else ""
            )
            + (
                f" {excedente} linha(s) barrada(s) pelo limite do plano "
                f"{teto} clientes."
                if excedente
                else ""
            )
        ),
    }