"""Cache dos preços recorrentes criados sob demanda no Stripe

Permite dispensar a criação manual de produto e preço no painel do Stripe: o
produto passa a ser criado pela API na primeira compra de cada plano, e o
``price_id`` fica guardado aqui para a segunda compra reutilizar.

Sem esta tabela, cada checkout criaria um produto novo — 50 assinantes virariam
50 produtos no painel do Stripe.

O passo 3 da resolução (buscar na Stripe por ``metadata['lembrazap_plano']``)
continua sendo a rede de segurança para o caso de o banco ser recriado: o
sistema reencontra o produto existente em vez de duplicá-lo.

Revision ID: b7e1d4c8f2a6
Revises: 8a4c2f19d3e7
Create Date: 2026-10-05 10:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7e1d4c8f2a6"
down_revision: Union[str, Sequence[str], None] = "8a4c2f19d3e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "planos_stripe",
        sa.Column("chave", sa.String(), primary_key=True),
        sa.Column("product_id", sa.String(), nullable=True, server_default=""),
        sa.Column("price_id", sa.String(), nullable=True, server_default=""),
        sa.Column("preco_centavos", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("criado_em", sa.DateTime(), nullable=True),
        sa.Column("atualizado_em", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_planos_stripe_price_id", "planos_stripe", ["price_id"])


def downgrade() -> None:
    op.drop_index("ix_planos_stripe_price_id", table_name="planos_stripe")
    op.drop_table("planos_stripe")