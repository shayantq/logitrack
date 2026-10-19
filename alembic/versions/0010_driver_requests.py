"""driver portal: leave and vehicle-change requests

Revision ID: 0010_driver_requests
Revises: 0009_driver_scheduling
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa

revision = '0010_driver_requests'
down_revision = '0009_driver_scheduling'
branch_labels = None
depends_on = None


def _org_column():
    return sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                     nullable=False, index=True)


def upgrade():
    op.create_table(
        'driver_requests',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org_column(),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('kind', sa.String(16), nullable=False, index=True),
        sa.Column('status', sa.String(16), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('leave_type', sa.String(16), nullable=True),
        sa.Column('category', sa.String(32), nullable=True),
        sa.Column('starts_at', sa.DateTime(), nullable=True),
        sa.Column('ends_at', sa.DateTime(), nullable=True),
        sa.Column('reason', sa.String(500), nullable=True),
        sa.Column('time_off_id', sa.Integer(), sa.ForeignKey('driver_time_off.id', ondelete='SET NULL'), nullable=True),
        sa.Column('vehicle_data', sa.JSON(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('review_note', sa.String(500), nullable=True),
    )
    op.create_table(
        'driver_request_documents',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org_column(),
        sa.Column('request_id', sa.Integer(), sa.ForeignKey('driver_requests.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('file_path', sa.String(255), nullable=False),
        sa.Column('content_type', sa.String(64), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('request_id', 'kind', name='uq_driver_request_documents_kind'),
    )


def downgrade():
    op.drop_table('driver_request_documents')
    op.drop_table('driver_requests')
