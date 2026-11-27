"""Reference-lap Track DNA cards; drop configs and old scorecards

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-11-27 21:00:00.000000

Track DNA simplification (owner-approved 2026-11-27): one track = one
layout, one admin-selected reference lap per track, no conditions and
no configurations. Adds tracks.reference_* columns and the new
track_dna_cards table; drops track_configs, track_dna_scorecards and
sessions.track_config_id. Existing scorecards are NOT migrated — they
are recomputed from the reference lap via the admin UI.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 's9t0u1v2w3x4'
down_revision = 'r8s9t0u1v2w3'
branch_labels = None
depends_on = None


def upgrade():
    # Additive: reference lap on tracks, new card table
    op.add_column('tracks',
                  sa.Column('reference_session_id', sa.Integer(),
                            nullable=True))
    op.add_column('tracks',
                  sa.Column('reference_lap_number', sa.Integer(),
                            nullable=True))
    op.create_foreign_key(
        'fk_tracks_reference_session', 'tracks', 'sessions',
        ['reference_session_id'], ['id'], ondelete='SET NULL')

    op.create_table('track_dna_cards',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer(), nullable=False),
        sa.Column('methodology_version', sa.String(length=10),
                  nullable=False),
        sa.Column('params_json', sa.JSON(), nullable=False),
        sa.Column('dimensions_json', sa.JSON(), nullable=False),
        sa.Column('overall_score', sa.Float(), nullable=True),
        sa.Column('dataset_json', sa.JSON(), nullable=False),
        sa.Column('support_json', sa.JSON(), nullable=False),
        sa.Column('computed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['track_id'], ['tracks.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('track_id', 'methodology_version',
                            name='uq_dna_card_track_version')
    )
    op.create_index('ix_track_dna_cards_track_id', 'track_dna_cards',
                    ['track_id'], unique=False)

    # Destructive: the consensus-era tables go away
    op.drop_column('sessions', 'track_config_id')
    op.drop_table('track_dna_scorecards')
    op.drop_table('track_configs')


def downgrade():
    op.create_table('track_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('direction', sa.String(length=3), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('confirmed', sa.Boolean(), nullable=False,
                  server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['track_id'], ['tracks.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('track_id', 'name',
                            name='uq_track_config_name')
    )
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
    op.add_column('sessions',
                  sa.Column('track_config_id', sa.Integer(), nullable=True))
    op.create_index('ix_sessions_track_config_id', 'sessions',
                    ['track_config_id'], unique=False)

    op.drop_index('ix_track_dna_cards_track_id', table_name='track_dna_cards')
    op.drop_table('track_dna_cards')
    op.drop_constraint('fk_tracks_reference_session', 'tracks',
                       type_='foreignkey')
    op.drop_column('tracks', 'reference_lap_number')
    op.drop_column('tracks', 'reference_session_id')
