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

    # E-mail do titular. Coluna de verdade, e não dentro de `config`, porque a
    # assinatura self-service localiza a conta por ele: quem clica em "Assinar"
    # digita só o e-mail e a Stripe devolve o pagamento. Buscar isso dentro de um
    # JSON exigiria varrer a tabela inteira, e a conta pendente precisa ser
    # reencontrada a cada tentativa.
    #
    # `index=True` sem unicidade: pode haver contas antigas repetindo e-mail,
    # criadas pelo cadastro por nome, que não exigiam e-mail. Impor unicidade
    # agora quebraria a instalação. A deduplicação vale para o caminho novo.
    email_contato = Column(String, default="", index=True)

    # --- Assinatura e cobrança ---
    # status: pendente, trial, ativo, inadimplente, suspenso, cancelado
    # `pendente` é a conta criada pelo checkout antes do pagamento: existe para o
    # webhook reencontrar, mas não libera acesso nem aparece como assinante.
    status = Column(String, default="trial", index=True)
    plano = Column(String, default="starter")
    stripe_customer_id = Column(String, default="", index=True)
    stripe_subscription_id = Column(String, default="", index=True)
    assinatura_ativa = Column(Boolean, default=False)
    renovacao_em = Column(DateTime, nullable=True)
    motivo_suspensao = Column(String, default="")
    suspenso_em = Column(DateTime, nullable=True)

    # Relações
    clientes = relationship("Cliente", back_populates="tenant")
    agendas = relationship("Agenda", back_populates="tenant")
    fila_envios = relationship("FilaEnvio", back_populates="tenant")
    pagamentos = relationship("Pagamento", back_populates="tenant", cascade="all, delete-orphan")

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


class Pagamento(Base):
    """Registro imutável de cada evento de cobrançaprocessado.

    O `stripe_event_id` é único: o webhook do Stripe pode reenviar o mesmo evento
    quantas vezes quiser e a gravação é idempotente, então nunca contamos a mesma
    cobrança duas vezes no painel do admin.
    """

    __tablename__ = "pagamentos"

    id = Column(String, primary_key=True, default=gerar_id_curto)
    tenant_id = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    stripe_event_id = Column(String, unique=True, index=True)
    tipo = Column(String, default="") # checkout, renovacao, falha, cancelamento, manual
    status = Column(String, default="") # pago, falhou, pendente, cancelado, estornado
    valor_centavos = Column(Integer, default=0)
    moeda = Column(String, default="BRL")
    descricao = Column(String, default="")
    criado_em = Column(DateTime, default=datetime.utcnow, index=True)

    tenant = relationship("Tenant", back_populates="pagamentos")


class PlanoStripe(Base):
    """Cache dos preços recorrentes criados sob demanda no Stripe.

    O produto e o preço são criados automaticamente na primeira compra de cada
    plano, sem passo manual no painel do Stripe. Guardamos o `price_id` aqui para
    não chamar a API a cada checkout — e, mais importante, para não criar um
    produto novo a cada venda.

    A busca por `metadata['lembrazap_plano']` é a rede de segurança: se o banco for
    recriado, o sistema reencontra o produto existente em vez de duplicá-lo.

    O preço gravado aqui é o **preço cobrado dos assinantes daquele plano**. Mudar
    o valor em `app/config/planos.py` só afeta quem assinar depois — quem já está
    assinado continua no preço antigo, e é preciso migrar a assinatura na Stripe
    para mudar isso.
    """

    __tablename__ = "planos_stripe"

    chave = Column(String, primary_key=True)  # starter, pro, business
    product_id = Column(String, default="")
    price_id = Column(String, default="", index=True)
    preco_centavos = Column(Integer, default=0)
    criado_em = Column(DateTime, default=datetime.utcnow)
    atualizado_em = Column(DateTime, default=datetime.utcnow)


class AdminUsuario(Base):
    """Conta do proprietário do sistema, separada de `Tenant` de propósito.

    O admin não é um tenant: não tem base de clientes, não recebe disparo e nunca
    aparece no painel do assinante. O token dele é outro header (`X-LZ-Admin`),
    então um token de assinante não dá acesso ao painel administrativo.
    """

    __tablename__ = "admin_usuarios"

    id = Column(String, primary_key=True, default=gerar_id_curto)
    nome = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    senha_hash = Column(String, nullable=False)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    ativo = Column(Boolean, default=True)
    criado_em = Column(DateTime, default=datetime.utcnow)
    ultimo_acesso_em = Column(DateTime, nullable=True)