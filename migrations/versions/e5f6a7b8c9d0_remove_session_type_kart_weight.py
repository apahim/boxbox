"""remove session_type, kart_number, driver_weight_kg from sessions

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-04

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('sessions', 'session_type')
    op.drop_column('sessions', 'kart_number')
    op.drop_column('sessions', 'driver_weight_kg')


def downgrade():
    op.add_column('sessions', sa.Column('driver_weight_kg', sa.Float(), nullable=True))
    op.add_column('sessions', sa.Column('kart_number', sa.Integer(), nullable=True))
    op.add_column('sessions', sa.Column('session_type', sa.String(length=100), nullable=True))
