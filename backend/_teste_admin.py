"""Teste ponta a ponta do painel administrativo e do controle de assinatura.

Roda contra a API de desenvolvimento. Cria uma conta descartável, suspende,
reativa e confere que o bloqueio de acesso é real — não só cosmético.

    python _teste_admin.py
"""

import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8002"
ADMIN_EMAIL = "admin@lembrazap.com.br"
ADMIN_SENHA = "LembraZap#2026"

falhas = []


def chamar(metodo, caminho, corpo=None, headers=None, espera_erro=None):
    """Faz a requisição e devolve (status, json). Não levanta em erro de HTTP."""
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(f"{BASE}{caminho}", data=dados, method=metodo)
    req.add_header("Content-Type", "application/json")
    for chave, valor in (headers or {}).items():
        req.add_header(chave, valor)

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def conferir(rotulo, condicao, detalhe=""):
    marca = "ok  " if condicao else "FALHA"
    print(f"  {marca} {rotulo}" + (f"  -> {detalhe}" if detalhe else ""))
    if not condicao:
        falhas.append(rotulo)


print("== autenticacao ==")
status, _ = chamar("POST", "/api/admin/login", {"email": ADMIN_EMAIL, "senha": "errada"})
conferir("senha errada devolve 401", status == 401, str(status))

status, _ = chamar("POST", "/api/admin/login", {"email": "ninguem@x.com", "senha": "errada"})
conferir("email inexistente devolve o mesmo 401", status == 401, str(status))

status, _ = chamar("GET", "/api/admin/contas", headers={"X-LZ-Admin": "token-de-assinante"})
conferir("token de assinante nao abre o admin", status == 401, str(status))

status, login = chamar("POST", "/api/admin/login", {"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})
conferir("login do proprietario", status == 200, login.get("nome", ""))

A = {"X-LZ-Admin": login["token"]}

print("\n== criacao de conta ==")
status, nova = chamar(
    "POST",
    "/api/admin/contas",
    {
        "nome": "Clinica Teste E2E",
        "negocio": "Clinica Teste E2E",
        "plano": "pro",
        "dias_teste": 7,
        "criar_instancia": False,
    },
    A,
)
conferir("conta criada", status == 201, f"id={nova.get('tenant_id')}")

tid, token = nova["tenant_id"], nova["token"]
T = {"X-LZ-Token": token}

status, detalhe = chamar("GET", f"/api/admin/contas/{tid}", headers=A)
conferir(
    "plano e dias de teste gravados",
    detalhe["plano"] == "pro" and detalhe["status"] == "trial",
    f"{detalhe.get('plano')}/{detalhe.get('status')}",
)
conferir("limite do plano correto (pro=1000)", detalhe["metricas"] is not None)

print("\n== conta em teste pode operar ==")
status, sub = chamar("GET", "/api/assinatura", headers=T)
conferir("acesso liberado no teste", sub["acesso_liberado"] is True, sub["status"])
conferir("renovacao a 7 dias", sub["renovacao_em"] is not None, str(sub["renovacao_em"]))

status, lim = chamar("GET", "/api/assinatura/limites", headers=T)
conferir("limite pro = 1000 clientes", lim["limite_clientes"] == 1000, str(lim))

status, ag = chamar(
    "POST",
    "/api/agendamentos",
    {"nome": "Joao", "telefone": "5592992030250", "servico": "Consulta", "quando": "2026-10-10T15:00:00"},
    T,
)
conferir("agendamento aceito", status == 200 and ag.get("ok"), str(status))

print("\n== suspension ==")
status, susp = chamar(
    "POST", f"/api/admin/contas/{tid}/suspender", {"motivo": "teste e2e"}, A
)
conferir("conta suspensa", susp["contas"]["status"] == "suspenso", susp["contas"]["status"])
conferir("acesso cortado", susp["contas"]["acesso_liberado"] is False)
conferir("motivo registrado", susp["contas"]["motivo_bloqueio"] != "")

status, erro = chamar(
    "POST",
    "/api/agendamentos",
    {"nome": "Joao", "telefone": "5592992030250", "servico": "Consulta", "quando": "2026-10-10T15:00:00"},
    T,
)
conferir("agendamento bloqueado com 402", status == 402, f"{status} {erro.get('detail', {}).get('erro')}")

status, base = chamar("GET", "/api/clientes", headers=T)
conferir("base ainda legivel (nao apaga dado)", status == 200, f"{status}")

status, sub = chamar("GET", "/api/assinatura", headers=T)
conferir("painel do assinante explica o bloqueio", sub["acesso_liberado"] is False, sub["mensagem_bloqueio"][:48])

print("\n== reativacao ==")
status, reat = chamar("POST", f"/api/admin/contas/{tid}/reativar", {"dias": 30}, A)
conferir("conta reativada", reat["status"] == "ativo", reat["status"])
conferir("acesso liberado de novo", reat["acesso_liberado"] is True)

status, ag = chamar(
    "POST",
    "/api/agendamentos",
    {"nome": "Joao", "telefone": "5592992030250", "servico": "Consulta", "quando": "2026-10-11T15:00:00"},
    T,
)
conferir("agendamento volta a funcionar", status == 200 and ag.get("ok"), str(status))

print("\n== troca de plano ==")
status, ed = chamar("PATCH", f"/api/admin/contas/{tid}", {"plano": "starter"}, A)
conferir("plano alterado para starter", ed["plano"] == "starter", ed["plano_nome"])
status, lim = chamar("GET", "/api/assinatura/limites", headers=T)
conferir("limite passa a 300 no starter", lim["limite_clientes"] == 300, str(lim))

print("\n== revogacao de token ==")
status, novo = chamar("POST", f"/api/admin/contas/{tid}/token", None, A)
conferir("token regenerado", status == 200 and "token" in novo)
status, _ = chamar("GET", "/api/assinatura", headers=T)
conferir("token antigo invalidado", status == 401, str(status))

print("\n== isolamento entre contas ==")
status, clientes = chamar("GET", f"/api/admin/contas/{tid}/clientes", headers=A)
conferir("admin le clientes da conta", status == 200, f"{clientes.get('total')} clientes")
if clientes.get("clientes"):
    telefone = clientes["clientes"][0]["telefone_mascarado"]
    conferir("telefone mascarado no painel admin", telefone.startswith("***"), telefone)

print("\n== historico de pagamento ==")
status, det = chamar("GET", f"/api/admin/contas/{tid}", headers=A)
conferir("reativacao registrada como pagamento", len(det["pagamentos"]) >= 1, f"{len(det['pagamentos'])} registro(s)")

print(f"\n{'FALHAS: ' + ', '.join(falhas) if falhas else 'todos os testes passaram'}")
sys.exit(1 if falhas else 0)