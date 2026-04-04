"""add sf gate to tracks and data_source to sessions

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-04

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tracks', sa.Column('sf_lat1', sa.Float(), nullable=True))
    op.add_column('tracks', sa.Column('sf_lon1', sa.Float(), nullable=True))
    op.add_column('tracks', sa.Column('sf_lat2', sa.Float(), nullable=True))
    op.add_column('tracks', sa.Column('sf_lon2', sa.Float(), nullable=True))
    op.add_column('sessions', sa.Column(
        'data_source', sa.String(length=20), nullable=True,
        server_default='racechrono',
    ))


def downgrade():
    op.drop_column('sessions', 'data_source')
    op.drop_column('tracks', 'sf_lon2')
    op.drop_column('tracks', 'sf_lat2')
    op.drop_column('tracks', 'sf_lon1')
    op.drop_column('tracks', 'sf_lat1')
