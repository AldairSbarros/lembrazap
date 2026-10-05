"""Catálogo de planos do LembraZap.

Tudo aqui é **dado editável**, não regra de negócio: para mudar preço ou limite basta
alterar esta tabela e reiniciar a API. Nenhum valor de plano aparece espalhado pelo
código, o que evita o erro clássico de cobrar um preço e aplicar outro.

Cada plano tem:
- `preco_centavos`: preço mensal de exibição no painel.
- `limite_clientes`: máximo de clientes cadastrados (bloqueia a importação acima disso).
- `limite_mensagens_mes`: teto de disparos no mês corrente.
- `stripe_price_id`: id do Price no Stripe, lido do ambiente para o código ficar
  igual em todos os lugares. Se estiver vazio, a cobrança é gerenciada pelo admin.
"""

import os

PRECOS_PADRAO = {
    "starter": 4900,
    "pro": 9900,
    "business": 19900,
}

LIMITES_PADRAO = {
    "starter": {"clientes": 300, "mensagens": 2000},
    "pro": {"clientes": 1000, "mensagens": 8000},
    "business": {"clientes": 3000, "mensagens": 25000},
}

ROTULOS = {
    "starter": "Starter",
    "pro": "Pro",
    "business": "Business",
}

DESCRICOES = {
    "starter": "Para o profissional solo que está começando.",
    "pro": "Para o negócio com agenda cheia e equipe.",
    "business": "Para operações com múltiplos atendentes e volume alto.",
}

# Plano com destaque visual na tela de planos. Dado de apresentação, então fica
# aqui com o resto do catálogo: a tela de planos é gerada a partir dele, e um
# destaque escrito dentro do JSX não sobrevive a uma troca de plano.
DESTAQUES = {"pro"}

# Recursos que o card mostra abaixo do preço. Os dois primeiros limites já são
# renderizados à parte, então não se repetem aqui.
RECURSOS = {
    "starter": ["Importação por planilha (CSV)", "Mensagens de reativação automática"],
    "pro": ["Agendamentos ilimitados", "Mensagens de reativação automática"],
    "business": ["Agendamentos ilimitados", "Mensagens de reativação automática", "Relatório de comparação por período"],
}


def _preco(chave: str) -> int:
    """Preço do ambiente tem precedência; senão usa o padrão do catálogo."""
    do_env = os.getenv(f"STRIPE_PRECIO_{chave.upper()}", "").strip()
    return int(do_env) if do_env.isdigit() else PRECOS_PADRAO.get(chave, 0)


def _stripe_price(chave: str) -> str:
    return os.getenv(f"STRIPE_PRICE_ID_{chave.upper()}", "").strip()


def listar_planos() -> list[dict]:
    """Planos prontos para o frontend: etiqueta, preço em reais e limites."""
    planos = []
    for chave, limites in LIMITES_PADRAO.items():
        centavos = _preco(chave)
        planos.append(
            {
                "chave": chave,
                "nome": ROTULOS.get(chave, chave),
                "descricao": DESCRICOES.get(chave, ""),
                "preco_centavos": centavos,
                "preco_reais": f"{centavos / 100:.2f}".replace(".", ","),
                "limite_clientes": limites["clientes"],
                "limite_mensagens_mes": limites["mensagens"],
                "destaque": chave in DESTAQUES,
                "recursos": RECURSOS.get(chave, []),
                # Sem Price configurado o checkout do Stripe não pode ser aberto.
                "disponivel_stripe": bool(_stripe_price(chave)),
            }
        )
    return planos


def obter_plano(chave: str) -> dict | None:
    for plano in listar_planos():
        if plano["chave"] == (chave or "").strip().lower():
            return plano
    return None


def limite_clientes(chave: str) -> int:
    return LIMITES_PADRAO.get((chave or "").lower(), LIMITES_PADRAO["business"])["clientes"]


def limite_mensagens(chave: str) -> int:
    return LIMITES_PADRAO.get((chave or "").lower(), LIMITES_PADRAO["business"])["mensagens"]


def stripe_price_id(chave: str) -> str:
    """Id do Price no Stripe. Vazio quando a cobrança é feita pelo admin."""
    return _stripe_price((chave or "").lower())