"""Add is_admin to users

Revision ID: d125d5d1489a
Revises: dbf58c8a5e36
Create Date: 2026-04-18 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd125d5d1489a'
down_revision = 'dbf58c8a5e36'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('is_admin', sa.Boolean(),
                                     nullable=False, server_default='false'))


def downgrade():
    op.drop_column('users', 'is_admin')
