"""organization brand colour for branded Excel/PDF reports

Revision ID: 0019_brand_color
Revises: 0018_catalog
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa

revision = '0019_brand_color'
down_revision = '0018_catalog'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('organizations', sa.Column('brand_color', sa.String(9), nullable=True))


def downgrade():
    op.drop_column('organizations', 'brand_color')
