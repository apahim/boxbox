"""Add track_dna_scorecards table

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-11-26 21:00:00.000000

Track DNA Phase 7: scorecard storage. One row per (track_config_id,
condition, methodology_version); recomputation upserts. No hooks write
here (D7 revised) — the CLI now, the admin-page trigger in Phase 9.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'r8s9t0u1v2w3'
down_revision = 'q7r8s9t0u1v2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('track_dna_scorecards',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('track_config_id', sa.Integer(), nullable=False),
        sa.Column('methodology_version', sa.String(length=10),
                  nullable=False),
        sa.Column('condition', sa.String(length=4), nullable=False),
        sa.Column('params_json', sa.JSON(), nullable=False),
        sa.Column('dimensions_json', sa.JSON(), nullable=False),
        sa.Column('overall_score', sa.Float(), nullable=True),
        sa.Column('dataset_json', sa.JSON(), nullable=False),
        sa.Column('support_json', sa.JSON(), nullable=False),
        sa.Column('computed_at', sa.DateTime(), nullable=True),
        sa.Column('stale', sa.Boolean(), nullable=False,
                  server_default='false'),
        sa.ForeignKeyConstraint(['track_config_id'], ['track_configs.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('track_config_id', 'condition',
                            'methodology_version',
                            name='uq_scorecard_config_condition_version')
    )
    op.create_index('ix_track_dna_scorecards_track_config_id',
                    'track_dna_scorecards', ['track_config_id'],
                    unique=False)


def downgrade():
    op.drop_index('ix_track_dna_scorecards_track_config_id',
                  table_name='track_dna_scorecards')
    op.drop_table('track_dna_scorecards')
