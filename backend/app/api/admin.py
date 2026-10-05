"""Painel do proprietário: gestão de contas, cobrança e métricas.

Estas rotas **não** usam `obter_tenant_atual`. O admin não é um tenant: tem header
próprio (`X-LZ-Admin`), não tem base de clientes e não entra no fluxo de disparo.

Todo acesso exige `obter_admin_atual`. A única exceção é o webhook do Stripe, que se
autentica pela assinatura criptográfica da requisição (`Stripe-Signature`) e precisa
responder 200 rápido para o Stripe não reenviar.
"""

import secrets
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import hash_token, obter_admin_atual
from app.config.planos import listar_planos
from app.db.database import get_db
from app.db.models import Agenda, AdminUsuario, Cliente, FilaEnvio, Pagamento, Tenant
from app.services import assinatura, evolution, stripe
from app.services.seguranca import hash_senha, verificar_senha

router = APIRouter(prefix="/api/admin", tags=["Administração"])
log = logging.getLogger(__name__)

# Cliente sem visita neste intervalo conta como inativo no painel.
DIAS_ATIVO = 90

ERRO_ADMIN = {
    401: {
        "description": "Header `X-LZ-Admin` ausente ou sessão inválida.",
        "content": {"application/json": {"example": {"detail": "Sessão de administrador inválida."}}},
    }
}


# ---------------------------------------------------------------- schemas


class LoginAdminReq(BaseModel):
    email: str = Field(..., examples=["admin@lembrazap.com.br"])
    senha: str = Field(..., examples=["sua-senha"])


class NovoTenantReq(BaseModel):
    nome: str = Field(..., examples=["Barbearia Barros"])
    negocio: str = Field(default="", examples=["Barbearia Barros"])
    email: str = Field(default="", examples=["contato@barbearia.com.br"])
    plano: str = Field(default="starter", examples=["pro"])
    dias_teste: int = Field(default=14, ge=0, le=365, description="0 = já cobrar.")
    criar_instancia: bool = Field(default=True, description="Criar instância Evolution agora.")


class EdicaoTenantReq(BaseModel):
    nome: str | None = None
    negocio: str | None = None
    email_contato: str | None = None
    plano: str | None = None


class SuspensaoReq(BaseModel):
    motivo: str = Field(default="", max_length=200)


class ReativacaoReq(BaseModel):
    dias: int = Field(default=30, ge=0, le=730, description="0 = sem data de expiração.")


class TrocarSenhaReq(BaseModel):
    senha_atual: str = Field(...)
    nova_senha: str = Field(..., min_length=6, max_length=128)


# ---------------------------------------------------------------- login


@router.post(
    "/login",
    summary="Entra no painel administrativo",
    description="Autentica o proprietário e devolve o token do header `X-LZ-Admin`.",
)
def login(req: LoginAdminReq, db: Session = Depends(get_db)):
    admin = (
        db.query(AdminUsuario)
        .filter(AdminUsuario.email == req.email.strip().lower())
        .first()
    )

    # Mesma mensagem para e-mail inexistente e senha errada: não dizemos se o
    # e-mail está cadastrado, o que permitiria enumerar contas.
    if not admin or not verificar_senha(req.senha, admin.senha_hash):
        raise HTTPException(status_code=401, detail="E-mail ou senha inválidos.")

    if not admin.ativo:
        raise HTTPException(status_code=403, detail="Conta de administrador desativada.")

    token = secrets.token_hex(24)
    admin.token_hash = hash_token(token)
    admin.ultimo_acesso_em = datetime.utcnow()
    db.commit()

    return {"token": token, "nome": admin.nome, "email": admin.email}


@router.get(
    "/eu",
    summary="Dados da sessão administrativa",
    dependencies=[Depends(obter_admin_atual)],
)
def eu(admin: AdminUsuario = Depends(obter_admin_atual)):
    return {"id": admin.id, "nome": admin.nome, "email": admin.email}


@router.post(
    "/trocar-senha",
    summary="Troca a senha do administrador",
    dependencies=[Depends(obter_admin_atual)],
)
def trocar_senha(
    req: TrocarSenhaReq,
    db: Session = Depends(get_db),
    admin: AdminUsuario = Depends(obter_admin_atual),
):
    """Exige a senha atual: se o token vazar, o atacante não troca a senha."""
    if not verificar_senha(req.senha_atual, admin.senha_hash):
        raise HTTPException(status_code=401, detail="Senha atual incorreta.")

    admin.senha_hash = hash_senha(req.nova_senha)
    admin.token_hash = hash_token(secrets.token_hex(24))
    db.commit()
    return {"ok": True, "mensagem": "Senha alterada. Entre novamente."}


# ---------------------------------------------------------------- métricas


def _metricas(db: Session, tenant_id: str) -> dict:
    """Números de uma conta.

    Consultas separadas em vez de um JOIN com `count(distinct)`: clientes e
    agendamentos têm cardinalidades diferentes e um JOIN sem cuidado infla a
    contagem de agendamentos pelo número de clientes.
    """
    corte = datetime.utcnow() - timedelta(days=DIAS_ATIVO)
    inicio_mes = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_clientes = (
        db.query(func.count(Cliente.id)).filter(Cliente.tenant_id == tenant_id).scalar() or 0
    )
    ativos = (
        db.query(func.count(Cliente.id))
        .filter(Cliente.tenant_id == tenant_id, Cliente.ultima_visita >= corte)
        .scalar()
        or 0
    )
    agendamentos_hoje = (
        db.query(func.count(Agenda.id))
        .filter(
            Agenda.tenant_id == tenant_id,
            func.date(Agenda.quando) == func.current_date(),
            Agenda.status.notin_(["cancelado", "concluido"]),
        )
        .scalar()
        or 0
    )
    enviados_mes = (
        db.query(func.count(FilaEnvio.id))
        .filter(
            FilaEnvio.tenant_id == tenant_id,
            FilaEnvio.status == "enviado",
            FilaEnvio.enviado_em >= inicio_mes,
        )
        .scalar()
        or 0
    )
    falhas_mes = (
        db.query(func.count(FilaEnvio.id))
        .filter(
            FilaEnvio.tenant_id == tenant_id,
            FilaEnvio.status == "falha",
            FilaEnvio.criado_em >= inicio_mes,
        )
        .scalar()
        or 0
    )

    return {
        "clientes_total": total_clientes,
        "clientes_ativos": ativos,
        "clientes_inativos": total_clientes - ativos,
        "agendamentos_hoje": agendamentos_hoje,
        "mensagens_mes": enviados_mes,
        "falhas_mes": falhas_mes,
    }


def _resumo(tenant: Tenant, db: Session) -> dict:
    """Forma de uma conta para a lista do painel."""
    liberado, motivo = assinatura.pode_operar(tenant)
    plano = next((p for p in listar_planos() if p["chave"] == tenant.plano), None)
    return {
        "id": tenant.id,
        "nome": tenant.nome,
        "negocio": tenant.negocio,
        # Lê a coluna, com o JSON como reserva para contas criadas antes da migração.
  "email_contato": tenant.email_contato or (tenant.config or {}).get("email_contato", ""),
        "status": tenant.status or "trial",
        "status_rotulo": assinatura.ROTULO_STATUS.get(tenant.status or "trial", tenant.status),
        "plano": tenant.plano,
        "plano_nome": plano["nome"] if plano else tenant.plano,
        "assinatura_ativa": bool(tenant.assinatura_ativa),
        "acesso_liberado": liberado,
        "motivo_bloqueio": motivo,
        "renovacao_em": tenant.renovacao_em.isoformat() if tenant.renovacao_em else None,
        "criado_em": tenant.criado_em.isoformat() if tenant.criado_em else None,
        "ultima_envio_em": (
            tenant.ultima_envio_em.isoformat() if tenant.ultima_envio_em else None
        ),
        "tem_instancia": bool(tenant.instancia),
        "no_stripe": bool(tenant.stripe_customer_id or tenant.stripe_subscription_id),
        "metricas": _metricas(db, tenant.id),
    }


@router.get(
    "/planos",
    summary="Catálogo de planos comercializados",
    dependencies=[Depends(obter_admin_atual)],
)
def planos():
    """Catálogo com o preço **efetivo** de cada plano.

    `preco_centavos` vem do catálogo; `em_vigor_centavos` é o que a Stripe está
    cobrando hoje. Divergem quando o dono mudou o valor em `planos.py` e ainda não
    rodou a sincronização — e a consequência não é só de exibição, ver
    `POST /planos/{chave}/sincronizar`.
    """
    resultado = []
    for plano in listar_planos():
        if stripe.disponivel():
            em_vigor = stripe.situacao(plano["chave"])
        else:
            em_vigor = {
                "origem": "sem_stripe",
                "price_id": "",
                "product_id": "",
                "preco_centavos": 0,
                "criado_em": None,
            }
        resultado.append(
            {
                **plano,
                "stripe": em_vigor,
                "divergente": bool(
                    em_vigor["preco_centavos"]
                    and em_vigor["preco_centavos"] != plano["preco_centavos"]
                ),
            }
        )

    return {"planos": resultado, "stripe_configurado": stripe.disponivel()}


@router.post(
    "/planos/{chave}/sincronizar",
    summary="Recria o preço de um plano no Stripe",
    dependencies=[Depends(obter_admin_atual)],
)
def sincronizar_plano(
    chave: str,
    db: Session = Depends(get_db),
    admin: AdminUsuario = Depends(obter_admin_atual),
):
    """Cria um preço novo com o valor atual do catálogo.

    **Não muda o que os assinantes atuais pagam.** O `price_id` antigo continua
    valendo para as assinaturas criadas com ele — na Stripe, preço é imutável e
    mover uma assinatura exige editar o item dela. Esta rota só faz novos
    assinantes pagarem o valor novo.

    Quem já está assinado precisa ser migrado na Stripe: em cada assinatura,
    *Editar item* → *Atualizar preço* → escolher o novo.
    """
    chave = chave.strip().lower()
    if not any(p["chave"] == chave for p in listar_planos()):
        raise HTTPException(status_code=404, detail=f"Plano '{chave}' não existe.")

    if not stripe.disponivel():
        raise HTTPException(
            status_code=503, detail="Stripe não configurado neste ambiente."
        )

    try:
        resultado = stripe.sincronizar(chave)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Stripe respondeu com erro: {exc}")

    return {
        "ok": True,
        **resultado,
        "mensagem": (
            "Novo preço criado. Assinantes atuais continuam no preço antigo — "
            "migre as assinaturas na Stripe para aplicar o valor novo a eles."
        ),
    }


@router.get(
    "/metricas",
    summary="Visão geral de todas as contas",
    dependencies=[Depends(obter_admin_atual)],
)
def metricas_gerais(
    db: Session = Depends(get_db), admin: AdminUsuario = Depends(obter_admin_atual)
):
    """Totais do sistema para o topo do painel."""
    tenants = db.query(Tenant).all()

    por_status: dict[str, int] = {}
    com_acesso = 0
    for t in tenants:
        status = t.status or "trial"
        por_status[status] = por_status.get(status, 0) + 1
        if assinatura.pode_operar(t)[0]:
            com_acesso += 1

    inicio_mes = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    receita = (
        db.query(func.coalesce(func.sum(Pagamento.valor_centavos), 0))
        .filter(Pagamento.status == "pago", Pagamento.criado_em >= inicio_mes)
        .scalar()
        or 0
    )
    mensagens = (
        db.query(func.count(FilaEnvio.id))
        .filter(FilaEnvio.status == "enviado", FilaEnvio.enviado_em >= inicio_mes)
        .scalar()
        or 0
    )

    return {
        "total_contas": len(tenants),
        "contas_com_acesso": com_acesso,
        "por_status": por_status,
        "receita_mes_centavos": receita,
        "mensagens_mes": mensagens,
        "stripe_configurado": stripe.disponivel(),
    }


# ---------------------------------------------------------------- contas


@router.get(
    "/contas",
    summary="Lista todas as contas com métricas",
    dependencies=[Depends(obter_admin_atual)],
)
def listar_contas(
    busca: str = Query(default="", description="Filtra por nome, negócio ou e-mail."),
    status: str = Query(default="", description="Filtra por status exato."),
    db: Session = Depends(get_db),
    admin: AdminUsuario = Depends(obter_admin_atual),
):
    """Busca é feita em Python sobre a lista filtrada por status: com poucas centenas
    de contas isso é mais simples que indexar nome normalizado, e evita que uma
    busca por "barbearia" devolva nada por causa de acento ou caixa."""
    query = db.query(Tenant)
    if status.strip():
        query = query.filter(Tenant.status == status.strip().lower())

    contas = [_resumo(t, db) for t in query.order_by(Tenant.criado_em.desc()).all()]

    if busca.strip():
        alvo = busca.strip().lower()
        contas = [
            c
            for c in contas
            if alvo in c["nome"].lower()
            or alvo in (c["negocio"] or "").lower()
            or alvo in (c["email_contato"] or "").lower()
        ]

    return {"contas": contas, "total": len(contas)}


@router.post(
    "/contas",
    status_code=201,
    summary="Cria uma conta manualmente",
    dependencies=[Depends(obter_admin_atual)],
)
def criar_conta(
    req: NovoTenantReq,
    db: Session = Depends(get_db),
    admin: AdminUsuario = Depends(obter_admin_atual),
):
    """Cria a conta e devolve o token **em claro**, que não é recuperável depois.

    Use para teste, cortesia ou venda presencial. Para venda com pagamento, prefira
    o checkout do Stripe (rota de assinatura do tenant), que já ativa o acesso.
    """
    token = secrets.token_hex(24)
    tenant = Tenant(
        nome=req.nome.strip(),
        negocio=(req.negocio or req.nome).strip(),
        token_hash=hash_token(token),
        plano=req.plano.strip().lower(),
        status="trial" if req.dias_teste > 0 else "inadimplente",
        assinatura_ativa=req.dias_teste > 0,
        renovacao_em=(
            datetime.utcnow() + timedelta(days=req.dias_teste)
            if req.dias_teste > 0
            else None
        ),
        config={"email_contato": req.email.strip()},
    )
    db.add(tenant)
    db.commit()

    instancia = ""
    aviso = ""
    if req.criar_instancia:
        nome_instancia = f"LZ_{tenant.id}".upper()
        try:
            evolution.criar_instancia(nome_instancia)
            tenant.instancia = nome_instancia
            db.commit()
            instancia = nome_instancia
        except Exception as exc:  # noqa: BLE001
            # A conta já existe; falhar só a instância não pode desfazer a criação.
            aviso = f"Conta criada, mas a instância Evolution falhou: {exc}"

    return {
        "ok": True,
        "tenant_id": tenant.id,
        "token": token,
        "instancia": instancia,
        "aviso": aviso,
        "mensagem": "Token exibido uma única vez. Guarde-o para enviar ao cliente.",
    }


def _exigir_conta(db: Session, tenant_id: str) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Conta não encontrada.")
    return tenant


@router.get(
    "/contas/{tenant_id}",
    summary="Detalhe de uma conta",
    dependencies=[Depends(obter_admin_atual)],
)
def detalhe_conta(
    tenant_id: str,
    db: Session = Depends(get_db),
    admin: AdminUsuario = Depends(obter_admin_atual),
):
    tenant = _exigir_conta(db, tenant_id)
    resumo = _resumo(tenant, db)

    resumo["motivo_suspensao"] = tenant.motivo_suspensao or ""
    resumo["suspenso_em"] = tenant.suspenso_em.isoformat() if tenant.suspenso_em else None
    resumo["instancia"] = tenant.instancia or ""
    resumo["stripe_subscription_id"] = tenant.stripe_subscription_id or ""
    resumo["pagamentos"] = [
        {
            "id": p.id,
            "tipo": p.tipo,
            "status": p.status,
            "valor_centavos": p.valor_centavos,
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
    return resumo


@router.patch(
    "/contas/{tenant_id}",
    summary="Edita dados e plano de uma conta",
    dependencies=[Depends(obter_admin_atual)],
)
def editar_conta(
    tenant_id: str,
    req: EdicaoTenantReq,
    db: Session = Depends(get_db),
    admin: AdminUsuario = Depends(obter_admin_atual),
):
    """Muda plano e dados cadastrais.

    Não mexe em status: para isso use suspender/reativar, que registram a decisão.
    Token só muda por `/token`, para ficar explícito quando um acesso é revogado.
    """
    tenant = _exigir_conta(db, tenant_id)

    if req.nome is not None:
        tenant.nome = req.nome.strip()
    if req.negocio is not None:
        tenant.negocio = req.negocio.strip()
    if req.email_contato is not None:
        tenant.config = {**(tenant.config or {}), "email_contato": req.email_contato.strip()}
    if req.plano is not None:
        tenant.plano = req.plano.strip().lower()

    db.commit()
    return _resumo(tenant, db)


@router.post(
    "/contas/{tenant_id}/suspender",
    summary="Suspende uma conta",
    dependencies=[Depends(obter_admin_atual)],
)
def suspender_conta(
    tenant_id: str,
    req: SuspensaoReq,
    db: Session = Depends(get_db),
    admin: AdminUsuario = Depends(obter_admin_atual),
):
    """Corta o envio de mensagens imediatamente.

    A fila pendente é esvaziada junto: sem isso, um lembrete disparado antes da
    suspensão ainda sairia depois dela.
    """
    tenant = _exigir_conta(db, tenant_id)
    assinatura.suspender_manual(db, tenant, req.motivo)

    pendentes = (
        db.query(FilaEnvio)
        .filter(FilaEnvio.tenant_id == tenant.id, FilaEnvio.status == "pendente")
        .count()
    )
    if pendentes:
        (
            db.query(FilaEnvio)
            .filter(FilaEnvio.tenant_id == tenant.id, FilaEnvio.status == "pendente")
            .delete(synchronize_session=False)
        )
        db.commit()

    return {
        "ok": True,
        "contas": _resumo(tenant, db),
        "fila_limpa": pendentes,
        "mensagem": f"Conta suspensa. {pendentes} envio(s) pendente(s) descartado(s).",
    }


@router.post(
    "/contas/{tenant_id}/reativar",
    summary="Reativa uma conta suspensa ou inadimplente",
    dependencies=[Depends(obter_admin_atual)],
)
def reativar_conta(
    tenant_id: str,
    req: ReativacaoReq,
    db: Session = Depends(get_db),
    admin: AdminUsuario = Depends(obter_admin_atual),
):
    """Volta o acesso e, se `dias` vier, define até quando vale.

    Útil para os dois cenários de cobrança: conceder mais dias de teste ou liberar
    manualmente uma conta que quitou pelo WhatsApp, sem passar pelo Stripe.
    """
    tenant = _exigir_conta(db, tenant_id)

    if req.dias == 0:
        tenant.renovacao_em = None
        assinatura.reativar_manual(db, tenant, None)
    else:
        assinatura.reativar_manual(db, tenant, req.dias)

    assinatura.registrar(
        db, tenant.id, "manual", "pago", 0, f"Reativação manual por {admin.email}"
    )
    return _resumo(tenant, db)


@router.post(
    "/contas/{tenant_id}/token",
    summary="Gera um novo token de acesso",
    dependencies=[Depends(obter_admin_atual)],
)
def regenerar_token(
    tenant_id: str,
    db: Session = Depends(get_db),
    admin: AdminUsuario = Depends(obter_admin_atual),
):
    """Invalida o token anterior de imediato — é a ação de suporte para token vazado."""
    tenant = _exigir_conta(db, tenant_id)
    token = secrets.token_hex(24)
    tenant.token_hash = hash_token(token)
    db.commit()
    return {
        "ok": True,
        "token": token,
        "mensagem": "Token exibido uma única vez. O anterior deixou de funcionar.",
    }


@router.get(
    "/contas/{tenant_id}/clientes",
    summary="Base de clientes de uma conta",
    dependencies=[Depends(obter_admin_atual)],
)
def clientes_da_conta(
    tenant_id: str,
    busca: str = Query(default=""),
    limite: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: AdminUsuario = Depends(obter_admin_atual),
):
    """Leitura da base para suporte e conferência.

    Telefone vem mascarado: o painel do admin serve para resolver problema, não para
    virar uma lista de contatos para exportar.
    """
    _exigir_conta(db, tenant_id)

    query = db.query(Cliente).filter(Cliente.tenant_id == tenant_id)
    if busca.strip():
        alvo = busca.strip().lower()
        query = query.filter(Cliente.nome.ilike(f"%{alvo}%"))

    corte = datetime.utcnow() - timedelta(days=DIAS_ATIVO)
    total = query.count()
    lista = query.order_by(Cliente.ultima_visita.is_(None), Cliente.ultima_visita).limit(limite).all()

    return {
        "total": total,
        "clientes": [
            {
                "id": c.id,
                "nome": c.nome,
                "telefone_mascarado": f"***{c.telefone[-4:]}",
                "ultima_visita": c.ultima_visita.isoformat() if c.ultima_visita else None,
                "situacao": "ativo" if c.ultima_visita and c.ultima_visita >= corte else "inativo",
                "opt_out": bool(c.opt_out),
                "criado_em": c.criado_em.isoformat() if c.criado_em else None,
            }
            for c in lista
        ],
    }


# ---------------------------------------------------------------- Stripe


@router.post(
    "/stripe/webhook",
    summary="Recebe eventos do Stripe",
    description=(
        "Autenticado por assinatura `Stripe-Signature`, não por token. "
        "Configure no Stripe: `POST https://seudominio/api/admin/stripe/webhook`."
    ),
)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Ponto único de entrada dos eventos de cobrança.

    Respondemos 200 mesmo quando não conseguimos identificar a conta, porque
    devolver erro faz o Stripe reenviar por dias. Um evento órfão é logado e
    descartado — devolver 500 aqui transformaria uma conta apagada num ciclo
    infinito de reenvio.
    """
    payload = await request.body()
    assinatura_header = request.headers.get("stripe-signature", "")

    try:
        evento = stripe.confirmar_webhook(payload, assinatura_header)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Assinatura inválida: {exc}")
    except Exception as exc:  # noqa: BLE001
        log.error("[stripe] falha ao validar webhook: %s", exc)
        raise HTTPException(status_code=400, detail="Não foi possível validar o evento.")

    try:
        resultado = assinatura.processar_evento(db, evento)
    except Exception as exc:  # noqa: BLE001
        log.exception("[stripe] erro ao processar %s", evento.get("tipo"))
        raise HTTPException(status_code=500, detail=f"Falha ao processar evento: {exc}")

    log.info("[stripe] %s -> %s", evento.get("tipo"), resultado)
    return {"ok": True, "resultado": resultado}