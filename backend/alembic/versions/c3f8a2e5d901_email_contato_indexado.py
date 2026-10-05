"""E-mail do titular vira coluna própria em `tenants`.

Motivo: a assinatura self-service identifica a conta pelo e-mail. A pessoa clica
em "Assinar", digita o e-mail e vai para o Stripe — sem token nenhum. Guardar o
e-mail dentro do `config` (JSON) obrigaria a varrer a tabela a cada tentativa de
compra, e a conta pendente precisa ser reencontrada para não duplicar.

A migração copia o que já existia no `config` para a coluna nova, então as contas
existentes continuam com o e-mail consultável por índice.

Revisão: down remove a coluna. O dado não se perde de vez — continua em `config`,
de onde foi copiado.
"""

from alembic import op
import sqlalchemy as sa

revision = "c3f8a2e5d901"
down_revision = "b7e1d4c8f2a6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tenants",
        sa.Column("email_contato", sa.String(), nullable=True),
    )

    # Copia o e-mail de dentro do JSON para a coluna indexada.
    op.execute(
        """
        UPDATE tenants
           SET email_contato = lower(trim(config->>'email_contato'))
         WHERE config->>'email_contato' IS NOT NULL
           AND trim(config->>'email_contato') <> ''
        """
    )

    op.execute(
        "UPDATE tenants SET email_contato = '' "
        "WHERE email_contato IS NULL"
    )
    op.alter_column("tenants", "email_contato", nullable=False)
    op.create_index("ix_tenants_email_contato", "tenants", ["email_contato"])


def downgrade():
    op.drop_index("ix_tenants_email_contato", table_name="tenants")
    op.drop_column("tenants", "email_contato")