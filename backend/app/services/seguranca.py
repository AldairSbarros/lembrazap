"""Senhas de admin, derivadas sem dependência externa.

Usamos PBKDF2-HMAC-SHA256 da biblioteca padrão em vez de bcrypt/argon2 para não
acrescentar dependência nativa ao container. O custo padrão (600k iterações) é o
recomendado atualmente e leva ~0,3 s por verificação, o que é irrelevante para um
login administrativo e caro o suficiente para quem tentar forçar offline.

Os tokens de tenant continuam sendo SHA-256 puro, como já eram: são aleatórios e de
64 caracteres, então não precisam de stretching.
"""

import hashlib
import hmac
import secrets

_ITERACOES = 600_000
_ALGO = "pbkdf2_sha256"


def hash_senha(senha: str) -> str:
    """Gera o hash no formato `pbkdf2_sha256$iteracoes$salt$digest`."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", senha.encode(), salt.encode(), _ITERACOES)
    return f"{_ALGO}${_ITERACOES}${salt}${digest.hex()}"


def verificar_senha(senha: str, armazenado: str) -> bool:
    """Compara em tempo constante. Formato inválido retorna False, não levanta."""
    try:
        algo, iteracoes, salt, digest = armazenado.split("$")
        if algo != _ALGO:
            return False
        calculado = hashlib.pbkdf2_hmac(
            "sha256", senha.encode(), salt.encode(), int(iteracoes)
        ).hex()
    except (AttributeError, ValueError):
        return False
    return hmac.compare_digest(calculado, digest)


def gerar_token() -> str:
    """Token de sessão do painel admin (header `X-LZ-Admin`)."""
    return secrets.token_hex(24)


def gerar_senha_provisoria() -> str:
    """Senha aleatória para o primeiro acesso, exibida uma única vez ao admin."""
    alfabeto = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alfabeto) for _ in range(14))