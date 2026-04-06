"""Add terms_accepted_at to users

Revision ID: h8b9c0d1e2f3
Revises: g7a8b9c0d1e2
Create Date: 2026-04-05

"""
from alembic import op
import sqlalchemy as sa


revision = 'h8b9c0d1e2f3'
down_revision = 'g7a8b9c0d1e2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('terms_accepted_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('users', 'terms_accepted_at')
