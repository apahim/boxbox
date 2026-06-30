"""Normalize video_hash into separate table

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-06-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'o5p6q7r8s9t0'
down_revision = 'n4o5p6q7r8s9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'session_video_hashes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('hash', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, video_hash FROM sessions WHERE video_hash IS NOT NULL AND video_hash != ''")
    ).fetchall()
    for session_id, video_hash in rows:
        for h in video_hash.split(','):
            h = h.strip()
            if h:
                conn.execute(
                    sa.text("INSERT INTO session_video_hashes (session_id, hash) VALUES (:sid, :h)"),
                    {"sid": session_id, "h": h},
                )

    op.drop_column('sessions', 'video_hash')


def downgrade():
    op.add_column('sessions', sa.Column('video_hash', sa.String(length=255), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT DISTINCT session_id FROM session_video_hashes")
    ).fetchall()
    for (session_id,) in rows:
        hashes = conn.execute(
            sa.text("SELECT hash FROM session_video_hashes WHERE session_id = :sid ORDER BY id"),
            {"sid": session_id},
        ).fetchall()
        joined = ','.join(h for (h,) in hashes)
        conn.execute(
            sa.text("UPDATE sessions SET video_hash = :vh WHERE id = :sid"),
            {"vh": joined, "sid": session_id},
        )

    op.drop_table('session_video_hashes')
