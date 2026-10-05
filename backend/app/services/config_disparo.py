"""Leitura tipada das configurações do tenant.

As regras de disparo vivem num JSON (`Tenant.config`) para não exigir migration
a cada ajuste do dono. Isso deixa o acesso espalhado por `config.get(...)` com
defaults repetidos — e foi assim que `dias_sem_visitar` acabou inexistente
enquanto o campo `ultima_visita` já existia no banco. Centralizar aqui é o que
permite o painel e o worker lerem exatamente as mesmas regras.
"""

from dataclasses import dataclass

# Sentinela: ausente no JSON significa usar este valor. Precisa ser algo que
# nunca seja um valor válido de configuração, para distinguir "não configurado"
# de "configurado com este número".
_NAO_DEFINIDO = object()

# Intervalos aceitos para reativação de cliente inativo.
DIAS_MINIMO = 7
DIAS_MAXIMO = 365


@dataclass(frozen=True)
class RegrasDisparo:
    """Regras de disparo de um tenant, já com defaults aplicados."""

    # Lembrete de consulta marcada
    horas_antecedencia: int = 24

    # Reativação de cliente inativo
    dias_sem_visitar: int = 45
    reativacao_ativa: bool = False
    limite_por_dia: int = 50

    # Texto de cada tipo de campanha
    mensagem_lembrete: str = ""
    mensagem_reativacao: str = ""

    # Pausa geral de envios
    envios_pausados: bool = False


def _inteiro(valor, padrao: int, minimo: int, maximo: int) -> int:
    """Converte para int respeitando faixa, sem levantar exceção.

    O JSON pode ter vindo com string (edição manual), `null`, ou um número fora
    da faixa. Nenhum desses pode derrubar o worker inteiro.
    """
    if valor is _NAO_DEFINIDO or valor is None or valor == "":
        return padrao
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return padrao
    return max(minimo, min(maximo, numero))


def _booleano(valor, padrao: bool) -> bool:
    if valor is _NAO_DEFINIDO or valor is None:
        return padrao
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        return valor.strip().lower() in ("1", "true", "sim", "on", "yes")
    return bool(valor)


def _texto(valor, padrao: str = "") -> str:
    if valor is _NAO_DEFINIDO or valor is None:
        return padrao
    return str(valor)


def ler_regras(config: dict | None) -> RegrasDisparo:
    """Converte o JSON bruto do tenant em regras com tipos garantidos.

    Reconhece tanto o nome atual quanto o legado: `mensagem_modelo` era o campo
    único de texto; agora há um por campanha, com o antigo mantido como
    fallback para não quebrar contas que nunca salvaram as regras novas.
    """
    dados = config if isinstance(config, dict) else {}
    cfg = dados.get

    return RegrasDisparo(
        horas_antecedencia=_inteiro(cfg("horas_antecedencia", _NAO_DEFINIDO), 24, 1, 720),
        dias_sem_visitar=_inteiro(cfg("dias_sem_visitar", _NAO_DEFINIDO), 45, DIAS_MINIMO, DIAS_MAXIMO),
        reativacao_ativa=_booleano(cfg("reativacao_ativa", _NAO_DEFINIDO), False),
        limite_por_dia=_inteiro(cfg("limite_por_dia", _NAO_DEFINIDO), 50, 1, 500),
        mensagem_lembrete=_texto(
            cfg("mensagem_lembrete", _NAO_DEFINIDO),
            _texto(cfg("mensagem_modelo", _NAO_DEFINIDO)),
        ),
        mensagem_reativacao=_texto(
            cfg("mensagem_reativacao", _NAO_DEFINIDO),
            _texto(cfg("mensagem_modelo", _NAO_DEFINIDO)),
        ),
        envios_pausados=_booleano(cfg("envios_pausados", _NAO_DEFINIDO), False),
    )