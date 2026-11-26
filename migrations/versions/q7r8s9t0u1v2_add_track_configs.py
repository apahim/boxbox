"""Add track_configs table and sessions.track_config_id

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-11-26 12:00:00.000000

Track DNA Phase 2: configuration identification. ``track_configs`` stores
admin-confirmed track layouts; ``sessions.track_config_id`` links each
session to the layout it was driven on (nullable — most sessions are
unassigned until an admin acts).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'q7r8s9t0u1v2'
down_revision = 'p6q7r8s9t0u1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('track_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('direction', sa.String(length=3), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('confirmed', sa.Boolean(), nullable=False,
                  server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['track_id'], ['tracks.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('track_id', 'name', name='uq_track_config_name')
    )
    op.create_index('ix_track_configs_track_id', 'track_configs', ['track_id'],
                    unique=False)

    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('track_config_id', sa.Integer(),
                                      nullable=True))
        batch_op.create_foreign_key('fk_sessions_track_config',
                                    'track_configs', ['track_config_id'],
                                    ['id'])
        batch_op.create_index('ix_sessions_track_config_id', ['track_config_id'],
                              unique=False)


def downgrade():
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_index('ix_sessions_track_config_id')
        batch_op.drop_constraint('fk_sessions_track_config', type_='foreignkey')
        batch_op.drop_column('track_config_id')

    op.drop_index('ix_track_configs_track_id', table_name='track_configs')
    op.drop_table('track_configs')
