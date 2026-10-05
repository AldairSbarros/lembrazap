"""Assinatura vista pelo próprio cliente.

Distingue três coisas que o assinante costuma confundir:

- **Status da conta** (`status`): diz se ele pode operar agora.
- **Limite do plano** (`limite_clientes`, `limite_mensagens_mes`): o que ele pode
  usar enquanto opera.
- **Pagamento** (`pagamentos`): o histórico financeiro, que aparece apenas para o
  próprio cliente e nunca expõe outro tenant.

O `X-LZ-Token` continua obrigatório: nenhuma rota autenticada aqui aceita o token de outro
tenant, porque quem resolve a conta é sempre o `obter_tenant_atual`.

A única rota pública é `POST /api/assinatura/assinar`: o botão "Assinar" da tela de
planos precisa funcionar antes de a pessoa ter conta. Ela recebe só e-mail e plano,
cria a conta em estado `pendente` e devolve a URL da Stripe. O acesso só é liberado
pelo webhook, depois que o pagamento é confirmado.
"""

import logging
import os
import re
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import hash_token, obter_tenant_atual
from app.config.planos import limite_clientes, limite_mensagens, listar_planos, obter_plano
from app.db.database import get_db
from app.db.models import Cliente, FilaEnvio, Pagamento, Tenant
from app.services import assinatura, stripe

router = APIRouter(prefix="/api/assinatura", tags=["Assinatura"])

log = logging.getLogger(__name__)

BASE_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")

# Validação deliberadamente frouxa: o objetivo é pegar "abc" ou "a@b", não
# arbitrar o que é um endereço válido. Quem cobra é a Stripe — se o e-mail não
# chegar nela, o checkout não conclui. Rejeitar aqui por Regex mais estrita
# apenas transformaria um endereço exótico em um beco sem saída.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _email_valido(email: str) -> str:
    normalizado = email.strip().lower()
    if not _EMAIL.match(normalizado):
        raise HTTPException(
            status_code=400,
            detail="Informe um e-mail válido para receber a cobrança.",
        )
    return normalizado


class CheckoutReq(BaseModel):
    plano: str = Field(..., examples=["pro"], description="Chave do plano: starter, pro ou business.")


class AssinarReq(BaseModel):
    """Compra self-service: só e-mail e plano.

    Não pede token porque a pessoa ainda não tem conta. É este o caminho que o
    botão "Assinar" da tela de planos usa.
    """

    email: str = Field(
        ...,
        max_length=254,
        examples=["contato@barbearia.com.br"],
        description="E-mail do titular. É por ele que a conta é reencontrada.",
    )
    plano: str = Field(..., examples=["pro"], description="starter, pro ou business.")


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
    "/assinar",
    summary="Compra self-service: e-mail + plano, sem token",
    description=(
        "Cria a conta em estado `pendente` e devolve a URL do Stripe. O acesso só é "
        "liberado pelo webhook, depois que o pagamento é confirmado."
    ),
    responses={
        400: {"description": "E-mail inválido ou plano desconhecido."},
        503: {"description": "Pagamento online indisponível neste ambiente."},
    },
)
def assinar(req: AssinarReq, db: Session = Depends(get_db)):
    """Abre o checkout para quem ainda não tem conta.

    Sem token, porque a pessoa está chegando agora. A conta é criada **antes** de
    redirecionar, e não depois do webhook, por dois motivos: o `client_reference_id`
    precisa de um id para o webhook reencontrar, e a Stripe pode confirm o pagamento
    em poucos segundos — se a criação dependesse do webhook, um pagamento rápido
    cairia em "sem tenant" e a conta ficaria sem acesso.

    O estado `pendente` não libera nada (`STATUS_LIBERA_ACESSO` não o inclui) e não
    conta como assinante no painel.
    """
    if not stripe.disponivel():
        raise HTTPException(
            status_code=503,
            detail="Pagamento online indisponível. Fale com o suporte para ativar sua conta.",
        )

    email = _email_valido(req.email)
    chave_plano = req.plano.strip().lower()
    if not obter_plano(chave_plano):
        raise HTTPException(status_code=400, detail="Plano não encontrado.")

    # Reaproveita a conta pendente do mesmo e-mail. Tentar de novo depois de
    # abandonar o checkout não deve criar uma segunda conta — e nem um segundo
    # produto na Stripe, porque `garantir_preco` já é idempotente por plano.
    existente = (
        db.query(Tenant)
        .filter(Tenant.email_contato == email)
        .order_by(Tenant.criado_em.desc())
        .first()
    )

    if existente and (existente.status or "") in ("ativo", "trial"):
        raise HTTPException(
            status_code=409,
            detail="Este e-mail já tem uma conta ativa. Entre com seu acesso ou fale com o suporte.",
        )

    if existente:
        tenant = existente
        token_plano = ""
        # Atualiza o plano ao voltar. Quem tentou Starter, abandonou o checkout e
        # voltou para o Business precisa sair pagando pelo Business — o preço vem
        # de `garantir_preco(plano_chave)` logo abaixo, então deixar o plano velho
        # aqui cobraria a pessoa pelo plano que ela não escolheu.
        if tenant.plano != chave_plano:
            log.info("[assinatura] trocando plano de %s para %s", tenant.plano, chave_plano)
            tenant.plano = chave_plano
            db.commit()
    else:
        token_plano = secrets.token_hex(16)
        tenant = Tenant(
            nome=email.split("@")[0][:60],
            negocio=email.split("@")[0][:60],
            email_contato=email,
            token_hash=hash_token(token_plano),
            # `pendente`, não `trial`: conta sem pagamento não entra como teste.
            status="pendente",
            plano=chave_plano,
            assinatura_ativa=False,
            config={"email_contato": email},
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)

    try:
        resultado = stripe.criar_checkout(tenant, chave_plano, BASE_URL, email, token_plano)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        # A conta `pendente` fica no banco de propósito: o mesmo e-mail reentra
        # pela mesma linha na próxima tentativa. Apagá-la aqui perderia o
        # `client_reference_id` caso a Stripe já tivesse criado a sessão.
        log.warning("[assinatura] checkout falhou para %s: %s", email, exc)
        raise HTTPException(
            status_code=502,
            detail=f"O Stripe recusou o pagamento: {exc}",
        )

    return {**resultado, "token": token_plano}


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