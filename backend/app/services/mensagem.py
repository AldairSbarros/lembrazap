"""Montagem do texto das mensagens disparadas ao cliente.

O renderizador original usava `str.format()` direto. Um placeholder digitado
errado pelo dono (`{cliente}` em vez de `{nome}`) levantava `KeyError` dentro do
`for` de tenants do worker, e como o `try/except` envolvia o laço inteiro, um
único template ruim impedia o disparo dos outroshwa-establishments. Aqui um
placeholder inválido vira aviso, não exceção.
"""

import re

# Placeholders aceitos nos modelos de mensagem do painel.
PLACEHOLDERS = ("nome", "negocio", "servico", "data", "horario", "telefone", "dias")

_PADRAO_REATIVACAO = (
    "Fala {nome}, faz um tempão que não te vemos por aqui na {negocio}! "
    "Passa pra tomar um café com a gente. Se quiser, responde aqui que a gente "
    "confere a agenda pra você."
)

_PADRAO_LEMBRETE = (
    "Olá {nome}, lembramos do seu agendamento na {negocio} dia {data} às {horario}."
)


def _detectar_placeholders(template: str) -> tuple[str, list[str]]:
    """Separa o que é placeholder conhecido do que é lixo.

    Devolve (texto_irrigado, placeholders_desconhecidos).
    """
    conhecidos, desconhecidos, falhas = set(), [], 0

    def substituir(m: re.Match) -> str:
        nonlocal falhas
        chave = m.group(1)
        if chave in PLACEHOLDERS:
            conhecidos.add(chave)
            return m.group(0)
        desconhecidos.append(chave)
        falhas += 1
        return ""

    texto = re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", substituir, template or "")
    return texto, desconhecidos


def _falhas_de_formato(texto: str) -> int:
    """Conta chaves desbalanceadas, para avisar sem quebrar."""
    return texto.count("{") - texto.count("}")


def formatar_mensagem(
    template: str,
    nome: str | None,
    negocio: str | None,
    servico: str | None = None,
    quando=None,
    telefone: str | None = None,
    dias_sem_visita: int | None = None,
    padrao: str = _PADRAO_LEMBRETE,
) -> str:
    """Substitui os placeholders pelo contexto real do cliente.

    Nunca levanta por causa do conteúdo do template. Devolve o texto pronto para
    envio.
    """
    texto = template.strip() if template and template.strip() else padrao

    contexto = {
        "nome": (nome or "").strip() or "cliente",
        "negocio": (negocio or "").strip() or "nosso espaço",
        "servico": (servico or "").strip() or "atendimento",
        "data": quando.strftime("%d/%m") if quando else "",
        "horario": quando.strftime("%H:%M") if quando else "",
        "telefone": telefone or "",
        "dias": str(dias_sem_visita) if dias_sem_visita else "",
    }

    for chave in PLACEHOLDERS:
        texto = texto.replace("{" + chave + "}", contexto[chave])

    return texto.strip()


def validar_template(template: str) -> list[str]:
    """Lista os problemas do modelo, para o painel avisar antes de salvar.

    Devolve lista de avisos; lista vazia significa template utilizável.
    """
    avisos: list[str] = []

    if template and _falhas_de_formato(template) != 0:
        avisos.append("Há chaves { ou } desbalanceadas no texto.")

    _, desconhecidos = _detectar_placeholders(template or "")
    if desconhecidos:
        unicos = sorted(set(desconhecidos))
        avisos.append(
            "Placeholders desconhecidos serão removidos: "
            + ", ".join("{" + p + "}" for p in unicos)
            + ". Válidos: "
            + ", ".join("{" + p + "}" for p in PLACEHOLDERS)
        )

    return avisos