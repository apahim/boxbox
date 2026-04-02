"""replace corner point with trap line endpoints

Revision ID: a1b2c3d4e5f6
Revises: 38475a16c3d5
Create Date: 2026-04-02 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '38475a16c3d5'
branch_labels = None
depends_on = None


def upgrade():
    # Add trap columns (nullable first for data migration)
    op.add_column('track_corners', sa.Column('trap_lat1', sa.Float(), nullable=True))
    op.add_column('track_corners', sa.Column('trap_lon1', sa.Float(), nullable=True))
    op.add_column('track_corners', sa.Column('trap_lat2', sa.Float(), nullable=True))
    op.add_column('track_corners', sa.Column('trap_lon2', sa.Float(), nullable=True))

    # Migrate existing corner points to trap lines (small offset for initial line)
    op.execute("""
        UPDATE track_corners
        SET trap_lat1 = lat + 0.00005,
            trap_lon1 = lon - 0.00005,
            trap_lat2 = lat - 0.00005,
            trap_lon2 = lon + 0.00005
        WHERE trap_lat1 IS NULL
    """)

    # Make trap columns non-nullable
    op.alter_column('track_corners', 'trap_lat1', nullable=False)
    op.alter_column('track_corners', 'trap_lon1', nullable=False)
    op.alter_column('track_corners', 'trap_lat2', nullable=False)
    op.alter_column('track_corners', 'trap_lon2', nullable=False)

    # Drop old point columns
    op.drop_column('track_corners', 'lat')
    op.drop_column('track_corners', 'lon')


def downgrade():
    # Re-add lat/lon as midpoint of trap line
    op.add_column('track_corners', sa.Column('lat', sa.Float(), nullable=True))
    op.add_column('track_corners', sa.Column('lon', sa.Float(), nullable=True))

    op.execute("""
        UPDATE track_corners
        SET lat = (trap_lat1 + trap_lat2) / 2,
            lon = (trap_lon1 + trap_lon2) / 2
    """)

    op.alter_column('track_corners', 'lat', nullable=False)
    op.alter_column('track_corners', 'lon', nullable=False)

    op.drop_column('track_corners', 'trap_lon2')
    op.drop_column('track_corners', 'trap_lat2')
    op.drop_column('track_corners', 'trap_lon1')
    op.drop_column('track_corners', 'trap_lat1')
