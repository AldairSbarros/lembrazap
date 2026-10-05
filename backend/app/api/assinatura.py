"""Assinatura vista pelo próprio cliente.

Distingue três coisas que o assinante costuma confundir:

- **Status da conta** (`status`): diz se ele pode operar agora.
- **Limite do plano** (`limite_clientes`, `limite_mensagens_mes`): o que ele pode
  usar enquanto opera.
- **Pagamento** (`pagamentos`): o histórico financeiro, que aparece apenas para o
  próprio cliente e nunca expõe outro tenant.

O `X-LZ-Token` continua obrigatório: nenhuma rota aqui aceita o token de outro tenant,
porque quem resolve a conta é sempre o `obter_tenant_atual`.
"""

import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import obter_tenant_atual
from app.config.planos import limite_clientes, limite_mensagens, listar_planos, obter_plano
from app.db.database import get_db
from app.db.models import Cliente, FilaEnvio, Pagamento, Tenant
from app.services import assinatura, stripe

router = APIRouter(prefix="/api/assinatura", tags=["Assinatura"])

BASE_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")


class CheckoutReq(BaseModel):
    plano: str = Field(..., examples=["pro"], description="Chave do plano: starter, pro ou business.")


class _LimitesPayload(BaseModel):
    """Resposta do limite, lida pelo `Clientes.jsx` antes de importar CSV."""

    limite_clientes: int
    clientes_no_plano: int
    restantes: int
    excedeu: bool


@router.get(
    "",
    summary="Estado da assinatura e cobrança",
)
def estado(
    tenant: Tenant = Depends(obter_tenant_atual),
    db: Session = Depends(get_db),
):
    liberado, motivo = assinatura.pode_operar(tenant)
    plano = obter_plano(tenant.plano) or listar_planos()[0]

    return {
        "status": tenant.status or "trial",
        "status_rotulo": assinatura.ROTULO_STATUS.get(tenant.status or "trial", tenant.status),
        "acesso_liberado": liberado,
        "mensagem_bloqueio": motivo,
        "plano": plano,
        "renovacao_em": tenant.renovacao_em.isoformat() if tenant.renovacao_em else None,
        "criado_em": tenant.criado_em.isoformat() if tenant.criado_em else None,
        "stripe_configurado": stripe.disponivel(),
        "no_stripe": bool(tenant.stripe_customer_id),
    }


@router.get(
    "/planos",
    summary="Planos disponíveis para contratação",
)
def planos():
    """Público de propósito: é a vitrine de preços da landing page."""
    return {"planos": listar_planos()}


@router.get(
    "/limites",
    summary="Consumo atual contra o limite do plano",
    response_model=_LimitesPayload,
)
def limites(
    tenant: Tenant = Depends(obter_tenant_atual),
    db: Session = Depends(get_db),
):
    """Consultado pelo painel antes de importar CSV, para barrar no cliente em vez de
    deixar a importação estourar o plano pela metade."""
    total = db.query(Cliente).filter(Cliente.tenant_id == tenant.id).count()
    teto = limite_clientes(tenant.plano)

    return {
        "limite_clientes": teto,
        "clientes_no_plano": total,
        "restantes": max(0, teto - total),
        "excedeu": total >= teto,
    }


@router.post(
    "/checkout",
    summary="Abre o pagamento da assinatura no Stripe",
)
def checkout(
    req: CheckoutReq,
    tenant: Tenant = Depends(obter_tenant_atual),
    db: Session = Depends(get_db),
):
    """Devolve a URL do Stripe para o navegador redirecionar. Não ativa nada sozinho:
    quem ativa é o webhook, depois que o pagamento é confirmado."""
    if not stripe.disponivel():
        raise HTTPException(
            status_code=503,
            detail="Pagamento online indisponível. Fale com o suporte para ativar sua conta.",
        )

    try:
        resultado = stripe.criar_checkout(tenant, req.plano.lower(), BASE_URL)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Stripe respondeu com erro: {exc}")

    return resultado


@router.post(
    "/portal",
    summary="Abre o portal de cobrança do Stripe",
)
def portal(
    tenant: Tenant = Depends(obter_tenant_atual),
    db: Session = Depends(get_db),
):
    """Permite trocar cartão, ver faturas e cancelar sem falar com o suporte."""
    if not stripe.disponivel():
        raise HTTPException(
            status_code=503, detail="Pagamento online indisponível neste ambiente."
        )

    try:
        return stripe.criar_portal(tenant, BASE_URL)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Stripe respondeu com erro: {exc}")


@router.get(
    "/pagamentos",
    summary="Histórico de cobrança da conta",
)
def pagamentos(
    tenant: Tenant = Depends(obter_tenant_atual),
    db: Session = Depends(get_db),
):
    return {
        "pagamentos": [
            {
                "id": p.id,
                "tipo": p.tipo,
                "status": p.status,
                "valor_reais": f"{p.valor_centavos / 100:.2f}".replace(".", ","),
                "descricao": p.descricao,
                "criado_em": p.criado_em.isoformat() if p.criado_em else None,
            }
            for p in db.query(Pagamento)
            .filter(Pagamento.tenant_id == tenant.id)
            .order_by(Pagamento.criado_em.desc())
            .limit(50)
            .all()
        ]
    }


@router.get(
    "/uso",
    summary="Uso de mensagens no mês contra o plano",
)
def uso(
    tenant: Tenant = Depends(obter_tenant_atual),
    db: Session = Depends(get_db),
):
    """Mostra o consumo de disparos do mês para o assinante saber quando está perto
    do teto — e para o admin poder cobrar upgrade com dado, não com impressão."""
    inicio_mes = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    enviados = (
        db.query(FilaEnvio)
        .filter(
            FilaEnvio.tenant_id == tenant.id,
            FilaEnvio.status == "enviado",
            FilaEnvio.criado_em >= inicio_mes,
        )
        .count()
    )
    teto = limite_mensagens(tenant.plano)

    return {
        "mensagens_enviadas": enviados,
        "limite_mensagens": teto,
        "restantes": max(0, teto - enviados),
        "excedeu": enviados >= teto,
    }