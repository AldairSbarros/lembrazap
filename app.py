"""LembraZap — micro-SaaS de remarketing por WhatsApp para negócios locais.

Protótipo funcional (v1) rodando sobre a mesma Evolution API que o AletheIA já
usa na VPS. Cada conta (tenant) conecta o próprio número de WhatsApp via QR Code
(instância isolada na Evolution API) e usa duas automações:

1. **Reativação** — clientes sem visitar há N dias recebem uma mensagem personalizada.
2. **Lembrete de agenda** — compromissos cadastrados geram lembrete automático antes do horário.

Proteções embutidas desde o protótipo (WhatsApp bloqueia número que spamma):
limite diário de envios por conta, intervalo mínimo entre mensagens, opt-out por
webhook ("SAIR") e fila própria por tenant processada em background.

Sem banco: JSON em disco com escrita atômica (``armazem.JsonStore``), suficiente
para a escala de pilotos pagantes e fácil de migrar depois.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import evolution
import ia
from armazem import JsonStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("lembrazap")

# ── Configuração de ambiente ──────────────────────────────────────────────────
DADOS_DIR = Path(os.getenv("DADOS_DIR", str(Path(__file__).parent / "dados")))
WEBHOOK_PUBLIC_URL = os.getenv("WEBHOOK_PUBLIC_URL", "").rstrip("/")
PORTA = int(os.getenv("PORTA", "8050"))

PALAVRAS_OPT_OUT = ("sair", "parar", "cancelar", "remover", "stop", "nao me mande")

# Resposta positiva curta ("sim", "quero", "confirmo"...) como palavra inteira,
# em mensagem de até 60 caracteres — evita confundir com texto longo.
_REGEX_SIM = re.compile(r"\b(sim|quero|queria|confirmo|aceito|pode agendar|bora|yes)\b")
_TAMANHO_MAX_SIM = 60
_JANELA_RESPOSTA_DIAS = 7  # só responde sozinho a quem recebeu campanha há até 7 dias

TEMPLATE_REATIVACAO = (
    "Olá, {nome}! Sentimos sua falta aqui na {negocio} — já faz {dias} dias "
    "desde a sua última visita. Que tal agendar um horário esta semana? "
    "É só responder SIM. (Para não receber mais mensagens, responda SAIR.)"
)
TEMPLATE_LEMBRETE = (
    "Olá, {nome}! Passando para lembrar do seu compromisso em {quando} aqui na "
    "{negocio}. Qualquer remarcação, é só responder por aqui. "
    "(Para não receber mais mensagens, responda SAIR.)"
)
TEMPLATE_RESPOSTA_SIM = (
    "Que bom ter você de volta, {nome}! Me diz o dia e o horário que ficam "
    "melhores que eu já deixo seu horário reservado aqui na {negocio}."
)
TEMPLATE_CONFIRMA_AGENDAMENTO = (
    "Perfeito, {nome}! Seu horário ficou reservado para {quando} aqui na "
    "{negocio}. Você recebe um lembrete antes do compromisso. "
    "Precisa remarcar? É só avisar por aqui."
)

CONFIG_PADRAO = {
    "limite_diario": 80,        # teto de envios/dia por conta (proteção anti-ban)
    "intervalo_seg": 20,        # pausa mínima entre duas mensagens da mesma conta
    "antecedencia_horas": 24,   # com quanta antecedência o lembrete de agenda entra na fila
    "resposta_auto_ativa": True,  # responde sozinho a quem responder SIM à campanha
    "ia_agendamento_ativa": True, # extrai horário da resposta e reserva sozinho
    "template_reativacao": TEMPLATE_REATIVACAO,
    "template_lembrete": TEMPLATE_LEMBRETE,
    "template_resposta_sim": TEMPLATE_RESPOSTA_SIM,
    "template_confirmacao": TEMPLATE_CONFIRMA_AGENDAMENTO,
}

# ── Stores (JSON em disco, escrita atômica) ───────────────────────────────────
TENANTS = JsonStore(DADOS_DIR / "tenants.json", {})
CLIENTES = JsonStore(DADOS_DIR / "clientes.json", {})
AGENDA = JsonStore(DADOS_DIR / "agenda.json", {})
FILA = JsonStore(DADOS_DIR / "fila.json", {})


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _erro(codigo: int, msg: str) -> None:
    """Levanta HTTPException com a mensagem padrão do produto."""
    raise HTTPException(status_code=codigo, detail=msg)


def _hash_token(token: str) -> str:
    """Hash SHA-256 do token de conta (o token em si nunca é persistido)."""
    return hashlib.sha256(token.encode()).hexdigest()


def _normalizar_telefone(bruto: str) -> str:
    """Reduz o telefone a dígitos com DDI (assume 55 quando ausente)."""
    digitos = re.sub(r"\D", "", bruto or "")
    if len(digitos) in (10, 11):
        return "55" + digitos
    return digitos


def _parse_data(bruto: str) -> Optional[date]:
    """Aceita AAAA-MM-DD ou DD/MM/AAAA; None quando vazio ou inválido."""
    bruto = (bruto or "").strip()
    if not bruto:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(bruto[:10], fmt).date()
        except ValueError:
            continue
    return None


def _parse_quando(bruto: str) -> Optional[datetime]:
    """Aceita AAAA-MM-DDTHH:MM, AAAA-MM-DD HH:MM ou data pura (meio-dia)."""
    bruto = (bruto or "").strip()
    if not bruto:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(bruto, fmt)
        except ValueError:
            continue
    dia = _parse_data(bruto)
    return datetime.combine(dia, datetime.min.time().replace(hour=12)) if dia else None


def _render(template: str, tenant: dict, cliente: Optional[dict] = None,
            dias: int = 0, quando: str = "") -> str:
    """Substitui {nome}, {negocio}, {dias} e {quando} no template da conta."""
    return (
        template
        .replace("{nome}", (cliente or {}).get("nome", "tudo bem?").split()[0])
        .replace("{negocio}", tenant.get("negocio") or tenant.get("nome", ""))
        .replace("{dias}", str(dias))
        .replace("{quando}", quando)
    )


def _cfg(tenant: dict) -> dict:
    """Configuração efetiva da conta (padrões mesclados com o que foi salvo)."""
    cfg = dict(CONFIG_PADRAO)
    cfg.update(tenant.get("config") or {})
    return cfg


def _eh_resposta_sim(texto: str) -> bool:
    """True quando a mensagem recebida é uma aceitação curta (SIM/quero/...)."""
    texto = (texto or "").strip().lower()
    return len(texto) <= _TAMANHO_MAX_SIM and bool(_REGEX_SIM.search(texto))


def _cliente_por_telefone(tid: str, telefone: str) -> tuple[str, dict]:
    """Localiza o cliente da conta pelo sufixo do número; ("", {}) se não achar."""
    achado = next(
        ((cid, c) for cid, c in CLIENTES.ler().items()
         if c["tenant"] == tid and c["telefone"].endswith(telefone[-10:])),
        ("", {}),
    )
    return achado


def _reativacao_recente(cliente_id: str) -> bool:
    """True se o cliente recebeu campanha de reativação entregue nos últimos N dias."""
    corte = (datetime.now() - timedelta(days=_JANELA_RESPOSTA_DIAS)).isoformat(timespec="seconds")
    return any(
        i.get("cliente_id") == cliente_id
        and i.get("campanha", "").startswith("reativacao")
        and i.get("status") == "enviado"
        and (i.get("enviado_em") or "") >= corte
        for i in FILA.ler().values()
    )


# ── Autenticação por token de conta ───────────────────────────────────────────
def _tenant_atual(x_lz_token: str = Header(default="")) -> tuple[str, dict]:
    """Resolve a conta pelo header X-LZ-Token; 401 quando ausente/inválido."""
    if not x_lz_token:
        _erro(401, "Informe o header X-LZ-Token.")
    achado = next(
        ((tid, t) for tid, t in TENANTS.ler().items()
         if t.get("token_hash") == _hash_token(x_lz_token)),
        None,
    )
    if not achado:
        _erro(401, "Token de conta inválido.")
    return achado  # type: return


# ══════════════════════════════════════════════════════════════════════════════
#  MODELOS DE REQUISIÇÃO
# ══════════════════════════════════════════════════════════════════════════════
class ContaReq(BaseModel):
    """Criação de conta (nome do negócio e segmento)."""
    nome: str
    negocio: str = ""


class ClienteReq(BaseModel):
    """Cliente final do negócio (nome, telefone e última visita)."""
    nome: str
    telefone: str
    ultima_visita: str = ""
    obs: str = ""


class ImportarReq(BaseModel):
    """CSV colado no painel: nome;telefone;ultima_visita;obs."""
    csv: str


class OptOutReq(BaseModel):
    """Alterna o opt-out manual de um cliente."""
    opt_out: bool


class ReativacaoReq(BaseModel):
    """Disparo de reativação para inativos há N dias, com mensagem opcional."""
    dias: int = 60
    mensagem: str = ""


class AgendaReq(BaseModel):
    """Compromisso a lembrar (telefone, quando e mensagem opcional)."""
    telefone: str
    quando: str
    nome: str = ""
    mensagem: str = ""


class ConfigReq(BaseModel):
    """Ajustes de envio e templates da conta (todos opcionais)."""
    limite_diario: Optional[int] = None
    intervalo_seg: Optional[int] = None
    antecedencia_horas: Optional[int] = None
    resposta_auto_ativa: Optional[bool] = None
    ia_agendamento_ativa: Optional[bool] = None
    template_reativacao: Optional[str] = None
    template_lembrete: Optional[str] = None
    template_resposta_sim: Optional[str] = None
    template_confirmacao: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
#  PROCESSADORES DE FUNDO (fila de envio e agenda)
# ══════════════════════════════════════════════════════════════════════════════
async def _enviar_item(tid: str, tenant: dict, item_id: str, item: dict) -> None:
    """Envia um item da fila e atualiza fila/cliente/agenda de forma atômica."""
    cliente = CLIENTES.ler().get(item.get("cliente_id") or "")
    if cliente and cliente.get("opt_out"):
        def _marcar_opt_out(fila: dict) -> None:
            fila[item_id]["status"] = "opt_out"
        FILA.atualizar(_marcar_opt_out)
        return
    try:
        resposta = await asyncio.to_thread(
            evolution.enviar_texto, tenant.get("instancia") or "", item["telefone"], item["texto"]
        )
        simulado = bool(resposta.get("simulado"))

        def _pos_envio(fila: dict) -> None:
            fila[item_id].update({
                "status": "enviado",
                "enviado_em": datetime.now().isoformat(timespec="seconds"),
                "simulado": simulado,
            })
        FILA.atualizar(_pos_envio)

        if item.get("cliente_id"):
            def _tocar_cliente(clientes: dict) -> None:
                if item["cliente_id"] in clientes:
                    clientes[item["cliente_id"]]["ultima_msg_em"] = (
                        datetime.now().isoformat(timespec="seconds"))
            CLIENTES.atualizar(_tocar_cliente)
        if item.get("agenda_id"):
            def _fechar_agenda(agenda: dict) -> None:
                if item["agenda_id"] in agenda:
                    agenda[item["agenda_id"]]["status"] = "enviado"
            AGENDA.atualizar(_fechar_agenda)
    except Exception as exc:  # falha de rede/Evolution: marca e tenta no próximo ciclo
        log.warning("Falha ao enviar %s: %s", item_id, exc)
        erro_texto = str(exc)[:300]  # captura antes: o nome do except morre no fim do bloco

        def _marcar_falha(fila: dict) -> None:
            fila[item_id].update({"status": "falha", "erro": erro_texto})
        FILA.atualizar(_marcar_falha)


async def _processar_fila_once() -> None:
    """Um tick do processador: respeita limite diário e intervalo por conta."""
    agora = datetime.now()
    hoje = agora.date().isoformat()
    tenants = TENANTS.ler()
    fila = FILA.ler()
    for tid, tenant in tenants.items():
        if not tenant.get("instancia"):
            continue
        cfg = _cfg(tenant)
        pendentes = sorted(
            (i for i in fila.values() if i["tenant"] == tid and i["status"] == "pendente"),
            key=lambda i: (i.get("prioridade", 1), i["criado_em"]),
        )
        if not pendentes:
            continue
        enviados_hoje = sum(
            1 for i in fila.values()
            if i["tenant"] == tid and i["status"] == "enviado"
            and (i.get("enviado_em") or "").startswith(hoje)
        )
        if enviados_hoje >= int(cfg["limite_diario"]):
            continue
        ultima = tenant.get("ultima_envio_em")
        if ultima:
            if (agora - datetime.fromisoformat(ultima)).total_seconds() < int(cfg["intervalo_seg"]):
                continue
        item = pendentes[0]

        def _carimbar(tenants_: dict) -> None:
            tenants_[tid]["ultima_envio_em"] = agora.isoformat(timespec="seconds")
        TENANTS.atualizar(_carimbar)
        await _enviar_item(tid, tenant, item["id"], item)
        fila = FILA.ler()  # recarrega para o próximo tenant ver o estado novo


async def _loop_fila() -> None:
    """Loop infinito do processador de fila (tick de 5 s)."""
    while True:
        try:
            await _processar_fila_once()
        except Exception as exc:
            log.exception("Erro no loop da fila: %s", exc)
        await asyncio.sleep(5)


async def _agenda_once() -> None:
    """Move compromissos dentro da janela de antecedência para a fila."""
    agora = datetime.now()
    tenants = TENANTS.ler()
    agenda = AGENDA.ler()
    for item_id, item in agenda.items():
        if item.get("status") != "agendado":
            continue
        quando = _parse_quando(item.get("quando", ""))
        if not quando:
            continue
        tenant = tenants.get(item["tenant"], {})
        cfg = _cfg(tenant)
        janela = agora + timedelta(hours=int(cfg["antecedencia_horas"]))
        if quando <= janela and quando >= agora - timedelta(hours=2):
            texto = item.get("mensagem") or _render(
                cfg["template_lembrete"], tenant,
                cliente={"nome": item.get("nome") or ""},
                quando=quando.strftime("%d/%m às %H:%M"),
            )
            novo = {
                "id": uuid.uuid4().hex[:12],
                "tenant": item["tenant"],
                "cliente_id": item.get("cliente_id") or "",
                "agenda_id": item_id,
                "telefone": item["telefone"],
                "texto": texto,
                "campanha": "lembrete-agenda",
                "criado_em": agora.isoformat(timespec="seconds"),
                "status": "pendente",
                "erro": "",
                "enviado_em": "",
                "simulado": False,
                "prioridade": 1,
            }

            def _enfileirar(fila: dict, novo=novo) -> None:
                fila[novo["id"]] = novo
            FILA.atualizar(_enfileirar)

            def _marcar_na_fila(agenda_: dict) -> None:
                agenda_[item_id]["status"] = "na_fila"
            AGENDA.atualizar(_marcar_na_fila)


async def _loop_agenda() -> None:
    """Loop infinito da agenda (tick de 20 s)."""
    while True:
        try:
            await _agenda_once()
        except Exception as exc:
            log.exception("Erro no loop da agenda: %s", exc)
        await asyncio.sleep(20)


@asynccontextmanager
async def _ciclo_de_vida(app: FastAPI):
    """Sobe os dois loops de background e os cancela no shutdown."""
    tarefas = [asyncio.create_task(_loop_fila()), asyncio.create_task(_loop_agenda())]
    log.info("LembraZap no ar (simulação=%s). Dados em %s", evolution.simulando(), DADOS_DIR)
    yield
    for t in tarefas:
        t.cancel()


app = FastAPI(title="LembraZap", version="0.1.0", lifespan=_ciclo_de_vida,
              docs_url=None, redoc_url=None)


# ══════════════════════════════════════════════════════════════════════════════
#  CONTAS
# ══════════════════════════════════════════════════════════════════════════════
@app.post("/api/contas")
async def criar_conta(body: ContaReq) -> dict:
    """Cria a conta e devolve o token uma única vez (só o hash é persistido)."""
    if not body.nome.strip():
        _erro(400, "Informe o nome do negócio.")
    tid = uuid.uuid4().hex[:12]
    token = secrets.token_hex(16)
    tenant = {
        "id": tid,
        "nome": body.nome.strip(),
        "negocio": body.negocio.strip() or body.nome.strip(),
        "token_hash": _hash_token(token),
        "criado_em": datetime.now().isoformat(timespec="seconds"),
        "instancia": "",
        "ultima_envio_em": "",
        "config": {},
    }

    def _inserir(tenants: dict) -> None:
        tenants[tid] = tenant
    TENANTS.atualizar(_inserir)
    return {"ok": True, "tenant_id": tid, "token": token}


@app.get("/api/conta")
async def dados_conta(tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Resumo da conta autenticada (sem expor hash nem token)."""
    tid, t = tenant
    return {
        "tenant_id": tid,
        "nome": t["nome"],
        "negocio": t["negocio"],
        "instancia": t.get("instancia") or "",
        "config": _cfg(t),
        "simulacao": evolution.simulando(),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  CONEXÃO DO WHATSAPP (QR Code)
# ══════════════════════════════════════════════════════════════════════════════
@app.post("/api/conexao/criar")
async def conexao_criar(tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Cria a instância Evolution API da conta e configura o webhook de opt-out."""
    tid, t = tenant
    if t.get("instancia"):
        return {"ok": True, "instancia": t["instancia"], "ja_existia": True}
    nome = f"LZ{tid}".upper()
    try:
        await asyncio.to_thread(evolution.criar_instancia, nome)
    except Exception as exc:
        _erro(502, f"Erro ao criar instância no WhatsApp: {exc}")

    def _gravar(tenants: dict) -> None:
        tenants[tid]["instancia"] = nome
    TENANTS.atualizar(_gravar)

    if WEBHOOK_PUBLIC_URL:
        try:
            await asyncio.to_thread(
                evolution.definir_webhook, nome, f"{WEBHOOK_PUBLIC_URL}/webhook/evolution/{tid}"
            )
        except Exception as exc:
            log.warning("Webhook não configurado para %s: %s", nome, exc)
    return {"ok": True, "instancia": nome, "ja_existia": False}


@app.get("/api/conexao/qrcode")
async def conexao_qrcode(tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Retorna o QR Code (campo ``base64`` pronto para <img src>)."""
    _, t = tenant
    if not t.get("instancia"):
        _erro(404, "Crie a conexão primeiro (POST /api/conexao/criar).")
    try:
        return await asyncio.to_thread(evolution.qrcode, t["instancia"])
    except Exception as exc:
        _erro(502, f"Erro ao gerar QR Code: {exc}")


@app.get("/api/conexao/status")
async def conexao_status(tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Estado da conexão (``conectado`` = True quando o WhatsApp está pareado)."""
    _, t = tenant
    if not t.get("instancia"):
        return {"conectado": False, "instancia": ""}
    try:
        return await asyncio.to_thread(evolution.status_conexao, t["instancia"])
    except Exception as exc:
        return {"conectado": False, "instancia": t["instancia"], "erro": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
#  CLIENTES DO NEGÓCIO
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/clientes")
async def clientes_listar(tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Lista os clientes da conta, mais recentes primeiro."""
    tid, _ = tenant
    todos = [c for c in CLIENTES.ler().values() if c["tenant"] == tid]
    todos.sort(key=lambda c: c["criado_em"], reverse=True)
    return {"clientes": todos}


@app.post("/api/clientes")
async def clientes_criar(body: ClienteReq, tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Cadastra um cliente manualmente."""
    tid, _ = tenant
    telefone = _normalizar_telefone(body.telefone)
    if len(telefone) < 10:
        _erro(400, "Telefone inválido (use DDD + número).")
    cid = uuid.uuid4().hex[:12]
    cliente = {
        "id": cid,
        "tenant": tid,
        "nome": body.nome.strip(),
        "telefone": telefone,
        "ultima_visita": (_parse_data(body.ultima_visita) or date.today()).isoformat(),
        "obs": body.obs.strip(),
        "opt_out": False,
        "criado_em": datetime.now().isoformat(timespec="seconds"),
        "ultima_msg_em": "",
        "respondeu_em": "",
        "resposta_auto_enviada": False,
    }

    def _inserir(clientes: dict) -> None:
        clientes[cid] = cliente
    CLIENTES.atualizar(_inserir)
    return {"ok": True, "cliente": cliente}


@app.post("/api/clientes/importar")
async def clientes_importar(body: ImportarReq, tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Importa CSV colado (nome;telefone;ultima_visita;obs), ignorando cabeçalho."""
    tid, _ = tenant
    importados, ignorados = 0, 0
    agora = datetime.now().isoformat(timespec="seconds")

    def _importar(clientes: dict) -> None:
        nonlocal importados, ignorados
        for linha in body.csv.splitlines():
            linha = linha.strip()
            if not linha:
                continue
            sep = ";" if ";" in linha else ","
            partes = [p.strip() for p in linha.split(sep)]
            if partes[0].lower() in ("nome", "name"):
                continue
            if len(partes) < 2:
                ignorados += 1
                continue
            telefone = _normalizar_telefone(partes[1])
            if len(telefone) < 10:
                ignorados += 1
                continue
            cid = uuid.uuid4().hex[:12]
            clientes[cid] = {
                "id": cid,
                "tenant": tid,
                "nome": partes[0],
                "telefone": telefone,
                "ultima_visita": (_parse_data(partes[2] if len(partes) > 2 else "") or date.today()).isoformat(),
                "obs": partes[3] if len(partes) > 3 else "",
                "opt_out": False,
                "criado_em": agora,
                "ultima_msg_em": "",
                "respondeu_em": "",
                "resposta_auto_enviada": False,
            }
            importados += 1
    CLIENTES.atualizar(_importar)
    return {"ok": True, "importados": importados, "ignorados": ignorados}


@app.post("/api/clientes/{cliente_id}/optout")
async def clientes_optout(cliente_id: str, body: OptOutReq,
                          tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Alterna o opt-out manual (o webhook também faz isso automaticamente)."""
    tid, _ = tenant

    def _alternar(clientes: dict) -> None:
        c = clientes.get(cliente_id)
        if not c or c["tenant"] != tid:
            return
        c["opt_out"] = body.opt_out
    antes = CLIENTES.ler().get(cliente_id)
    if not antes or antes["tenant"] != tid:
        _erro(404, "Cliente não encontrado.")
    CLIENTES.atualizar(_alternar)
    return {"ok": True}


@app.delete("/api/clientes/{cliente_id}")
async def clientes_remover(cliente_id: str, tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Remove um cliente da base da conta."""
    tid, _ = tenant
    atual = CLIENTES.ler().get(cliente_id)
    if not atual or atual["tenant"] != tid:
        _erro(404, "Cliente não encontrado.")

    def _remover(clientes: dict) -> None:
        clientes.pop(cliente_id, None)
    CLIENTES.atualizar(_remover)
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
#  REATIVAÇÃO DE INATIVOS
# ══════════════════════════════════════════════════════════════════════════════
def _elegiveis_reativacao(tid: str, dias: int) -> list[dict]:
    """Clientes sem visitar há >= N dias, sem opt-out, com dias calculados."""
    hoje = date.today()
    resultado = []
    for c in CLIENTES.ler().values():
        if c["tenant"] != tid or c.get("opt_out"):
            continue
        uv = _parse_data(c.get("ultima_visita", ""))
        if not uv:
            continue
        sem_visitar = (hoje - uv).days
        if sem_visitar >= dias:
            resultado.append({**c, "dias_sem_visitar": sem_visitar})
    resultado.sort(key=lambda c: c["dias_sem_visitar"], reverse=True)
    return resultado


@app.get("/api/reativacao/preview")
async def reativacao_preview(dias: int = 60, tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Prévia de quem receberia a campanha, sem disparar nada."""
    tid, _ = tenant
    return {"elegiveis": _elegiveis_reativacao(tid, dias)}


@app.post("/api/reativacao/disparar")
async def reativacao_disparar(body: ReativacaoReq, tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Enfileira mensagem personalizada para cada inativo elegível."""
    tid, t = tenant
    if not t.get("instancia"):
        _erro(409, "Conecte o WhatsApp antes de disparar.")
    cfg = _cfg(t)
    elegiveis = _elegiveis_reativacao(tid, body.dias)
    agora = datetime.now().isoformat(timespec="seconds")
    template = body.mensagem.strip() or cfg["template_reativacao"]
    novos = []
    for c in elegiveis:
        novos.append({
            "id": uuid.uuid4().hex[:12],
            "tenant": tid,
            "cliente_id": c["id"],
            "agenda_id": "",
            "telefone": c["telefone"],
            "texto": _render(template, t, cliente=c, dias=c["dias_sem_visitar"]),
            "campanha": f"reativacao-{body.dias}d",
            "criado_em": agora,
            "status": "pendente",
            "erro": "",
            "enviado_em": "",
            "simulado": False,
            "prioridade": 1,
        })

    def _enfileirar(fila: dict) -> None:
        for n in novos:
            fila[n["id"]] = n
    FILA.atualizar(_enfileirar)

    def _rearmar_resposta(clientes: dict) -> None:
        # nova campanha rearma o opt-in de resposta automática destes clientes
        for n in novos:
            clientes[n["cliente_id"]].update({"resposta_auto_enviada": False, "respondeu_em": ""})
    CLIENTES.atualizar(_rearmar_resposta)
    return {"ok": True, "enfileirados": len(novos)}


# ══════════════════════════════════════════════════════════════════════════════
#  AGENDA DE LEMBRETES
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/agenda")
async def agenda_listar(tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Lista compromissos da conta, mais próximos primeiro."""
    tid, _ = tenant
    itens = [i for i in AGENDA.ler().values() if i["tenant"] == tid]
    itens.sort(key=lambda i: i.get("quando") or "")
    return {"agenda": itens}


@app.post("/api/agenda")
async def agenda_criar(body: AgendaReq, tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Cadastra um compromisso; o lembrete entra na fila sozinho na janela certa."""
    tid, _ = tenant
    quando = _parse_quando(body.quando)
    if not quando:
        _erro(400, "Data/hora inválida (use AAAA-MM-DDTHH:MM).")
    telefone = _normalizar_telefone(body.telefone)
    if len(telefone) < 10:
        _erro(400, "Telefone inválido.")
    iid = uuid.uuid4().hex[:12]
    item = {
        "id": iid,
        "tenant": tid,
        "cliente_id": "",
        "telefone": telefone,
        "nome": body.nome.strip(),
        "quando": quando.isoformat(timespec="minutes"),
        "mensagem": body.mensagem.strip(),
        "status": "agendado",
        "criado_em": datetime.now().isoformat(timespec="seconds"),
    }

    def _inserir(agenda: dict) -> None:
        agenda[iid] = item
    AGENDA.atualizar(_inserir)
    return {"ok": True, "item": item}


@app.delete("/api/agenda/{item_id}")
async def agenda_cancelar(item_id: str, tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Cancela um compromisso ainda não enfileirado."""
    tid, _ = tenant
    atual = AGENDA.ler().get(item_id)
    if not atual or atual["tenant"] != tid:
        _erro(404, "Compromisso não encontrado.")

    def _cancelar(agenda: dict) -> None:
        if agenda.get(item_id, {}).get("status") == "agendado":
            agenda[item_id]["status"] = "cancelado"
    AGENDA.atualizar(_cancelar)
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
#  LOG DE ENVIOS E CONFIGURAÇÃO
# ══════════════════════════════════════════════════════════════════════════════
@app.get("/api/envios")
async def envios_listar(status: str = "", limite: int = 200,
                        tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Log de envios da conta (filtros opcionais por status e tamanho)."""
    tid, _ = tenant
    itens = [i for i in FILA.ler().values() if i["tenant"] == tid]
    if status:
        itens = [i for i in itens if i["status"] == status]
    itens.sort(key=lambda i: i["criado_em"], reverse=True)
    return {"envios": itens[:limite]}


@app.get("/api/configuracao")
async def config_ler(tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Configuração efetiva da conta (padrões + overrides)."""
    _, t = tenant
    return {"config": _cfg(t)}


@app.put("/api/configuracao")
async def config_gravar(body: ConfigReq, tenant: tuple = Depends(_tenant_atual)) -> dict:
    """Grava overrides de configuração da conta (campos ausentes não mudam)."""
    tid, _ = tenant
    mudancas = {k: v for k, v in body.model_dump().items() if v is not None}
    if mudancas.get("limite_diario", 1) < 1 or mudancas.get("intervalo_seg", 1) < 1:
        _erro(400, "Limite diário e intervalo precisam ser >= 1.")

    def _gravar(tenants: dict) -> None:
        tenants[tid].setdefault("config", {}).update(mudancas)
    TENANTS.atualizar(_gravar)
    return {"ok": True, "config": _cfg(TENANTS.ler()[tid])}


# ══════════════════════════════════════════════════════════════════════════════
#  WEBHOOK DA EVOLUTION (opt-out automático)
# ══════════════════════════════════════════════════════════════════════════════
@app.post("/webhook/evolution/{tenant_id}")
async def webhook_evolution(tenant_id: str, request: Request) -> dict:
    """Recebe messages.upsert e reage: opt-out ("SAIR") ou aceitação ("SIM").

    Na aceitação, marca o cliente como lead quente (``respondeu_em``) e, se a
    conta tiver a resposta automática ligada e o cliente vier de campanha
    recente, enfileira com prioridade máxima o template de reserva.
    """
    payload = await request.json()
    telefone, texto = evolution.extrair_mensagem_recebida(payload)
    if not telefone or not texto:
        return {"ok": True, "acao": "ignorado"}
    cid, cliente = _cliente_por_telefone(tenant_id, telefone)
    if not cid:
        return {"ok": True, "acao": "ignorado"}
    agora = datetime.now().isoformat(timespec="seconds")

    if any(p in texto.lower() for p in PALAVRAS_OPT_OUT):
        def _opt_out(clientes: dict) -> None:
            clientes[cid]["opt_out"] = True
        CLIENTES.atualizar(_opt_out)

        def _derrubar_fila(fila: dict) -> None:
            for item in fila.values():
                if item["tenant"] == tenant_id and item["status"] == "pendente" \
                        and item.get("cliente_id") == cid:
                    item["status"] = "opt_out"
        FILA.atualizar(_derrubar_fila)
        log.info("Opt-out via webhook: tenant %s, telefone ...%s", tenant_id, telefone[-4:])
        return {"ok": True, "acao": "opt_out", "clientes": 1}

    tenant = TENANTS.ler().get(tenant_id)
    if not tenant:
        return {"ok": True, "acao": "ignorado"}
    cfg = _cfg(tenant)

    if _eh_resposta_sim(texto):
        def _marcar_quente(clientes: dict) -> None:
            clientes[cid]["respondeu_em"] = agora
        CLIENTES.atualizar(_marcar_quente)

        auto_liberada = (
            cfg.get("resposta_auto_ativa", True)
            and not cliente.get("resposta_auto_enviada")
            and _reativacao_recente(cid)
        )
        if not auto_liberada:
            log.info("SIM de ...%s registrado sem resposta automática", telefone[-4:])
            return {"ok": True, "acao": "resposta_sim", "auto": False}

        resposta = {
            "id": uuid.uuid4().hex[:12],
            "tenant": tenant_id,
            "cliente_id": cid,
            "agenda_id": "",
            "telefone": cliente["telefone"],
            "texto": _render(cfg["template_resposta_sim"], tenant, cliente=cliente),
            "campanha": "resposta-sim",
            "criado_em": agora,
            "status": "pendente",
            "erro": "",
            "enviado_em": "",
            "simulado": False,
            "prioridade": 0,  # furar a fila: quem respondeu SIM não pode esperar
        }

        def _enfileirar_resposta(fila: dict) -> None:
            fila[resposta["id"]] = resposta
        FILA.atualizar(_enfileirar_resposta)

        def _marcar_enviada(clientes: dict) -> None:
            clientes[cid]["resposta_auto_enviada"] = True
        CLIENTES.atualizar(_marcar_enviada)
        log.info("Resposta automática enfileirada para ...%s", telefone[-4:])
        return {"ok": True, "acao": "resposta_sim", "auto": True}

    # ── IA: cliente quente propondo dia/horário vira agenda + confirmação ──
    if not cliente.get("respondeu_em") or not cfg.get("ia_agendamento_ativa", True):
        return {"ok": True, "acao": "ignorado"}
    resultado = await asyncio.to_thread(
        ia.interpretar_horario, cliente["nome"], tenant["negocio"], texto
    )
    quando = _parse_quando(resultado.get("quando") or "")
    if not quando or not (
        datetime.now() - timedelta(hours=1) <= quando <= datetime.now() + timedelta(days=60)
    ):
        return {"ok": True, "acao": "ignorado", "ia": resultado.get("fonte", "")}
    quando_iso = quando.isoformat(timespec="minutes")
    if any(
        i["tenant"] == tenant_id and i.get("cliente_id") == cid
        and i.get("status") in ("agendado", "na_fila") and i.get("quando") == quando_iso
        for i in AGENDA.ler().values()
    ):
        return {"ok": True, "acao": "agendado_via_ia", "duplicado": True}

    item = {
        "id": uuid.uuid4().hex[:12],
        "tenant": tenant_id,
        "cliente_id": cid,
        "telefone": cliente["telefone"],
        "nome": cliente["nome"],
        "quando": quando_iso,
        "mensagem": "",
        "status": "agendado",
        "origem": "ia",
        "criado_em": agora,
    }

    def _agendar(agenda: dict) -> None:
        agenda[item["id"]] = item
    AGENDA.atualizar(_agendar)

    confirmacao = {
        "id": uuid.uuid4().hex[:12],
        "tenant": tenant_id,
        "cliente_id": cid,
        "agenda_id": item["id"],
        "telefone": cliente["telefone"],
        "texto": _render(cfg["template_confirmacao"], tenant, cliente=cliente,
                         quando=quando.strftime("%d/%m às %H:%M")),
        "campanha": "ia-confirmacao",
        "criado_em": agora,
        "status": "pendente",
        "erro": "",
        "enviado_em": "",
        "simulado": False,
        "prioridade": 0,
    }

    def _enfileirar_confirmacao(fila: dict) -> None:
        fila[confirmacao["id"]] = confirmacao
    FILA.atualizar(_enfileirar_confirmacao)
    log.info("Agendamento via IA (%s) para ...%s em %s",
             resultado.get("fonte"), telefone[-4:], quando_iso)
    return {"ok": True, "acao": "agendado_via_ia", "quando": quando_iso,
            "fonte": resultado.get("fonte", "")}


# ── Painel estático ───────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@app.get("/healthz")
async def healthz() -> dict:
    """Verificação de vida leve para healthcheck do Docker e monitoramento."""
    return {"ok": True, "simulacao": evolution.simulando()}


@app.get("/")
async def painel() -> FileResponse:
    """Serve o painel (SPA sem build)."""
    return FileResponse(str(Path(__file__).parent / "static" / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORTA)
