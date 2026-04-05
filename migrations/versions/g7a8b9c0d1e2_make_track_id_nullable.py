"""Make track_id nullable on sessions

Revision ID: g7a8b9c0d1e2
Revises: a1b2c3d4e5f7
Create Date: 2026-04-05

"""
from alembic import op
import sqlalchemy as sa


revision = 'g7a8b9c0d1e2'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('sessions') as batch_op:
        batch_op.alter_column('track_id', existing_type=sa.Integer(), nullable=True)


def downgrade():
    with op.batch_alter_table('sessions') as batch_op:
        batch_op.alter_column('track_id', existing_type=sa.Integer(), nullable=False)
