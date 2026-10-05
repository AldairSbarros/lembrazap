"""Integração com o Stripe (assinatura recorrente por cartão).

O módulo é **opcional**: se `STRIPE_SECRET_KEY` não estiver definida, `disponivel()`
retorna False e o painel admin cai automaticamente para cobrança manual (marcar como
pago, suspender, estender). Assim o sistema funciona numa instalação nova antes de
existir conta no Stripe, e o dono do negócio nunca fica sem administer as contas.

Só importamos o pacote `stripe` quando há chave configurada, para não quebrar o
container de desenvolvimento que ainda não tem o pacote instalado.
"""

import logging
import os

log = logging.getLogger(__name__)

_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()

_sdk = None


def disponivel() -> bool:
    return bool(_SECRET_KEY)


def _client():
    """Instância preguiçosa do SDK, só criada na primeira chamada de verdade."""
    global _sdk
    if _sdk is None:
        import stripe  # import tardio de propósito

        stripe.api_key = _SECRET_KEY
        stripe.max_network_retries = 2
        _sdk = stripe
    return _sdk


def criar_checkout(tenant, plano_chave: str, base_url: str) -> dict:
    """Abre a sessão de checkout do Stripe para um tenant pagar a assinatura.

    `client_reference_id` carrega o id do tenant para o webhook reencontrar a conta
    mesmo que o cliente abandone o checkout e volte depois.
    """
    from app.config.planos import obter_plano, stripe_price_id

    price_id = stripe_price_id(plano_chave)
    plano = obter_plano(plano_chave)
    if not price_id:
        raise ValueError(
            f"Plano '{plano_chave}' sem STRIPE_PRICE_ID_{plano_chave.upper()} configurado."
        )

    stripe = _client()
    sessao = stripe.checkout.Session.create(
        mode="subscription",
        client_reference_id=tenant.id,
        customer=tenant.stripe_customer_id or None,
        line_items=[{"price": price_id, "quantity": 1}],
        # `pending` deixa a conta em trial: o acesso só liga quando o Stripe
        # confirma o pagamento, evitando granting por sessão abandonada.
        payment_status="paid",
        subscription_data={"metadata": {"tenant_id": tenant.id, "plano": plano_chave}},
        metadata={"tenant_id": tenant.id, "plano": plano_chave},
        success_url=f"{base_url}/assinatura?status=ok",
        cancel_url=f"{base_url}/assinatura?status=cancelado",
        locale="pt-BR",
    )
    log.info("[stripe] checkout criado para tenant %s plano %s", tenant.id, plano_chave)
    return {"url": sessao.url, "id": sessao.id, "plano": plano["nome"]}


def criar_portal(tenant, base_url: str) -> dict:
    """Portal do Stripe para o assinante trocar cartão ou cancelar sozinho."""
    if not tenant.stripe_customer_id:
        raise ValueError("Esta conta ainda não tem assinatura no Stripe.")

    stripe = _client()
    sessao = stripe.billing_portal.Session.create(
        customer=tenant.stripe_customer_id,
        return_url=f"{base_url}/assinatura",
    )
    return {"url": sessao.url}


def cancelar_assinatura(tenant, imediata: bool = True) -> dict:
    """Cancela a assinatura no Stripe. `imediata=True` encerra o acesso na hora."""
    if not tenant.stripe_subscription_id:
        return {"ok": False, "motivo": "Conta sem assinatura registrada."}

    stripe = _client()
    sub = stripe.Subscription.modify(
        tenant.stripe_subscription_id,
        cancel_at_period_end=not imediata,
    )
    return {"ok": True, "status": sub.status}


def confirmar_webhook(payload: bytes, assinatura_header: str) -> dict:
    """Valida a assinatura do webhook. Levanta `ValueError` se não bater."""
    if not WEBHOOK_SECRET:
        raise ValueError("STRIPE_WEBHOOK_SECRET não configurado.")

    stripe = _client()
    evento = stripe.Webhook.construct_event(payload, assinatura_header, WEBHOOK_SECRET)
    return {
        "id": evento["id"],
        "tipo": evento["type"],
        "objeto": dict(evento["data"]["object"]),
    }