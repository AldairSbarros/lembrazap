import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, JSON
from sqlalchemy.orm import relationship
from .database import Base

def gerar_id_curto():
    """Gera um ID único de 12 caracteres semelhante ao teu protótipo original."""
    return uuid.uuid4().hex[:12]

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String, primary_key=True, default=gerar_id_curto)
    nome = Column(String, nullable=False)
    negocio = Column(String, default="")
    token_hash = Column(String, unique=True, nullable=False, index=True)
    instancia = Column(String, default="")
    config = Column(JSON, default={})
    criado_em = Column(DateTime, default=datetime.utcnow)
    ultima_envio_em = Column(DateTime, nullable=True)

    # Relações
    clientes = relationship("Cliente", back_populates="tenant")
    agendas = relationship("Agenda", back_populates="tenant")
    fila_envios = relationship("FilaEnvio", back_populates="tenant")

class Cliente(Base):
    __tablename__ = "clientes"

    id = Column(String, primary_key=True, default=gerar_id_curto)
    tenant_id = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    nome = Column(String, nullable=False)
    telefone = Column(String, nullable=False, index=True)
    ultima_visita = Column(DateTime, nullable=True)
    obs = Column(String, default="")
    opt_out = Column(Boolean, default=False)
    criado_em = Column(DateTime, default=datetime.utcnow)
    respondeu_em = Column(DateTime, nullable=True)
    ultima_resposta = Column(String, default="") # Texto da última mensagem recebida (ex: "SIM", "ADIAR")
    resposta_auto_enviada = Column(Boolean, default=False)

    # Relações
    tenant = relationship("Tenant", back_populates="clientes")

class Agenda(Base):
    __tablename__ = "agenda"

    id = Column(String, primary_key=True, default=gerar_id_curto)
    tenant_id = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    cliente_id = Column(String, ForeignKey("clientes.id", ondelete="SET NULL"), nullable=True)
    telefone = Column(String, nullable=False)
    nome = Column(String, default="")
    servico = Column(String, default="") # Ex: "Corte de Cabelo", "Banho e Tosa", "Manicure"
    quando = Column(DateTime, nullable=False, index=True)
    mensagem = Column(String, default="")
    status = Column(String, default="agendado") # agendado, confirmado, reagendando, cancelado
    confirmado_em = Column(DateTime, nullable=True) # Registo exato de quando o cliente confirmou via WhatsApp
    origem = Column(String, default="manual")
    criado_em = Column(DateTime, default=datetime.utcnow)

    # Relações
    tenant = relationship("Tenant", back_populates="agendas")

class FilaEnvio(Base):
    __tablename__ = "fila"

    id = Column(String, primary_key=True, default=gerar_id_curto)
    tenant_id = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    cliente_id = Column(String, nullable=True)
    agenda_id = Column(String, nullable=True)
    telefone = Column(String, nullable=False)
    texto = Column(String, nullable=False)
    campanha = Column(String, default="")
    status = Column(String, default="pendente") # pendente, enviado, falha, opt_out
    erro = Column(String, default="")
    prioridade = Column(Integer, default=1)
    simulado = Column(Boolean, default=False)
    criado_em = Column(DateTime, default=datetime.utcnow)
    enviado_em = Column(DateTime, nullable=True)

    # Relações
    tenant = relationship("Tenant", back_populates="fila_envios")