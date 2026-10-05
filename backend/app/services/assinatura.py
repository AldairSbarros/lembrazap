"""Estado da assinatura e regra de acesso.

Uma conta só opera enquanto `status` for `ativo` ou `trial`. Os demais estados
(`inadimplente`, `suspenso`, `cancelado`) cortam o envio de mensagens e a criação de
agendamentos, mas **não** apagam dados nem derrubam o login: o assinante precisa
conseguir entrar e ver a tela de assinatura vencida para voltar a pagar.

O processamento dos eventos do Stripe é idempotente. O Stripe reenvia webhook até receber
200, então gravamos o `stripe_event_id` com índice único e ignoramos o que já foi visto —
duas entregas do mesmo evento não viram duas cobranças no painel.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.db.models import Pagamento, Tenant

log = logging.getLogger(__name__)

STATUS_LIBERA_ACESSO = {"ativo", "trial"}

# Tradução para o painel admin e para o mensajeiro do assinante.
ROTULO_STATUS = {
    "trial": "Período de teste",
    "ativo": "Ativo",
    "inadimplente": "Inadimplente",
    "suspenso": "Suspenso",
    "cancelado": "Cancelado",
}

MSG_BLOQUEIO = {
    "inadimplente": "Sua assinatura está com pagamento pendente. Regularize para voltar a enviar mensagens.",
    "suspenso": "Sua conta está suspensa. Fale com o suporte para reativar.",
    "cancelado": "Sua assinatura foi cancelada. Reative quando quiser voltar.",
    "expirado": "Seu período de teste terminou. Assine um plano para continuar.",
}


def pode_operar(tenant: Tenant) -> tuple[bool, str]:
    """Diz se a conta pode enviar mensagens e criar agendamentos.

    Retorna `(liberado, motivo)`. Lógica duplicada em `deps.py` de propósito: o
    worker do Celery não passa pelos FastAPI Depends, então os dois precisam decidir
    igual sozinhos.
    """
    status = (tenant.status or "trial").lower()

    if status in STATUS_LIBERA_ACESSO:
        if status == "trial" and tenant.renovacao_em and tenant.renovacao_em < datetime.utcnow():
            return False, MSG_BLOQUEIO["expirado"]
        return True, ""

    return False, MSG_BLOQUEIO.get(status, MSG_BLOQUEIO["suspenso"])


def _tenant_por_cliente(db, objeto: dict) -> Tenant | None:
    """Reencontra a conta pelo webhook, aceitando as três chaves possíveis.

    O id direto vem do metadata. Os fallbacks existem porque o
    `customer.subscription.updated` chega só com o id do customer, e um
    `invoice.payment_failed` pode chegar antes de qualquer metadata gravada.
    """
    tenant_id = (objeto.get("metadata") or {}).get("tenant_id")
    if tenant_id:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if tenant:
            return tenant

    for chave, coluna in (
        ("subscription", Tenant.stripe_subscription_id),
        ("customer", Tenant.stripe_customer_id),
    ):
        valor = objeto.get(chave)
        if valor:
            tenant = db.query(Tenant).filter(coluna == valor).first()
            if tenant:
                return tenant
    return None


def _ja_processado(db, event_id: str) -> bool:
    return (
        db.query(Pagamento).filter(Pagamento.stripe_event_id == event_id).first()
        is not None
    )


def registrar(
    db,
    tenant_id: str,
    tipo: str,
    status: str,
    valor: int = 0,
    descricao: str = "",
    event_id: str | None = None,
) -> Pagamento | None:
    """Grava um pagamento. Devolve None se o evento já tinha sido visto."""
    pagamento = Pagamento(
        tenant_id=tenant_id,
        stripe_event_id=event_id,
        tipo=tipo,
        status=status,
        valor_centavos=valor,
        descricao=descricao,
    )
    db.add(pagamento)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        log.info("[assinatura] evento %s já registrado, ignorado", event_id)
        return None
    return pagamento


def _marcar_ativo(db, tenant: Tenant, renovacao_em, plano: str) -> None:
    mudancas = []
    if not tenant.assinatura_ativa:
        mudancas.append("assinatura_ativa=True")
    if tenant.status in ("inadimplente", "suspenso"):
        mudancas.append(f"status {tenant.status}->ativo")
    tenant.status = "ativo"
    tenant.assinatura_ativa = True
    tenant.renovacao_em = renovacao_em
    tenant.motivo_suspensao = ""
    tenant.suspenso_em = None
    if plano:
        tenant.plano = plano
    db.commit()
    if mudancas:
        log.info("[assinatura] tenant %s reativado: %s", tenant.id, ", ".join(mudancas))


def _marcar_inadimplente(db, tenant: Tenant, motivo: str) -> None:
    """Corta o acesso e cancela a fila pendente: nada de cobrar cliente inadimplente."""
    tenant.status = "inadimplente"
    tenant.assinatura_ativa = False
    tenant.motivo_suspensao = motivo
    tenant.suspenso_em = datetime.utcnow()
    db.commit()
    log.warning("[assinatura] tenant %s marcado inadimplente: %s", tenant.id, motivo)


def processar_evento(db, evento: dict) -> str:
    """Aplica um evento do Stripe. Devolve o que foi feito, para log e resposta.

    Nunca levanta por erro de negócio: uma assinatura que já não existe mais não pode
    derrubar o worker e deixar os demais tenants sem sincronizar.
    """
    event_id, tipo = evento.get("id", ""), evento.get("tipo", "")
    objeto = evento.get("objeto") or {}

    if event_id and _ja_processado(db, event_id):
        return "duplicado"

    tenant = _tenant_por_cliente(db, objeto)

    if tipo == "checkout.session.completed":
        if not tenant:
            log.warning("[assinatura] checkout sem tenant correspondente: %s", event_id)
            return "sem_tenant"
        if objeto.get("subscription"):
            tenant.stripe_subscription_id = objeto["subscription"]
            db.commit()
        _marcar_ativo(db, tenant, None, objeto.get("metadata", {}).get("plano", ""))
        registrar(
            db, tenant.id, "checkout", "pago",
            objeto.get("amount_total", 0), "Assinatura inicial", event_id,
        )
        return "checkout"

    if tipo in ("invoice.paid", "invoice.payment_succeeded"):
        if not tenant:
            return "sem_tenant"
        renovacao = None
        if objeto.get("lines", {}).get("data"):
            item = objeto["lines"]["data"][0]
            renovacao = datetime.utcfromtimestamp(item["period"]["end"]) if item.get("period") else None
        _marcar_ativo(db, tenant, renovacao, "")
        registrar(
            db, tenant.id, "renovacao", "pago",
            objeto.get("amount_paid", 0), "Renovação mensal", event_id,
        )
        return "renovacao"

    if tipo == "invoice.payment_failed":
        if not tenant:
            return "sem_tenant"
        _marcar_inadimplente(db, tenant, "Falha na última cobrança")
        registrar(
            db, tenant.id, "falha", "falhou",
            objeto.get("amount_due", 0), "Falha na cobrança", event_id,
        )
        return "falha"

    if tipo in ("customer.subscription.deleted", "customer.subscription.updated"):
        if not tenant:
            return "sem_tenant"
        if objeto.get("status") in ("canceled", "unpaid", "incomplete_expired"):
            tenant.status = "cancelado" if objeto.get("status") == "canceled" else "inadimplente"
            tenant.assinatura_ativa = False
            tenant.motivo_suspensao = f"Assinatura {objeto.get('status')}"
            tenant.suspenso_em = datetime.utcnow()
            db.commit()
            return "assinatura_encerrada"

        renovacao = None
        if objeto.get("current_period_end"):
            renovacao = datetime.utcfromtimestamp(objeto["current_period_end"])
        _marcar_ativo(db, tenant, renovacao, "")
        return "assinatura_ok"

    return "ignorado"


def suspender_manual(db, tenant: Tenant, motivo: str) -> Tenant:
    """Suspensão feita pelo admin. Preserva o histórico de cobrança."""
    tenant.status = "suspenso"
    tenant.assinatura_ativa = False
    tenant.motivo_suspensao = motivo or "Suspenso pelo administrador"
    tenant.suspenso_em = datetime.utcnow()
    db.commit()
    return tenant


def reativar_manual(db, tenant: Tenant, dias: int | None = None) -> Tenant:
    """Reativação manual pelo admin. `dias` estende a validade do acesso."""
    tenant.status = "ativo"
    tenant.assinatura_ativa = True
    tenant.motivo_suspensao = ""
    tenant.suspenso_em = None
    if dias:
        tenant.renovacao_em = datetime.utcnow().replace(microsecond=0) + timedelta(days=dias)
    db.commit()
    return tenant