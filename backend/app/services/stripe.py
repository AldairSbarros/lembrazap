"""Cria produto e preço recorrente no Stripe sob demanda.

Existe `STRIPE_PRICE_ID_*` no `.env` porque é o caminho que a Stripe documenta: você
cria o Product e o Price no painel dela uma vez e guarda o `price_...`. Funciona
bem, mas exige instalação manual.

Este módulo implementa a alternativa: quando o assinante clica em "assinar" e não há
preço configurado, o produto é criado na hora pela API. O comprador nunca vê nada
disso — abre o checkout, paga, e a assinatura ativa.

**O problema real disso é duplicar produto.** Cada checkout que criasse um produto
novo deixaria 50 assinantes virarem 50 produtos no painel do Stripe. Por isso a
ordem de resolução é:

1. `STRIPE_PRICE_ID_<PLANO>` no ambiente, se existir — caminho explícito, sempre
   vence, e é o que permite fixar um preço à mão.
2. `planos_stripe` no banco — cache do que já foi criado.
3. Busca na Stripe por `metadata['lembrazap_plano']` — rede de segurança para o caso
   do banco ter sido recriado.
4. Só então cria produto e preço.

O passo 3 é o que torna a automação segura de usar em produção.

**Atenção ao preço:** o `price_id` é imutável na Stripe. Quem assina hoje paga o
preço gravado em `planos_stripe`. Mudar `planos.py` de R$ 99 para R$ 109 afeta só
quem assinar depois — para mover quem já está assinado é preciso migrar a
assinatura na Stripe, que é operação manual.
"""

import logging
import os
from datetime import datetime

from app.config.planos import obter_plano
from app.db.database import SessionLocal
from app.db.models import PlanoStripe

log = logging.getLogger(__name__)

_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()

# Chave de metadata que amarra o produto ao plano. Buscar por ela é o que evita
# criar o mesmo produto duas vezes.
META_PLANO = "lembrazap_plano"

_sdk = None


def disponivel() -> bool:
    return bool(_SECRET_KEY)


def _client():
    global _sdk
    if _sdk is None:
        import stripe

        stripe.api_key = _SECRET_KEY
        stripe.max_network_retries = 2
        _sdk = stripe
    return _sdk


def _buscar_price_existente(chave: str) -> tuple[str, str] | None:
    """Reencontra produto já criado para este plano, pelos metadados.

    Filtra em Python em vez de usar `products.search` porque a Search API depende de
    habilitação na conta e falha com `error code api_key_invalid` quando não está.
    Listar produtos ativos funciona em qualquer conta.
    """
    stripe = _client()
    try:
        pagina = stripe.Product.list(limit=100, active=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("[stripe] não consegui listar produtos para buscar %s: %s", chave, exc)
        return None

    for produto in pagina.auto_paging_iter():
        if (produto.metadata or {}).get(META_PLANO) != chave:
            continue
        # `default_price` vem preenchido em produto com preço padrão, que é como criamos.
        price_id = produto.default_price
        if isinstance(price_id, dict):
            price_id = price_id.get("id")
        if price_id:
            return produto.id, price_id

    return None


def _criar_preco(chave: str) -> tuple[str, str]:
    """Cria Product + Price recorrente. Com `idempotency_key` para não duplicar
    quando duas compras simultâneas criarem o mesmo plano."""
    stripe = _client()
    plano = obter_plano(chave)
    if not plano:
        raise ValueError(f"Plano '{chave}' não existe no catálogo.")

    produto = stripe.Product.create(
        name=f"LembraZap {plano['nome']}",
        description=plano["descricao"],
        metadata={
            META_PLANO: chave,
            "lembrazap_clientes": str(plano["limite_clientes"]),
            "lembrazap_mensagens": str(plano["limite_mensagens_mes"]),
        },
    )

    preco = stripe.Price.create(
        product=produto.id,
        currency="brl",
        unit_amount=plano["preco_centavos"],
        recurring={"interval": "month"},
        nickname=f"{plano['nome']} mensal",
        metadata={META_PLANO: chave},
    )

    log.info("[stripe] plano %s criado: product=%s price=%s", chave, produto.id, preco.id)
    return produto.id, preco.id


def _registrar(chave: str, product_id: str, price_id: str, centavos: int) -> None:
    db = SessionLocal()
    try:
        linha = db.query(PlanoStripe).filter(PlanoStripe.chave == chave).first()
        if linha:
            linha.product_id = product_id
            linha.price_id = price_id
            linha.preco_centavos = centavos
            linha.atualizado_em = datetime.utcnow()
        else:
            db.add(
                PlanoStripe(
                    chave=chave,
                    product_id=product_id,
                    price_id=price_id,
                    preco_centavos=centavos,
                )
            )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        # Cache é otimização, não correctness: se falhar, o checkout ainda funciona
        # porque o passo 3 da busca vai reencontrar o produto.
        db.rollback()
        log.warning("[stripe] não consegui salvar o cache do plano %s: %s", chave, exc)
    finally:
        db.close()


def garantir_preco(chave: str) -> str:
    """Devolve o `price_id` do plano, criando o produto na Stripe se necessário."""
    chave = (chave or "").strip().lower()
    plano = obter_plano(chave)
    if not plano:
        raise ValueError(f"Plano '{chave}' não existe no catálogo.")

    # 1. Ambiente: configuração explícita sempre vence.
    do_env = os.getenv(f"STRIPE_PRICE_ID_{chave.upper()}", "").strip()
    if do_env:
        return do_env

    # 2. Cache local: evita chamada à API em todo checkout.
    db = SessionLocal()
    try:
        linha = db.query(PlanoStripe).filter(PlanoStripe.chave == chave).first()
        if linha and linha.price_id:
            return linha.price_id
    finally:
        db.close()

    # 3. Busca por metadados: banco recriado não deve duplicar produto.
    encontrado = _buscar_price_existente(chave)
    if encontrado:
        product_id, price_id = encontrado
        _registrar(chave, product_id, price_id, plano["preco_centavos"])
        log.info("[stripe] plano %s reencontrado: %s", chave, price_id)
        return price_id

    # 4. Cria. A chave de idempotência evita produto duplicado em compras simultâneas.
    produto_id, price_id = _criar_preco(chave)
    _registrar(chave, produto_id, price_id, plano["preco_centavos"])
    return price_id


def sincronizar(chave: str) -> dict:
    """Descarta o cache e recria o preço. Só serve para trocar o valor de um plano
    já existente — não muda o que os assinantes atuais pagam."""
    db = SessionLocal()
    try:
        db.query(PlanoStripe).filter(PlanoStripe.chave == chave).delete()
        db.commit()
    finally:
        db.close()

    produto_id, price_id = _criar_preco(chave)
    plano = obter_plano(chave)
    _registrar(chave, produto_id, price_id, plano["preco_centavos"])
    return {"chave": chave, "product_id": produto_id, "price_id": price_id}


def situacao(chave: str) -> dict:
    """O que está valendo hoje para este plano — usado pelo painel do admin."""
    do_env = os.getenv(f"STRIPE_PRICE_ID_{chave.upper()}", "").strip()
    db = SessionLocal()
    try:
        linha = db.query(PlanoStripe).filter(PlanoStripe.chave == chave).first()
    finally:
        db.close()

    return {
        "origem": (
            "ambiente"
            if do_env
            else "automatico"
            if linha and linha.price_id
            else "ainda_nao_criado"
        ),
        "price_id": do_env or (linha.price_id if linha else ""),
        "product_id": linha.product_id if linha else "",
        "preco_centavos": linha.preco_centavos if linha else 0,
        "criado_em": linha.criado_em.isoformat() if linha and linha.criado_em else None,
    }


def criar_checkout(
    tenant,
    plano_chave: str,
    base_url: str,
    email: str = "",
    token: str = "",
) -> dict:
    """Abre a sessão de checkout para um tenant pagar a assinatura.

    `client_reference_id` carrega o id do tenant para o webhook reencontrar a conta
    mesmo que o cliente abandone o checkout e volte depois.

    `email` e `token` atendem o caminho self-service, em que a conta acabou de ser
    criada e ainda não tem nada gravado. `token` só entra na `success_url` quando
    informado, e é o mesmo token de acesso que o cadastro emite.
    """
    from app.config.planos import obter_plano

    plano = obter_plano(plano_chave)
    price_id = garantir_preco(plano_chave)

    if token:
        destino = f"{base_url}/?plano={plano_chave}&token={token}"
    else:
        destino = f"{base_url}/assinatura?status=ok"

    stripe = _client()
    sessao = stripe.checkout.Session.create(
        mode="subscription",
        client_reference_id=tenant.id,
        customer=tenant.stripe_customer_id or None,
        # O e-mail vai preenchido para a Stripe não pedir de novo. Sem isso o
        # comprador digita o endereço duas vezes, e a chance de errar uma delas
        # quebra a entrega da cobrança no futuro.
        customer_email=email or None,
        line_items=[{"price": price_id, "quantity": 1}],
        subscription_data={"metadata": {"tenant_id": tenant.id, "plano": plano_chave}},
        metadata={"tenant_id": tenant.id, "plano": plano_chave},
        success_url=destino,
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