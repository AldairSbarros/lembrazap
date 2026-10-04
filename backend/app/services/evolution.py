"""Cliente da Evolution API (WhatsApp), com modo simulação para desenvolvimento.

Endpoints e shape de payload da Evolution API v2 (Baileys):

- ``POST /instance/create``             → cria instância (``WHATSAPP-BAILEYS``)
- ``GET  /instance/connect/{nome}``     → ``{"base64": <data-uri do QR>}``
- ``GET  /instance/connectionState/{n}``→ ``{"instance": {"state": "open"|...}}``
- ``POST /message/sendText/{nome}``     → ``{"number": ..., "text": ...}``
- ``POST /webhook/set/{nome}``          → aponta os eventos para o nosso backend

Autenticação pelo header ``apikey``. Quando ``MODO_SIMULACAO=1`` (ou quando
``EVOLUTION_API_URL`` está vazio) nenhum HTTP sai do processo: as funções
devolvem respostas canned para o fluxo completo poder ser testado e demonstrado
sem tocar em número real.
"""
from __future__ import annotations

import base64
import logging
import os
import re
from typing import Any, Optional

import requests

log = logging.getLogger("lembrazap.evolution")

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
MODO_SIMULACAO = os.getenv("MODO_SIMULACAO", "") == "1" or not EVOLUTION_API_URL

TIMEOUT = 30.0

_NAO_DIGITOS = re.compile(r"\D")

# QR fictício (SVG) para o painel renderizar algo em modo simulação.
_QR_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='224' height='224'>"
    "<rect width='224' height='224' fill='#ffffff'/>"
    "<rect x='16' y='16' width='60' height='60' fill='#111'/>"
    "<rect x='148' y='16' width='60' height='60' fill='#111'/>"
    "<rect x='16' y='148' width='60' height='60' fill='#111'/>"
    "<text x='112' y='118' font-family='sans-serif' font-size='14' "
    "text-anchor='middle' fill='#333'>QR SIMULADO</text>"
    "<text x='112' y='136' font-family='sans-serif' font-size='10' "
    "text-anchor='middle' fill='#777'>conecte na VPS</text></svg>"
)
_QR_DATA_URI = "data:image/svg+xml;base64," + base64.b64encode(_QR_SVG.encode()).decode()


def _headers() -> dict:
    """Headers padrão das chamadas à Evolution API (apikey + JSON)."""
    return {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}


def normalizar_numero(bruto: str) -> str:
    """Reduz o telefone só a dígitos (a Evolution exige o número cru)."""
    return _NAO_DIGITOS.sub("", bruto or "")


def simulando() -> bool:
    """Indica se o cliente está em modo simulação (sem chamadas reais)."""
    return MODO_SIMULACAO


def criar_instancia(nome_instancia: str) -> dict:
    """Cria a instância WhatsApp do tenant (idempotente no servidor da Evolution)."""
    if MODO_SIMULACAO:
        log.info("[simulação] criar_instancia(%s)", nome_instancia)
        return {"ok": True, "simulado": True, "instancia": nome_instancia}
    resposta = requests.post(
        f"{EVOLUTION_API_URL}/instance/create",
        json={"instanceName": nome_instancia, "qrcode": True, "integration": "WHATSAPP-BAILEYS"},
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resposta.raise_for_status()
    return resposta.json()


def obter_qrcode(nome_instancia: str) -> dict:
    """Gera o QR Code de pareamento; o campo ``base64`` já é um data-uri pronto para ``<img>``."""
    if MODO_SIMULACAO:
        return {"base64": _QR_DATA_URI, "simulado": True}
    resposta = requests.get(
        f"{EVOLUTION_API_URL}/instance/connect/{nome_instancia}",
        headers={"apikey": EVOLUTION_API_KEY},
        timeout=TIMEOUT,
    )
    resposta.raise_for_status()
    return resposta.json()


def status_conexao(nome_instancia: str) -> dict:
    """Consulta o estado da conexão; ``conectado`` é True quando o estado é ``open``."""
    if MODO_SIMULACAO:
        return {"conectado": True, "instancia": nome_instancia, "estado": "open", "simulado": True}
    resposta = requests.get(
        f"{EVOLUTION_API_URL}/instance/connectionState/{nome_instancia}",
        headers={"apikey": EVOLUTION_API_KEY},
        timeout=TIMEOUT,
    )
    resposta.raise_for_status()
    estado = resposta.json().get("instance", {}).get("state")
    return {"conectado": estado == "open", "instancia": nome_instancia, "estado": estado}


def enviar_texto(nome_instancia: str, numero: str, texto: str) -> dict:
    """Envia mensagem de texto a um número via instância do tenant.

    É esta função que o worker chama para disparar o lembrete de verdade; sem ela
    nada sai do painel (a fila era marcada como enviada sem envio nenhum).
    """
    destino = normalizar_numero(numero)
    if MODO_SIMULACAO:
        log.info("[simulação] sendText %s → %s: %.60s", nome_instancia, destino, texto)
        return {"ok": True, "simulado": True, "key": {"id": f"SIM{numero[-4:]}"}}
    resposta = requests.post(
        f"{EVOLUTION_API_URL}/message/sendText/{nome_instancia}",
        json={"number": destino, "text": texto},
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resposta.raise_for_status()
    return resposta.json()


def definir_webhook(nome_instancia: str, url: str, eventos: Optional[list] = None) -> dict:
    """Aponta o webhook da instância para o nosso endpoint de eventos.

    Sem isso a Evolution não notifica nada e o fluxo de SIM/ADIAR/SAIR
    simplesmente não existe em produção.

    A partir da Evolution 2.3.x o corpo é validado por schema e exige o bloco
    ``webhook`` aninhado — enviar os campos na raiz devolve 400 com
    ``instance requires property "webhook"``. Os eventos vão duplicados no topo
    porque a 2.3.x também os valida ali.
    """
    if MODO_SIMULACAO:
        log.info("[simulação] webhook %s → %s", nome_instancia, url)
        return {"ok": True, "simulado": True}
    resposta = requests.post(
        f"{EVOLUTION_API_URL}/webhook/set/{nome_instancia}",
        json={
            "webhook": {
                "enabled": True,
                "url": url,
                "events": eventos or ["MESSAGES_UPSERT"],
            },
            "events": eventos or ["MESSAGES_UPSERT"],
        },
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resposta.raise_for_status()
    return resposta.json()


def extrair_mensagem_recebida(payload: Any) -> tuple[str, str]:
    """Extrai (telefone, texto) de um evento ``messages.upsert``.

    Tolera os shapes v1 e v2 e valida o JID para não tratar grupo ou status
    como conversa de cliente. Devolve ``("", "")`` quando não é mensagem recebida.
    """
    if not isinstance(payload, dict):
        return "", ""
    dados = payload.get("data", payload)
    if not isinstance(dados, dict):
        return "", ""
    chave = dados.get("key") or {}
    if not isinstance(chave, dict) or chave.get("fromMe"):
        return "", ""
    jid = str(chave.get("remoteJid", ""))
    if not jid or "@s.whatsapp.net" not in jid:
        return "", ""
    telefone = jid.split("@")[0]
    mensagem = dados.get("message") or {}
    if not isinstance(mensagem, dict):
        return "", ""
    texto = (
        mensagem.get("conversation")
        or (mensagem.get("extendedTextMessage") or {}).get("text")
        or (mensagem.get("imageMessage") or {}).get("caption")
        or ""
    )
    return telefone, str(texto).strip()