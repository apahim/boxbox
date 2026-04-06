"""Add video_filename to sessions

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-04-06

"""
from alembic import op
import sqlalchemy as sa


revision = 'j0k1l2m3n4o5'
down_revision = 'i9j0k1l2m3n4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sessions', sa.Column('video_filename', sa.String(length=255),
                                         nullable=True))


def downgrade():
    op.drop_column('sessions', 'video_filename')
