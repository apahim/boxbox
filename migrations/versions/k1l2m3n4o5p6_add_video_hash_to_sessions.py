"""Add video_hash to sessions

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-04-06

"""
from alembic import op
import sqlalchemy as sa


revision = 'k1l2m3n4o5p6'
down_revision = 'j0k1l2m3n4o5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sessions', sa.Column('video_hash', sa.String(length=64),
                                         nullable=True))


def downgrade():
    op.drop_column('sessions', 'video_hash')
