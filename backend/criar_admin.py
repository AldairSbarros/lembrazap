"""Cria (ou redefine) a conta de administrador do sistema.

Uso dentro do container, onde as variáveis `DATABASE_URL` já existem:

    docker compose exec backend python criar_admin.py

Para fixar os dados em vez de usar prompt interativo:

    docker compose exec -e ADMIN_EMAIL=voce@seudominio.com \
                        -e ADMIN_SENHA='uma-senha-forte' \
                        backend python criar_admin.py

`ADMIN_SENHA` só é usada quando informada. Sem ela o script gera uma senha
provisória e mostra **uma única vez** — anote antes de fechar o terminal.

O e-mail é a identidade de login. Rodar de novo com o mesmo e-mail **atualiza** a
senha em vez de criar duplicata, que é o comportamento esperado para recuperar
acesso em vez de acumular contas de dono.
"""

import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.api.deps import hash_token  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.db.models import AdminUsuario  # noqa: E402
from app.services.seguranca import gerar_token, hash_senha  # noqa: E402

MINIMO_SENHA = 8


def _pedir_senha(email: str) -> str:
    senha = os.getenv("ADMIN_SENHA", "").strip()
    if not senha:
        senha = getpass.getpass(f"Senha para {email} (mínimo {MINIMO_SENHA} caracteres): ")
        confirma = getpass.getpass("Repita a senha: ")
        if senha != confirma:
            sys.exit("As senhas não coincidem.")

    if len(senha) < MINIMO_SENHA:
        sys.exit(f"A senha precisa de ao menos {MINIMO_SENHA} caracteres.")
    return senha


def main() -> None:
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    if not email:
        email = input("E-mail do administrador: ").strip().lower()

    if "@" not in email or len(email) < 5:
        sys.exit("E-mail inválido.")

    nome = os.getenv("ADMIN_NOME", "").strip() or "Administrador"
    senha = _pedir_senha(email)

    db = SessionLocal()
    try:
        admin = db.query(AdminUsuario).filter(AdminUsuario.email == email).first()
        token = gerar_token()

        if admin:
            # Redefinir a senha é o caminho de recuperação, então vale registrar
            # que a conta existia em vez de fingir que é um cadastro novo.
            admin.senha_hash = hash_senha(senha)
            admin.token_hash = hash_token(token)
            admin.ativo = True
            print(f"Senha atualizada para {email}.")
        else:
            admin = AdminUsuario(
                nome=nome,
                email=email,
                senha_hash=hash_senha(senha),
                token_hash=hash_token(token),
                ativo=True,
            )
            db.add(admin)
            print(f"Administrador criado: {email}")

        db.commit()
    finally:
        db.close()

    print(f"\nToken inicial (use como X-LZ-Admin):\n{token}")
    print("Ele também fica salvo no navegador após o primeiro login.")


if __name__ == "__main__":
    main()