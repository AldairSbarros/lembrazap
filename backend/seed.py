"""Seed idempotente do banco: o master user e os dados de demonstração.

Diferente de `criar_admin.py`, que é interativo e serve para o primeiro acesso, este
script é pensado para rodar **a cada deploy**, sem intervenção. Por isso a regra que
mais importa:

> Reexecutar o seed **nunca** sobrescreve a senha de um admin que já existe.

Um seed que reseta senha a cada deploy traria o dono de volta ao padrão de fábrica
em produção, e qualquer um que conhecesse o padrão entraria no painel. Por isso
`ADMIN_SENHA` só é aplicada quando o admin é criado pela primeira vez, ou quando
`--forcar-senha` é passado explicitamente.

    python seed.py --status      # o que existe hoje (não altera nada)
    python seed.py               # garante o master user
    python seed.py --demo        # cria também uma conta de demonstração
    python seed.py --forcar-senha  # reaplica ADMIN_SENHA mesmo se o admin existe

A senha é lida de `ADMIN_SENHA` no ambiente, e não de argumento na linha de comando:
passar senha como argumento grava ela no histórico do shell e no `ps` da máquina.

Se a senha faltar na primeira criação, uma senha aleatória é gerada e mostrada
**uma única vez**. Guarde-a; ela não é recuperável depois.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.api.deps import hash_token  # noqa: E402
from app.config.planos import listar_planos  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.db.models import AdminUsuario, Cliente, PlanoStripe, Tenant  # noqa: E402
from app.services.seguranca import (  # noqa: E402
    gerar_senha_provisoria,
    gerar_token,
    hash_senha,
)

MINIMO_SENHA = 8


# ------------------------------------------------------------------ master


def semear_admin(forcar_senha: bool = False) -> dict:
    """Garante o master user do painel administrativo. Idempotente."""
    db = SessionLocal()
    try:
        email = os.getenv("ADMIN_EMAIL", "").strip().lower()
        nome = os.getenv("ADMIN_NOME", "").strip() or "Proprietário"
        senha = os.getenv("ADMIN_SENHA", "").strip()

        existentes = db.query(AdminUsuario).order_by(AdminUsuario.criado_em).all()

        if not email:
            return {
                "acao": "pulado",
                "motivo": "ADMIN_EMAIL não definido no ambiente.",
                "total_admins": len(existentes),
            }

        if "@" not in email or len(email) < 5:
            return {"acao": "erro", "motivo": f"ADMIN_EMAIL inválido: {email!r}"}

        admin = next((a for a in existentes if a.email == email), None)

        if admin is not None:
            if forcar_senha and senha:
                if len(senha) < MINIMO_SENHA:
                    return {"acao": "erro", "motivo": "ADMIN_SENHA abaixo do mínimo."}
                admin.senha_hash = hash_senha(senha)
                db.commit()
                return {"acao": "ja_existe", "email": admin.email, "forcado": True}

            # `ADMIN_SENHA` setada no ambiente mas sem `--forcar-senha` é a combinação
            # que mais confunde em deploy: o operador muda a senha no .env, roda o
            # seed achando que aplicou, e o deploy seguinte volta a senha antiga.
            return {
                "acao": "ja_existe",
                "email": admin.email,
                "forcado": False,
                "total_admins": len(existentes),
                "senha_ignorada": bool(senha),
            }

        # Primeira criação. Sem senha no ambiente, gera uma e mostra uma vez.
        gerada = None
        if not senha:
            senha = gerar_senha_provisoria()
            gerada = senha
        elif len(senha) < MINIMO_SENHA:
            return {
                "acao": "erro",
                "motivo": f"ADMIN_SENHA precisa de ao menos {MINIMO_SENHA} caracteres.",
            }

        admin = AdminUsuario(
            nome=nome,
            email=email,
            senha_hash=hash_senha(senha),
            token_hash=hash_token(gerar_token()),
            ativo=True,
        )
        db.add(admin)
        db.commit()

        return {
            "acao": "criado",
            "email": email,
            "senha_provisoria": gerada,
            "total_admins": len(existentes) + 1,
        }
    finally:
        db.close()


# ------------------------------------------------------------ demonstração


def semear_demo() -> dict:
    """Cria uma conta de demonstração com clientes, para testar o painel.

    Marcada com `email_contato = 'demo@lembrazap.local'`, o que a torna fácil de
    achar e de remover. Rodar de novo **atualiza** a base em vez de duplicar.
    """
    db = SessionLocal()
    try:
        tenant = (
            db.query(Tenant)
            .filter(Tenant.token_hash == hash_token("demo-lembrazap-token"))
            .first()
        )
        if tenant is None:
            token = "demo-lembrazap-token"
            tenant = Tenant(
                nome="Barbearia Demonstração",
                negocio="Barbearia Demonstração",
                token_hash=hash_token(token),
                status="trial",
                plano="starter",
                assinatura_ativa=True,
                config={"email_contato": "demo@lembrazap.local"},
            )
            db.add(tenant)
            db.commit()

        if db.query(Cliente).filter(Cliente.tenant_id == tenant.id).count() > 0:
            return {"acao": "ja_existe", "tenant_id": tenant.id, "token": "demo-lembrazap-token"}

        exemplos = [
            ("Ana Souza", "5511988880001", -3),
            ("Bruno Lima", "5511988880002", -12),
            ("Carla Dias", "5511988880003", -75),
            ("Diego Alves", "5511988880004", -95),
            ("Elena Reis", "5511988880005", -140),
            ("Fabio Nunes", "5511988880006", -200),
        ]

        from datetime import datetime, timedelta

        agora = datetime.utcnow()
        criados = 0
        for nome, telefone, dias in exemplos:
            db.add(
                Cliente(
                    tenant_id=tenant.id,
                    nome=nome,
                    telefone=telefone,
                    ultima_visita=agora + timedelta(days=dias),
                    obs="Contato de demonstração",
                )
            )
            criados += 1

        # Um cliente sem histórico, para exercitar o filtro da reativação.
        db.add(
            Cliente(
                tenant_id=tenant.id,
                nome="Cliente Sem Histórico",
                telefone="5511988880007",
                obs="Nunca registrou visita",
            )
        )
        criados += 1

        db.commit()
        return {"acao": "criado", "tenant_id": tenant.id, "clientes": criados, "token": "demo-lembrazap-token"}
    finally:
        db.close()


# ------------------------------------------------------------------ status


def status() -> dict:
    db = SessionLocal()
    try:
        admins = db.query(AdminUsuario).order_by(AdminUsuario.criado_em).all()
        tenants = db.query(Tenant).all()
        precos = {p.chave: p for p in db.query(PlanoStripe).all()}

        return {
            "admins": [
                {
                    "email": a.email,
                    "nome": a.nome,
                    "ativo": bool(a.ativo),
                    "criado_em": a.criado_em.isoformat() if a.criado_em else None,
                    "ultimo_acesso_em": (
                        a.ultimo_acesso_em.isoformat() if a.ultimo_acesso_em else None
                    ),
                }
                for a in admins
            ],
            "tenants": {
                "total": len(tenants),
                "com_acesso": sum(1 for t in tenants if t.status in ("ativo", "trial")),
                "demonstracao": sum(
                    1 for t in tenants if (t.config or {}).get("email_contato") == "demo@lembrazap.local"
                ),
            },
            "precos_stripe": {
                p["chave"]: {
                    "price_id": precos[p["chave"]].price_id or "(não criado)",
                    "preco_centavos": precos[p["chave"]].preco_centavos,
                }
                for p in listar_planos()
                if p["chave"] in precos
            },
            "planos_sem_preco": [
                p["chave"] for p in listar_planos() if p["chave"] not in precos
            ],
        }
    finally:
        db.close()


# ------------------------------------------------------------------ main


def main() -> None:
    if "--ajuda" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return

    if "--status" in sys.argv:
        import json

        print(json.dumps(status(), indent=2, ensure_ascii=False))
        return

    resultado = semear_admin(forcar_senha="--forcar-senha" in sys.argv)
    acao = resultado["acao"]

    if acao == "criado":
        print(f"Master user criado: {resultado['email']}")
        if resultado.get("senha_provisoria"):
            print(f"\nSenha provisória (mostrada uma única vez):\n  {resultado['senha_provisoria']}\n")
            print("Guarde-a. Não é recuperável — se perder, rode `seed.py --forcar-senha` com ADMIN_SENHA no ambiente.")
    elif acao == "ja_existe":
        print(f"Master user já existe: {resultado['email']} (senha preservada)")
        if resultado.get("senha_ignorada"):
            print(
                "\nATENÇÃO: ADMIN_SENHA está definida no ambiente mas NÃO foi aplicada.\n"
                "A senha existente foi mantida de propósito — reexecutar o seed nunca\n"
                "sobrescreve senha. Para aplicar a nova:\n"
                "    python seed.py --forcar-senha"
            )
        elif resultado.get("forcado"):
            print(f"Senha de {resultado['email']} atualizada (--forcar-senha).")
    elif acao == "erro":
        print(f"ERRO: {resultado['motivo']}")
        sys.exit(1)
    else:
        print(f"Seed de admin pulado: {resultado['motivo']}")

    if acao == "criado" and resultado.get("total_admins", 1) > 1:
        print(
            f"Atenção: este é o {resultado['total_admins']}º administrador. "
            "Cada ADMIN_EMAIL diferente no ambiente cria um acesso novo."
        )

    if "--demo" in sys.argv:
        demo = semear_demo()
        if demo["acao"] == "criado":
            print(
                f"Conta de demonstração criada com {demo['clientes']} clientes.\n"
                f"  token: {demo['token']}\n"
                f"  Remova depois com: DELETE FROM clientes WHERE tenant_id='{demo['tenant_id']}; "
                f"DELETE FROM tenants WHERE id='{demo['tenant_id']}';"
            )
        else:
            print("Conta de demonstração já existe (base atualizada).")

    if acao != "criado":
        import json

        print("\n" + json.dumps(status(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()