"""Cliente da Evolution API (WhatsApp) com modo simulação para desenvolvimento.

Os endpoints e o shape de payload foram copiados da integração que já roda em
produção no AletheIA (Evolution API v2, Baileys):

- ``POST /instance/create``            → cria instância (``integration: WHATSAPP-BAILEYS``)
- ``GET  /instance/connect/{nome}``    → retorna ``{"base64": <data-uri do QR>}``
- ``GET  /instance/connectionState/{n}``→ ``{"instance": {"state": "open"|"connecting"|...}}``
- ``POST /message/sendText/{nome}``    → ``{"number": ..., "text": ...}``
- ``POST /webhook/set/{nome}``         → configura webhook de eventos

Autenticação pelo header ``apikey``. Quando ``MODO_SIMULACAO=1`` (ou quando
``EVOLUTION_API_URL`` está vazio), nenhum HTTP sai do processo: as funções
devolvem respostas canned para o fluxo completo poder ser testado localmente.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any, Optional

import httpx

log = logging.getLogger("lembrazap.evolution")

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
MODO_SIMULACAO = os.getenv("MODO_SIMULACAO", "") == "1" or not EVOLUTION_API_URL

_TIMEOUT = httpx.Timeout(30.0)

# QR fake (SVG) para o painel renderizar algo em modo simulação.
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


def simulando() -> bool:
    """Indica se o cliente está em modo simulação (sem chamadas reais)."""
    return MODO_SIMULACAO


def criar_instancia(nome: str) -> dict:
    """Cria a instância WhatsApp do tenant na Evolution API (idempotente no servidor)."""
    if MODO_SIMULACAO:
        log.info("[simulação] criar_instancia(%s)", nome)
        return {"ok": True, "simulado": True, "instancia": nome}
    resposta = httpx.post(
        f"{EVOLUTION_API_URL}/instance/create",
        json={"instanceName": nome, "qrcode": True, "integration": "WHATSAPP-BAILEYS"},
        headers=_headers(),
        timeout=_TIMEOUT,
    )
    resposta.raise_for_status()
    return resposta.json()


def qrcode(nome: str) -> dict:
    """Gera o QR Code de pareamento; o campo ``base64`` já é um data-uri pronto para <img>."""
    if MODO_SIMULACAO:
        return {"base64": _QR_DATA_URI, "simulado": True}
    resposta = httpx.get(
        f"{EVOLUTION_API_URL}/instance/connect/{nome}",
        headers={"apikey": EVOLUTION_API_KEY},
        timeout=_TIMEOUT,
    )
    resposta.raise_for_status()
    return resposta.json()


def status_conexao(nome: str) -> dict:
    """Consulta o estado da conexão; ``conectado`` é True quando o estado é ``open``."""
    if MODO_SIMULACAO:
        return {"conectado": True, "instancia": nome, "estado": "open", "simulado": True}
    resposta = httpx.get(
        f"{EVOLUTION_API_URL}/instance/connectionState/{nome}",
        headers={"apikey": EVOLUTION_API_KEY},
        timeout=_TIMEOUT,
    )
    resposta.raise_for_status()
    estado = resposta.json().get("instance", {}).get("state")
    return {"conectado": estado == "open", "instancia": nome, "estado": estado}


def enviar_texto(nome: str, numero: str, texto: str) -> dict:
    """Envia mensagem de texto a um número via instância do tenant."""
    if MODO_SIMULACAO:
        log.info("[simulação] sendText %s → %s: %.60s", nome, numero, texto)
        return {"ok": True, "simulado": True, "key": {"id": f"SIM{numero[-4:]}{os.getpid()}"}}
    resposta = httpx.post(
        f"{EVOLUTION_API_URL}/message/sendText/{nome}",
        json={"number": numero, "text": texto},
        headers=_headers(),
        timeout=_TIMEOUT,
    )
    resposta.raise_for_status()
    return resposta.json()


def definir_webhook(nome: str, url: str, eventos: Optional[list] = None) -> dict:
    """Aponta o webhook da instância para o nosso endpoint de opt-out (falha não é fatal)."""
    if MODO_SIMULACAO:
        log.info("[simulação] webhook %s → %s", nome, url)
        return {"ok": True, "simulado": True}
    resposta = httpx.post(
        f"{EVOLUTION_API_URL}/webhook/set/{nome}",
        json={
            "enabled": True,
            "url": url,
            "webhookByEvents": False,
            "webhookBase64": False,
            "events": eventos or ["MESSAGES_UPSERT"],
        },
        headers=_headers(),
        timeout=_TIMEOUT,
    )
    resposta.raise_for_status()
    return resposta.json()


def extrair_mensagem_recebida(payload: Any) -> tuple[str, str]:
    """Extrai (telefone, texto) de um evento messages.upsert, tolerando shapes v1 e v2.

    Retorna tupla vazia ("", "") quando o evento não é mensagem recebida de contato.
    """
    if not isinstance(payload, dict):
        return "", ""
    dados = payload.get("data", payload)
    chave = dados.get("key", {}) or {}
    if chave.get("fromMe"):
        return "", ""
    jid = str(chave.get("remoteJid", ""))
    if not jid or "@s.whatsapp.net" not in jid:
        return "", ""
    telefone = jid.split("@")[0]
    mensagem = dados.get("message", {}) or {}
    texto = (
        mensagem.get("conversation")
        or (mensagem.get("extendedTextMessage") or {}).get("text")
        or (mensagem.get("imageMessage") or {}).get("caption")
        or ""
    )
    return telefone, str(texto)
