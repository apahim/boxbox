"""add share_token_created_at to sessions

Revision ID: a1b2c3d4e5f7
Revises: 8eb728c81585
Create Date: 2026-04-05

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f7'
down_revision = '8eb728c81585'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sessions', sa.Column('share_token_created_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('sessions', 'share_token_created_at')
