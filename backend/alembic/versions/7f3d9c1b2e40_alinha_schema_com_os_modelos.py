"""Alinha o schema do banco com os modelos SQLAlchemy

Faltavam três colunas que o código já usa em produção: ``agenda.servico``
(exibido no painel e no texto da mensagem), ``agenda.confirmado_em``
(registro do SIM) e ``clientes.ultima_resposta`` (texto bruto da resposta).

Revision ID: 7f3d9c1b2e40
Revises: 0b5bbedbd982
Create Date: 2026-10-04 13:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f3d9c1b2e40'
down_revision: Union[str, Sequence[str], None] = '0b5bbedbd982'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agenda', sa.Column('servico', sa.String(), nullable=True))
    op.add_column('agenda', sa.Column('confirmado_em', sa.DateTime(), nullable=True))
    op.add_column('clientes', sa.Column('ultima_resposta', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('clientes', 'ultima_resposta')
    op.drop_column('agenda', 'confirmado_em')
    op.drop_column('agenda', 'servico')