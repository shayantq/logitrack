"""organization onboarding: profile fields, logo, public organization requests

Revision ID: 0005_org_onboarding
Revises: 0004_multi_tenancy
Create Date: 2026-10-10

۱. فیلدهای پروفایل هویتی/تجاری و لوگو به جدول organizations اضافه می‌شوند.
۲. جدول organization_requests برای درخواست‌های عمومی لندینگ پیج (قبل از
   تأیید توسط ادمین پلتفرم) ساخته می‌شود.
"""
from alembic import op
import sqlalchemy as sa

revision = '0005_org_onboarding'
down_revision = '0004_multi_tenancy'
branch_labels = None
depends_on = None


def _profile_columns() -> list[sa.Column]:
    """همان فیلدهای OrganizationProfileMixin در app/models.py"""
    return [
        sa.Column('legal_name', sa.String(200), nullable=True),
        sa.Column('business_type', sa.String(32), nullable=True),
        sa.Column('national_id', sa.String(11), nullable=True),
        sa.Column('economic_code', sa.String(14), nullable=True),
        sa.Column('registration_number', sa.String(32), nullable=True),
        sa.Column('province', sa.String(64), nullable=True),
        sa.Column('city', sa.String(64), nullable=True),
        sa.Column('address', sa.String(500), nullable=True),
        sa.Column('postal_code', sa.String(10), nullable=True),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('website', sa.String(200), nullable=True),
        sa.Column('employee_count', sa.String(16), nullable=True),
        sa.Column('monthly_order_volume', sa.String(16), nullable=True),
        sa.Column('warehouse_count', sa.Integer(), nullable=True),
        sa.Column('fleet_size', sa.Integer(), nullable=True),
        sa.Column('contact_name', sa.String(100), nullable=True),
        sa.Column('contact_mobile', sa.String(11), nullable=True),
        sa.Column('contact_email', sa.String(254), nullable=True),
    ]


def upgrade() -> None:
    for column in _profile_columns():
        op.add_column('organizations', column)
    op.add_column('organizations', sa.Column('updated_at', sa.DateTime(), nullable=True))
    op.add_column('organizations', sa.Column('logo_path', sa.String(255), nullable=True))

    op.create_table(
        'organization_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('tracking_code', sa.String(16), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('requested_features', sa.JSON(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('requester_ip', sa.String(45), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True),
        *_profile_columns(),
    )
    op.create_index('ix_organization_requests_id', 'organization_requests', ['id'])
    op.create_index('ix_organization_requests_tracking_code', 'organization_requests', ['tracking_code'], unique=True)
    op.create_index('ix_organization_requests_status', 'organization_requests', ['status'])


def downgrade() -> None:
    op.drop_index('ix_organization_requests_status', table_name='organization_requests')
    op.drop_index('ix_organization_requests_tracking_code', table_name='organization_requests')
    op.drop_index('ix_organization_requests_id', table_name='organization_requests')
    op.drop_table('organization_requests')

    op.drop_column('organizations', 'logo_path')
    op.drop_column('organizations', 'updated_at')
    for column in reversed(_profile_columns()):
        op.drop_column('organizations', column.name)
