import hashlib
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import Tenant

def hash_token(token: str) -> str:
    """Hash SHA-256 do token de conta."""
    return hashlib.sha256(token.encode()).hexdigest()

def obter_tenant_atual(
    x_lz_token: str = Header(default=""),
    db: Session = Depends(get_db)
) -> Tenant:
    """Resolve a conta pelo header X-LZ-Token consultando o PostgreSQL."""
    if not x_lz_token:
        raise HTTPException(status_code=401, detail="Informe o header X-LZ-Token.")
    
    token_hashed = hash_token(x_lz_token)
    tenant = db.query(Tenant).filter(Tenant.token_hash == token_hashed).first()
    
    if not tenant:
        raise HTTPException(status_code=401, detail="Token de conta inválido.")
    
    return tenant