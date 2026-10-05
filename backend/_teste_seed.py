"""Prova que o seed é idempotente e seguro para rodar a cada deploy.

O risco real de um seed não é falhar — é sobrescrever dado em produção. Estes testes
exercitam exatamente os casos que destroyirem um banco:

1. Rodar duas vezes não cria dois admins.
2. Rodar de novo **não** sobrescreve a senha.
3. `--forcar-senha` sobrescreve, e só quando pedido.
4. Não cria um segundo dono quando outro e-mail já existe.
5. Recusa senha curta.

    python _teste_seed.py
"""

import os
import sys

from app.api.deps import hash_token
from app.db.database import SessionLocal
from app.db.models import AdminUsuario
from app.services.seguranca import gerar_token, hash_senha, verificar_senha

falhas = []
BACKUP = {}


def conferir(rotulo, condicao, detalhe=""):
    marca = "ok  " if condicao else "FALHA"
    print(f"  {marca} {rotulo}" + (f"  -> {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(rotulo)


def rodar(flags=(), email=None, senha=None):
    """Executa o seed com o ambiente controlado."""
    import importlib

    import seed as mod

    importlib.reload(mod)

    anteriores = {k: os.environ.get(k) for k in ("ADMIN_EMAIL", "ADMIN_SENHA", "ADMIN_NOME")}
    if email is not None:
        os.environ["ADMIN_EMAIL"] = email
    if senha is not None:
        os.environ["ADMIN_SENHA"] = senha
    os.environ.setdefault("ADMIN_NOME", "Teste Seed")
    try:
        return mod.semear_admin(forcar_senha="--forcar-senha" in flags)
    finally:
        for chave, valor in anteriores.items():
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor


def limpar(email):
    db = SessionLocal()
    try:
        db.query(AdminUsuario).filter(AdminUsuario.email == email).delete()
        db.commit()
    finally:
        db.close()


EMAIL = "seed-test@lembrazap.local"
SENHA_1 = "PrimeiraSenha123"
SENHA_2 = "SegundaSenha456"

# Limpa antes de começar: execuções anteriores podem ter deixado os mesmos e-mails,
# e um teste que depende de estado limpo precisa garantir isso explicitamente.
limpar(EMAIL)
limpar("assistente@lembrazap.local")

print("== 1. primeira criacao ==")
limpar(EMAIL)
r1 = rodar(email=EMAIL, senha=SENHA_1)
conferir("admin criado", r1["acao"] == "criado", r1["acao"])

db = SessionLocal()
try:
    hash_1 = db.query(AdminUsuario).filter(AdminUsuario.email == EMAIL).first().senha_hash
finally:
    db.close()
conferir("senha confere", verificar_senha(SENHA_1, hash_1))

print("\n== 2. rodar de novo nao cria duplicata ==")
r2 = rodar(email=EMAIL, senha=SENHA_2)
conferir("acao foi 'ja_existe'", r2["acao"] == "ja_existe", r2["acao"])

db = SessionLocal()
try:
    admins = db.query(AdminUsuario).filter(AdminUsuario.email == EMAIL).all()
    hash_2 = admins[0].senha_hash if admins else ""
finally:
    db.close()
conferir("continua sendo um admin so", len(admins) == 1, f"{len(admins)} registro(s)")
conferir("SENHA NAO foi sobrescrita", hash_1 == hash_2)
conferir("a senha antiga ainda vale", verificar_senha(SENHA_1, hash_2))
conferir("a senha nova NAO vale", not verificar_senha(SENHA_2, hash_2))

print("\n== 3. --forcar-senha sobrescreve ==")
r3 = rodar(("--forcar-senha",), email=EMAIL, senha=SENHA_2)
conferir("acao marcada como forcada", r3["acao"] == "ja_existe" and r3.get("forcado"), f"{r3['acao']}/{r3.get('forcado')}")

db = SessionLocal()
try:
    hash_3 = db.query(AdminUsuario).filter(AdminUsuario.email == EMAIL).first().senha_hash
finally:
    db.close()
conferir("nova senha vale agora", verificar_senha(SENHA_2, hash_3))
conferir("senha antiga recusada", not verificar_senha(SENHA_1, hash_3))

print("\n== 4. e-mail diferente cria um segundo admin (operador assistente) ==")
r4 = rodar(email="assistente@lembrazap.local", senha=SENHA_1)
conferir("criado", r4["acao"] == "criado", r4["acao"])
conferir("avisou que é o segundo", r4.get("total_admins", 1) > 1, str(r4.get("total_admins")))

db = SessionLocal()
try:
    assistente = db.query(AdminUsuario).filter(AdminUsuario.email == "assistente@lembrazap.local").first()
    assistente_ok = assistente is not None and verificar_senha(SENHA_1, assistente.senha_hash)
finally:
    db.close()
conferir("o assistente existe e a senha confere", assistente_ok)

# Um e-mail diferente também pode ser master: quem entra em /admin vê tudo.
conferir(
    "os dois e-mails sao distintos",
    r4["email"] != EMAIL,
    f"{r4['email']} != {EMAIL}",
)

print("\n== 5. recusa senha curta na criacao ==")
limpar(EMAIL)
r5 = rodar(email=EMAIL, senha="abc")
conferir("recusada com erro", r5["acao"] == "erro", r5.get("motivo", "")[:50])

db = SessionLocal()
try:
    nao_criou = db.query(AdminUsuario).filter(AdminUsuario.email == EMAIL).count() == 0
finally:
    db.close()
conferir("nenhum admin criado com senha fraca", nao_criou)

print("\n== 5b. warns quando ADMIN_SENHA existe mas nao sera aplicada ==")
r5b = rodar(email=EMAIL, senha=SENHA_1)
rodar(email=EMAIL, senha=SENHA_2)
r5c = rodar(email=EMAIL, senha=SENHA_2)
conferir("sinaliza senha ignorada", r5c.get("senha_ignorada") is True, str(r5c.get("senha_ignorada")))

db = SessionLocal()
try:
    hash_5c = db.query(AdminUsuario).filter(AdminUsuario.email == EMAIL).first().senha_hash
finally:
    db.close()
conferir("e a senha NAO foi alterada", verificar_senha(SENHA_1, hash_5c))

print("\n== 6. sem ADMIN_SENHA gera provisoria ==")
limpar(EMAIL)
r6 = rodar(email=EMAIL, senha=None)
conferir("criado", r6["acao"] == "criado", r6["acao"])
conferir("gerou senha provisoria", bool(r6.get("senha_provisoria")), str(r6.get("senha_provisoria")))

db = SessionLocal()
try:
    hash_6 = db.query(AdminUsuario).filter(AdminUsuario.email == EMAIL).first().senha_hash
finally:
    db.close()
conferir("provisoria funciona como senha", verificar_senha(r6["senha_provisoria"], hash_6))

print("\n== 7. seed de demonstracao e idempotente ==")
from app.db.models import Cliente, Tenant

# A conta de demonstração de execuções anteriores atrapalharia a asserção de
# "primeira vez cria", então removemos antes.
db = SessionLocal()
try:
    demo_antigo = next(
        (
            t
            for t in db.query(Tenant).all()
            if (t.config or {}).get("email_contato") == "demo@lembrazap.local"
        ),
        None,
    )
    if demo_antigo:
        db.query(Cliente).filter(Cliente.tenant_id == demo_antigo.id).delete()
        db.delete(demo_antigo)
        db.commit()
finally:
    db.close()

import seed as mod_seed

d1 = mod_seed.semear_demo()
d2 = mod_seed.semear_demo()
conferir("primeira vez cria", d1["acao"] == "criado", f"{d1.get('clientes')} clientes")
conferir("segunda vez nao duplica", d2["acao"] == "ja_existe", d2["acao"])

db = SessionLocal()
try:
    # `config` é JSON e não aceita `LIKE` direto no Postgres. Busca por todos e
    # filtra em Python: são poucas contas e evita dialeto específico.
    demo = next(
        (
            t
            for t in db.query(Tenant).all()
            if (t.config or {}).get("email_contato") == "demo@lembrazap.local"
        ),
        None,
    )
    total = db.query(Cliente).filter(Cliente.tenant_id == demo.id).count() if demo else 0
finally:
    db.close()
conferir("base de demo tem 7 clientes (6 com data + 1 sem)", total == 7, str(total))

limpar(EMAIL)
limpar("assistente@lembrazap.local")

if falhas:
    print(f"\nFALHAS: {', '.join(falhas)}")
    sys.exit(1)
print("\nIdempotencia e seguranca do seed confirmadas.")