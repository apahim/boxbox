"""add share_token to sessions, drop teams and team_members tables

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-05

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sessions', sa.Column('share_token', sa.String(32), nullable=True))
    op.create_index('ix_sessions_share_token', 'sessions', ['share_token'], unique=True)

    op.drop_constraint('sessions_team_id_fkey', 'sessions', type_='foreignkey')
    op.drop_column('sessions', 'team_id')

    op.drop_table('team_members')
    op.drop_table('teams')


def downgrade():
    op.create_table('teams',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('slug', sa.String(100), unique=True, nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime()),
    )
    op.create_table('team_members',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('teams.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('role', sa.String(20), nullable=False, server_default='member'),
        sa.Column('joined_at', sa.DateTime()),
        sa.UniqueConstraint('team_id', 'user_id', name='uq_team_user'),
    )

    op.add_column('sessions', sa.Column('team_id', sa.Integer(), nullable=True))
    op.create_foreign_key('sessions_team_id_fkey', 'sessions', 'teams', ['team_id'], ['id'])

    op.drop_index('ix_sessions_share_token', 'sessions')
    op.drop_column('sessions', 'share_token')
