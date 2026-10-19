"""organization request referral source ("how did you hear about us?")

Revision ID: 0013_request_referral
Revises: 0012_rating_tags
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa

revision = '0013_request_referral'
down_revision = '0012_rating_tags'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('organization_requests', sa.Column('referral_source', sa.String(length=24), nullable=True))
    op.add_column('organization_requests', sa.Column('referral_detail', sa.String(length=200), nullable=True))
    op.create_index('ix_organization_requests_referral_source', 'organization_requests', ['referral_source'])


def downgrade():
    op.drop_index('ix_organization_requests_referral_source', table_name='organization_requests')
    op.drop_column('organization_requests', 'referral_detail')
    op.drop_column('organization_requests', 'referral_source')
