import hashlib

from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import AdminUsuario, Tenant
from app.services.assinatura import pode_operar


def hash_token(token: str) -> str:
    """Hash SHA-256 do token de conta."""
    return hashlib.sha256(token.encode()).hexdigest()


def obter_tenant_atual(
    x_lz_token: str = Header(default=""),
    db: Session = Depends(get_db),
) -> Tenant:
    """Resolve a conta pelo header X-LZ-Token consultando o PostgreSQL."""
    if not x_lz_token:
        raise HTTPException(status_code=401, detail="Informe o header X-LZ-Token.")

    token_hashed = hash_token(x_lz_token)
    tenant = db.query(Tenant).filter(Tenant.token_hash == token_hashed).first()

    if not tenant:
        raise HTTPException(status_code=401, detail="Token de conta inválido.")

    return tenant


def exigir_acesso_ativo(tenant: Tenant = Depends(obter_tenant_atual)) -> Tenant:
    """Impede operação em conta suspensa, inadimplente ou com teste vencido.

    Resposta 402 (`Payment Required`) em vez de 403: o problema é de pagamento, e o
    frontend usa esse status para abrir a tela de assinatura em vez de mostrar erro.
    Contas bloqueadas continuam conseguindo ler a própria base e abrir o painel — só
    não criam agendamento nem disparam mensagem.
    """
    liberado, motivo = pode_operar(tenant)
    if not liberado:
        raise HTTPException(
            status_code=402,
            detail={
                "erro": "assinatura_inativa",
                "mensagem": motivo,
                "status": tenant.status,
                "plano": tenant.plano,
                "renovacao_em": tenant.renovacao_em.isoformat() if tenant.renovacao_em else None,
            },
        )
    return tenant


def obter_admin_atual(
    x_lz_admin: str = Header(default=""),
    db: Session = Depends(get_db),
) -> AdminUsuario:
    """Resolve o proprietário do sistema pelo header `X-LZ-Admin`.

    Header separado do `X-LZ-Token` de propósito: um token de assinante nunca abre o
    painel administrativo, mesmo vazado.
    """
    if not x_lz_admin:
        raise HTTPException(status_code=401, detail="Informe o header X-LZ-Admin.")

    admin = (
        db.query(AdminUsuario)
        .filter(AdminUsuario.token_hash == hash_token(x_lz_admin), AdminUsuario.ativo.is_(True))
        .first()
    )

    if not admin:
        raise HTTPException(status_code=401, detail="Sessão de administrador inválida.")

    return admin