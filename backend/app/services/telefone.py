"""Normalização de telefone e utilidades de texto compartilhadas.

O mesmo cliente chega por caminhos diferentes — cadastro manual, importação de
CSV, confirmação por WhatsApp — e cada um traz o número num formato diferente.
`(11) 99999-8888`, `+55 11 99999 8888` e `11999998888` precisam virar a mesma
chave, senão o mesmo cliente entra três vezes na base e o motor de inatividade
conta ele como três pessoas diferentes.
"""

# DDI do Brasil. Números sem DDI são assumidos brasileiros.
DDI_BRASIL = "55"


def apenas_digitos(valor: str) -> str:
    """Mantém só os dígitos do valor recebido."""
    return "".join(ch for ch in (valor or "") if ch.isdigit())


def normalizar_telefone(valor: str) -> str | None:
    """Reduz o telefone ao formato canônico de dígitos com DDI.

    Retorna `None` quando não dá para montar um celular brasileiro. O sistema
    **não** adivinha DDD: se o número não vier com 55, assume que o usuário
    digitou o número local completo (DDD + número).

    Exige 11 dígitos locais (2 de DDD + 9) porque WhatsApp no Brasil só existe em
    celular. Aceitar os 10 dígitos do telefone fixo antigo faria o contato passar
    pela importação e falhar só no envio, que é pior: o dono veria "importado com
    sucesso" e a mensagem nunca sairia.

    >>> normalizar_telefone("(11) 99999-8888")
    '5511999998888'
    >>> normalizar_telefone("+55 11 99999-8888")
    '5511999998888'
    >>> normalizar_telefone("11999998888")
    '5511999998888'
    >>> normalizar_telefone("1123456789") is None   # fixo de 8 dígitos
    True
    >>> normalizar_telefone("123") is None
    True
    """
    digitos = apenas_digitos(valor)

    if digitos.startswith("0"):
        # Alguns exportadores gravam o zero inicial do DDI (0xx) ou do número.
        digitos = digitos.lstrip("0")

    if digitos.startswith(DDI_BRASIL):
        numero = digitos[len(DDI_BRASIL):]
    else:
        digitos = DDI_BRASIL + digitos
        numero = digitos[len(DDI_BRASIL):]

    # 2 dígitos de DDD + 9 do celular. 10 dígitos é telefone fixo, que não
    # recebe WhatsApp — recusar aqui evita import com sucesso e envio impossível.
    if len(numero) == 11:
        return digitos

    return None


def telefone_equivale(a: str, b: str) -> bool:
    """Compara dois telefones já normalizados (ou não) pelo mesmo criterio."""
    na, nb = normalizar_telefone(a), normalizar_telefone(b)
    if na and nb:
        return na == nb
    return (a or "").strip() == (b or "").strip()


def telefone_destino(valor: str) -> str:
    """Normaliza para o envio, mas devolve o original se não conseguir.

    Preferimos errar o formato e deixar a Evolution recusar (com erro visível na
    fila) do que trocar silenciosamente o número de destino. Um número
    normalizado errado entrega a mensagem para a pessoa errada, e isso não tem
    como desfazer.
    """
    return normalizar_telefone(valor) or apenas_digitos(valor) or (valor or "").strip()


def mascarar_telefone(telefone: str) -> str:
    """`(11) 99999-8888` para exibição na interface."""
    d = apenas_digitos(telefone)
    if len(d) == 13 and d.startswith(DDI_BRASIL):
        d = d[2:]
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return telefone or ""