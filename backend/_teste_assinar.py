"""Testa o fluxo de assinar sem depender da Stripe nem do TestClient.

A chave em producao esta expirada, entao um teste HTTP de verdade so provaria que
ela falha. E `TestClient` exigiria `httpx`, que nao esta no requirements.

Por isso o teste chama o handler da rota direto e le `HTTPException` para o status.
O que ele prova e a logica que importa:

- validacao do e-mail e do plano;
- criacao da conta `pendente`, e que ela nao libera acesso;
- `customer_email` e o `tenant_id` chegando a sessao da Stripe;
- reuso da conta quando o e-mail se repete, sem reemitir token;
- o webhook ativando, e o reenvio do mesmo evento nao virando cobranca dupla;
- falha da Stripe virando 502, com a conta preservada para nova tentativa.

O que ele nao prova: que a Stripe aceita a chamada. Isso so a chave valida prova.
"""

import os
import sys
import types
import uuid
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import HTTPException

from app.api import assinatura as api
from app.db.models import Tenant
from app.services import assinatura, stripe as svc_stripe

FALHAS = []


def checar(condicao, descricao):
    marca = "ok   " if condicao else "FALHA"
    print(f"  {marca} {descricao}")
    if not condicao:
        FALHAS.append(descricao)


def chamar(db, **corpo):
    """Chama a rota e devolve `(status, corpo)`, traduzindo a excecao."""
    try:
        req = api.AssinarReq(**corpo)
    except Exception as exc:  # validacao do Pydantic
        return 422, str(exc)

    try:
        return 200, api.assinar(req, db=db)
    except HTTPException as exc:
        return exc.status_code, exc.detail


class _SessaoFalsa:
    url = "https://checkout.stripe.com/c/pay/cs_test_123"
    id = "cs_test_123"


class _PrecoFalso:
    id = "price_test_123"
    product = "prod_test_123"


def main():
    from app.db.database import SessionLocal

    db = SessionLocal()

    # E-mail unico por execucao, para o teste nao depender do que sobrou antes.
    seq = uuid.uuid4().hex[:8]

    # `disponivel()` le o ambiente na importacao do modulo. Sem isto a rota
    # responde 503 e nenhum dos testes abaixo exercitaria nada.
    svc_stripe._SECRET_KEY = "sk_test_falso_para_teste"

    capturados = []

    def criar_sessao(**kwargs):
        capturados.append(kwargs)
        return _SessaoFalsa

    def criar_produto(**_kwargs):
        return types.SimpleNamespace(id="prod_test_123")

    def criar_price(**_kwargs):
        return _PrecoFalso()

    # `_buscar_price_existente` usa `auto_paging_iter`, então o duble precisa
    # oferecer esse método — um `dict` comum não tem. Vazio de propósito: força o
    # caminho de criação, que é o que este teste precisa exercitar. A busca por
    # metadata tem teste próprio em `_teste_worker_bloqueio.py`.
    class _PaginaVazia:
        @staticmethod
        def auto_paging_iter():
            return iter(())

    def listar_produtos(**_kwargs):
        return _PaginaVazia()

    duble = types.SimpleNamespace(
        checkout=types.SimpleNamespace(Session=types.SimpleNamespace(create=criar_sessao)),
        Product=types.SimpleNamespace(create=criar_produto, list=listar_produtos),
        Price=types.SimpleNamespace(create=criar_price),
    )

    def com_stripe(fn):
        with mock.patch.object(svc_stripe, "_client", return_value=duble):
            return fn()

    print("\n== validacao ==")
    st, detalhe = chamar(db, email="a@b.com", plano="inexistente")
    checar(st == 400, f"plano desconhecido -> 400 (veio {st})")
    checar("plano" in str(detalhe).lower(), "a mensagem diz qual campo falhou")

    for mal in ("nao-e-email", "sem arroba@", "@seminicio.com", "a b@c.com"):
        st, _ = chamar(db, email=mal, plano="pro")
        checar(st == 400, f"e-mail invalido {mal!r} -> 400 (veio {st})")

    st, _ = chamar(db, email="a@b.com")
    checar(st == 422, f"plano ausente -> 422 (veio {st})")

    print("\n== criacao da conta pendente ==")
    email = f"nova-{seq}@exemplo.com.br"
    with mock.patch.object(svc_stripe, "_client", return_value=duble):
        st, corpo = chamar(db, email=email, plano="pro")

    checar(st == 200, f"assinar -> 200 (veio {st})")
    corpo = corpo if isinstance(corpo, dict) else {}
    checar(str(corpo.get("url", "")).startswith("https://checkout.stripe.com/"), "devolve a URL do Stripe")
    checar(bool(corpo.get("token")), "devolve o token de acesso")
    checar(corpo.get("plano") == "Pro", "devolve o nome do plano")

    t = db.query(Tenant).filter(Tenant.email_contato == email).first()
    checar(t is not None, "a conta foi criada")
    checar(t is not None and t.status == "pendente", f"status pendente (veio {t.status if t else 'nada'})")
    checar(t is not None and t.plano == "pro", "plano gravado na conta")
    checar(t is not None and not t.assinatura_ativa, "pendente nao libera acesso")

    liberado, motivo = assinatura.pode_operar(t)
    checar(not liberado, "pode_operar barra a conta pendente")
    checar(bool(motivo), "e diz por que esta bloqueada")
    checar(
        assinatura.ROTULO_STATUS.get("pendente") == "Aguardando pagamento",
        "o admin tem rotulo para 'pendente'",
    )
    checar("pendente" not in assinatura.STATUS_LIBERA_ACESSO, "'pendente' nao esta em STATUS_LIBERA_ACESSO")

    print("\n== o que foi para a Stripe ==")
    checar(len(capturados) == 1, f"a Stripe foi chamada uma vez (veio {len(capturados)})")
    if capturados:
        sess = capturados[0]
        checar(sess.get("customer_email") == email, "customer_email preenchido")
        checar(sess.get("mode") == "subscription", "assinatura recorrente, nao pagamento unico")
        checar(sess.get("locale") == "pt-BR", "checkout em portugues")
        checar(
            (sess.get("metadata") or {}).get("tenant_id") == (t.id if t else None),
            "metadata leva o tenant_id para o webhook reencontrar",
        )
        checar(
            (sess.get("subscription_data") or {}).get("metadata", {}).get("tenant_id") == (t.id if t else None),
            "subscription_data tambem leva o tenant_id (invoice.paid precisa dele)",
        )
        checar(f"token={corpo.get('token')}" in str(sess.get("success_url")), "success_url devolve o token")
        checar("cancelado" in str(sess.get("cancel_url")), "cancel_url volta para o cancelamento")
        checar("price" in str(sess.get("line_items")), "leva o price_id do plano")

    print("\n== nao duplica conta quando o e-mail se repete ==")
    com_stripe(lambda: chamar(db, email=email, plano="starter"))
    st, corpo2 = com_stripe(lambda: chamar(db, email=email.upper(), plano="business"))

    repetidos = db.query(Tenant).filter(Tenant.email_contato == email).all()
    checar(len(repetidos) == 1, f"continua com uma conta (veio {len(repetidos)})")
    checar(repetidos[0].plano == "business", "o plano novo substitui o anterior")
    checar(st == 200 and not (corpo2 or {}).get("token"), "nao reemite token ja entregue")

    print("\n== e-mail normalizado ==")
    alvo = f"misto-{seq}@exemplo.com.br"
    com_stripe(lambda: chamar(db, email=f"  MiStO-{seq}@Exemplo.COM.BR  ", plano="pro"))
    checar(db.query(Tenant).filter(Tenant.email_contato == alvo).count() == 1, "espaco e caixa normalizados")

    print("\n== conta ativa nao reassina ==")
    t.status = "ativo"
    t.assinatura_ativa = True
    db.commit()
    antes = db.query(Tenant).filter(Tenant.email_contato == email).count()
    st, _ = com_stripe(lambda: chamar(db, email=email, plano="pro"))
    checar(st == 409, f"conta ativa -> 409 (veio {st})")
    checar(db.query(Tenant).filter(Tenant.email_contato == email).count() == antes, "e nao criou outra")

    print("\n== o webhook ativa ==")
    t.status = "pendente"
    t.assinatura_ativa = False
    db.commit()

    evento = {
        "id": f"evt_{seq}",
        "tipo": "checkout.session.completed",
        "objeto": {
            "subscription": f"sub_{seq}",
            "amount_total": 9900,
            "metadata": {"tenant_id": t.id, "plano": "pro"},
        },
    }
    assinatura.processar_evento(db, evento)
    db.refresh(t)

    checar(t.status == "ativo", f"webhook deixou ativa (veio {t.status})")
    checar(bool(t.assinatura_ativa), "assinatura_ativa ligada")
    checar(t.stripe_subscription_id == f"sub_{seq}", "gravou o subscription_id")
    checar(any(p.stripe_event_id == f"evt_{seq}" for p in t.pagamentos), "registrou o pagamento")
    liberado, _ = assinatura.pode_operar(t)
    checar(liberado, "agora pode operar")

    print("\n== reenvio do mesmo webhook ==")
    assinatura.processar_evento(db, evento)
    db.refresh(t)
    checar(
        len([p for p in t.pagamentos if p.stripe_event_id == f"evt_{seq}"]) == 1,
        "nao conta o mesmo pagamento duas vezes",
    )

    print("\n== falha da Stripe nao derruba a API ==")
    def explodir(**_kwargs):
        raise RuntimeError("Expired API Key provided")

    duble_ruim = types.SimpleNamespace(
        checkout=types.SimpleNamespace(Session=types.SimpleNamespace(create=explodir)),
        Product=types.SimpleNamespace(create=criar_produto, list=listar_produtos),
        Price=types.SimpleNamespace(create=criar_price),
    )
    email_erro = f"erro-{seq}@x.com.br"
    with mock.patch.object(svc_stripe, "_client", return_value=duble_ruim):
        st, detalhe = chamar(db, email=email_erro, plano="pro")

    checar(st == 502, f"erro da Stripe -> 502 (veio {st})")
    checar("Expired" in str(detalhe), "a mensagem traz o erro real da Stripe")
    checar(
        db.query(Tenant).filter(Tenant.email_contato == email_erro).count() == 1,
        "a conta fica salva para a proxima tentativa",
    )

    print("\n== sem Stripe configurado ==")
    chave = svc_stripe._SECRET_KEY
    svc_stripe._SECRET_KEY = ""
    st, _ = chamar(db, email=f"sem-chave-{seq}@x.com.br", plano="pro")
    checar(st == 503, f"sem STRIPE_SECRET_KEY -> 503 (veio {st})")
    svc_stripe._SECRET_KEY = chave

    # limpeza
    for alvo in (email, f"misto-{seq}@exemplo.com.br", email_erro):
        for row in db.query(Tenant).filter(Tenant.email_contato == alvo).all():
            db.delete(row)
    db.commit()
    db.close()

    print()
    if FALHAS:
        print(f"{len(FALHAS)} verificacao(oes) falharam:")
        for f in FALHAS:
            print(f"  - {f}")
        return 1

    print("fluxo de assinar confere inteiro")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())