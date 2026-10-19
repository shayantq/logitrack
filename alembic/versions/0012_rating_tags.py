"""rating tags (separate from the free-text comment)

Revision ID: 0012_rating_tags
Revises: 0011_driver_performance
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa

revision = '0012_rating_tags'
down_revision = '0011_driver_performance'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('driver_ratings', sa.Column('tags', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('driver_ratings', 'tags')
