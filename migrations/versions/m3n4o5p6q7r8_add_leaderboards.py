"""Add leaderboards

Revision ID: m3n4o5p6q7r8
Revises: d125d5d1489a
Create Date: 2026-05-11 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'm3n4o5p6q7r8'
down_revision = 'd125d5d1489a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('leaderboards',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('track_id', sa.Integer(), nullable=False),
    sa.Column('labels', sa.JSON(), nullable=True),
    sa.Column('period_type', sa.String(length=20), nullable=False,
              server_default='all_time'),
    sa.Column('period_start', sa.Date(), nullable=True),
    sa.Column('period_end', sa.Date(), nullable=True),
    sa.Column('max_drivers', sa.Integer(), nullable=False, server_default='10'),
    sa.Column('visibility', sa.String(length=20), nullable=False,
              server_default='personal'),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['track_id'], ['tracks.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('leaderboard_shares',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('leaderboard_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('shared_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['leaderboard_id'], ['leaderboards.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('leaderboard_id', 'user_id', name='uq_leaderboard_share')
    )
    with op.batch_alter_table('leaderboard_shares', schema=None) as batch_op:
        batch_op.create_index('ix_leaderboard_share_user', ['user_id'],
                              unique=False)


def downgrade():
    with op.batch_alter_table('leaderboard_shares', schema=None) as batch_op:
        batch_op.drop_index('ix_leaderboard_share_user')

    op.drop_table('leaderboard_shares')
    op.drop_table('leaderboards')
