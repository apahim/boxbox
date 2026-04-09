"""Widen video_hash for multi-file GoPro sessions

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-04-09

"""
from alembic import op
import sqlalchemy as sa


revision = 'l2m3n4o5p6q7'
down_revision = 'k1l2m3n4o5p6'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('sessions', 'video_hash',
                    type_=sa.String(length=255),
                    existing_type=sa.String(length=64))


def downgrade():
    op.alter_column('sessions', 'video_hash',
                    type_=sa.String(length=64),
                    existing_type=sa.String(length=255))
