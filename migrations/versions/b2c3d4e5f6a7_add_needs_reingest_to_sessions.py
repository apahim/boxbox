"""add needs_reingest to sessions

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-02

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sessions', sa.Column(
        'needs_reingest', sa.Boolean(), nullable=False,
        server_default=sa.text('false'),
    ))


def downgrade():
    op.drop_column('sessions', 'needs_reingest')
