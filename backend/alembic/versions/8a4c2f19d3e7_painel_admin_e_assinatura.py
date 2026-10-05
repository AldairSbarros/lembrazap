"""Painel do proprietário: assinatura, cobrança e contas de administrador

Adiciona o controle de acesso comercial ao schema. Três partes:

1. ``tenants`` ganha os campos de assinatura (``status``, ``plano``, ids do Stripe,
   renovação). Contas já existentes entram como ``trial`` com a assinatura fechada,
   então **nada é liberado por acidente**: o admin abre o acesso uma a uma.
2. Tabela ``pagamentos``: histórico financeiro com ``stripe_event_id`` único, que é o
   que torna o webhook idempotente quando o Stripe reenvia o mesmo evento.
3. Tabela ``admin_usuarios``: o proprietário não é um tenant, tem header de sessão
   próprio e nunca aparece no painel do assinante.

O ``index=True`` nos ids do Stripe existe porque toda mensagem do webhook busca a
conta por eles; sem índice, o painel fica lento conforme o número de contas cresce.

Revision ID: 8a4c2f19d3e7
Revises: 7f3d9c1b2e40
Create Date: 2026-10-05 02:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8a4c2f19d3e7"
down_revision: Union[str, Sequence[str], None] = "7f3d9c1b2e40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# server_default é o que salva a migração em base com dados: sem ele, `ALTER TABLE`
# numa tabela já populada falha ao preencher as linhas antigas.
_UPGRADE = [
    # --- Assinatura da conta ---
    sa.Column("status", sa.String(), nullable=False, server_default="trial"),
    sa.Column("plano", sa.String(), nullable=False, server_default="starter"),
    sa.Column("stripe_customer_id", sa.String(), nullable=True, server_default=""),
    sa.Column("stripe_subscription_id", sa.String(), nullable=True, server_default=""),
    sa.Column("assinatura_ativa", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("renovacao_em", sa.DateTime(), nullable=True),
    sa.Column("motivo_suspensao", sa.String(), nullable=True, server_default=""),
    sa.Column("suspenso_em", sa.DateTime(), nullable=True),
]

_DOWNGRADE = [
    "suspenso_em",
    "motivo_suspensao",
    "renovacao_em",
    "assinatura_ativa",
    "stripe_subscription_id",
    "stripe_customer_id",
    "plano",
    "status",
]


def upgrade() -> None:
    for coluna in _UPGRADE:
        op.add_column("tenants", coluna)

    op.create_index("ix_tenants_status", "tenants", ["status"])
    op.create_index("ix_tenants_stripe_customer_id", "tenants", ["stripe_customer_id"])
    op.create_index("ix_tenants_stripe_subscription_id", "tenants", ["stripe_subscription_id"])

    op.create_table(
        "pagamentos",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("stripe_event_id", sa.String(), nullable=True),
        sa.Column("tipo", sa.String(), nullable=True, server_default=""),
        sa.Column("status", sa.String(), nullable=True, server_default=""),
        sa.Column("valor_centavos", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("moeda", sa.String(), nullable=True, server_default="BRL"),
        sa.Column("descricao", sa.String(), nullable=True, server_default=""),
        sa.Column("criado_em", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_pagamentos_tenant_id", "pagamentos", ["tenant_id"])
    op.create_index("ix_pagamentos_criado_em", "pagamentos", ["criado_em"])
    # Único, e não apenas indexado: é o que impede a mesma cobrança de ser
    # contabilizada duas vezes quando o Stripe reenvia o webhook.
    op.create_index("uq_pagamentos_stripe_event_id", "pagamentos", ["stripe_event_id"], unique=True)

    op.create_table(
        "admin_usuarios",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("nome", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("senha_hash", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("criado_em", sa.DateTime(), nullable=True),
        sa.Column("ultimo_acesso_em", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_admin_usuarios_email", "admin_usuarios", ["email"], unique=True)
    op.create_index("ix_admin_usuarios_token_hash", "admin_usuarios", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_admin_usuarios_token_hash", table_name="admin_usuarios")
    op.drop_index("ix_admin_usuarios_email", table_name="admin_usuarios")
    op.drop_table("admin_usuarios")

    op.drop_index("uq_pagamentos_stripe_event_id", table_name="pagamentos")
    op.drop_index("ix_pagamentos_criado_em", table_name="pagamentos")
    op.drop_index("ix_pagamentos_tenant_id", table_name="pagamentos")
    op.drop_table("pagamentos")

    op.drop_index("ix_tenants_stripe_subscription_id", table_name="tenants")
    op.drop_index("ix_tenants_stripe_customer_id", table_name="tenants")
    op.drop_index("ix_tenants_status", table_name="tenants")

    for coluna in _DOWNGRADE:
        op.drop_column("tenants", coluna)