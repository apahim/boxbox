"""Replace password auth with Google OAuth

Revision ID: 8eb728c81585
Revises: f6a7b8c9d0e1
Create Date: 2026-04-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8eb728c81585'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('google_id', sa.String(255), nullable=True))
    op.create_unique_constraint('uq_users_google_id', 'users', ['google_id'])
    op.drop_column('users', 'password_hash')


def downgrade():
    op.add_column('users', sa.Column('password_hash', sa.LargeBinary(), nullable=True))
    op.drop_constraint('uq_users_google_id', 'users', type_='unique')
    op.drop_column('users', 'google_id')
