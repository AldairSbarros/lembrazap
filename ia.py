"""Interpretação de respostas de clientes com LLM (Groq primário, Gemini fallback).

Quando um cliente que já respondeu SIM à campanha escreve algo como
"posso terça às 14h30?" ou "amanhã de manhã funciona", este módulo extrai a
data/hora proposta para o agendamento automático. A chamada é barata (modelo
pequeno, temperature 0, resposta em JSON) e só acontece para clientes dentro da
janela de conversa — nunca para a base inteira.

Em ``MODO_SIMULACAO`` (ou sem chaves de IA configuradas) usa um parser local por
regex, suficiente para demonstrar e testar o fluxo sem custo.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import httpx

log = logging.getLogger("lembrazap.ia")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MODELO_GROQ = os.getenv("IA_MODELO_GROQ", "llama-3.1-8b-instant")
MODELO_GEMINI = os.getenv("IA_MODELO_GEMINI", "gemini-2.5-flash")
MODO_SIMULACAO = os.getenv("MODO_SIMULACAO", "") == "1"

_TIMEOUT = httpx.Timeout(20.0)

_DIAS_SEMANA = {
    "segunda": 0, "terca": 1, "terça": 1, "quarta": 2, "quinta": 3,
    "sexta": 4, "sabado": 5, "sábado": 5, "domingo": 6,
}


def ia_disponivel() -> bool:
    """True quando há pelo menos uma chave de IA configurada (ou simulação ativa)."""
    return MODO_SIMULACAO or bool(GROQ_API_KEY or GEMINI_API_KEY)


def _extrair_json(texto: str) -> dict:
    """Extrai o primeiro objeto JSON da resposta do modelo, tolerando cercas de código."""
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto, flags=re.MULTILINE)
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fim <= inicio:
        return {}
    try:
        dado = json.loads(texto[inicio:fim + 1])
        return dado if isinstance(dado, dict) else {}
    except json.JSONDecodeError:
        return {}


def _prompt(nome_cliente: str, negocio: str, texto: str, agora: datetime) -> str:
    """Monta o prompt de extração de horário, com o relógio atual como referência."""
    return (
        f"Hoje é {agora.strftime('%Y-%m-%d')} ({agora.strftime('%A')}), "
        f"{agora.strftime('%H:%M')} no horário do negócio.\n"
        f"O cliente {nome_cliente} do {negocio} respondeu à mensagem de agendamento:\n"
        f'"{texto}"\n'
        "Extraia a data e hora que ele está propondo para o compromisso. "
        "Responda SOMENTE com JSON no formato {\"quando\": \"AAAA-MM-DDTHH:MM\"} "
        'ou {"quando": ""} se não houver proposta clara de horário.'
    )


def _chamar_groq(prompt: str) -> str:
    """Chama o modelo pequeno da Groq (barato e rápido) para extração."""
    resposta = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        json={
            "model": MODELO_GROQ,
            "temperature": 0,
            "max_tokens": 60,
            "messages": [{"role": "user", "content": prompt}],
        },
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        timeout=_TIMEOUT,
    )
    resposta.raise_for_status()
    return resposta.json()["choices"][0]["message"]["content"]


def _chamar_gemini(prompt: str) -> str:
    """Fallback de extração via Gemini quando a Groq falha."""
    resposta = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO_GEMINI}:generateContent",
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 60},
        },
        headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
        timeout=_TIMEOUT,
    )
    resposta.raise_for_status()
    return resposta.json()["candidates"][0]["content"]["parts"][0]["text"]


def _parse_simulacao(texto: str, agora: datetime) -> str:
    """Parser local por regex usado em simulação: exige hora, dia é opcional."""
    m = re.search(r"\b(\d{1,2})[:h](\d{2})\b", texto.lower())
    if not m:
        return ""
    hora, minuto = int(m.group(1)), int(m.group(2))
    baixo = texto.lower()
    if "amanha" in baixo or "amanhã" in baixo:
        dia = agora.date() + timedelta(days=1)
    elif "hoje" in baixo:
        dia = agora.date()
    else:
        dia = None
        for nome, numero in _DIAS_SEMANA.items():
            if nome in baixo:
                delta = (numero - agora.weekday()) % 7 or 7
                dia = agora.date() + timedelta(days=delta)
                break
        dia = dia or (agora.date() + timedelta(days=1))
    return datetime.combine(dia, datetime.min.time().replace(hour=hora, minute=minuto)) \
        .isoformat(timespec="minutes")


def interpretar_horario(nome_cliente: str, negocio: str, texto: str,
                        agora: Optional[datetime] = None) -> dict:
    """Extrai a proposta de horário da resposta do cliente.

    Retorna ``{"quando": "AAAA-MM-DDTHH:MM" ou "", "fonte": ...}``. Nunca levanta
    exceção: falha de rede/modelo vira ``quando`` vazio e o fluxo segue humano.
    """
    agora = agora or datetime.now()
    if MODO_SIMULACAO:
        return {"quando": _parse_simulacao(texto, agora), "fonte": "simulacao"}
    if not (GROQ_API_KEY or GEMINI_API_KEY):
        return {"quando": "", "fonte": "nenhuma"}
    prompt = _prompt(nome_cliente, negocio, texto, agora)
    for fonte, chamar in (("groq", _chamar_groq), ("gemini", _chamar_gemini)):
        chave = GROQ_API_KEY if fonte == "groq" else GEMINI_API_KEY
        if not chave:
            continue
        try:
            dado = _extrair_json(chamar(prompt))
            quando = str(dado.get("quando") or "").strip()
            return {"quando": quando, "fonte": fonte}
        except Exception as exc:
            log.warning("IA (%s) falhou ao interpretar resposta: %s", fonte, exc)
    return {"quando": "", "fonte": "falha"}
