"""Add demo_seeded to users

Revision ID: i9j0k1l2m3n4
Revises: h8b9c0d1e2f3
Create Date: 2026-04-06

"""
from alembic import op
import sqlalchemy as sa


revision = 'i9j0k1l2m3n4'
down_revision = 'h8b9c0d1e2f3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('demo_seeded', sa.Boolean(),
                                     nullable=False, server_default='false'))


def downgrade():
    op.drop_column('users', 'demo_seeded')
