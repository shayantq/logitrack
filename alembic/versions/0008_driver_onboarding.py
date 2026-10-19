"""driver onboarding: invites, KYC profiles and documents, users.driver_status

Revision ID: 0008_driver_onboarding
Revises: 0007_order_redesign
Create Date: 2026-10-11

۱. ستون users.driver_status — رانندگان فعلی «approved» می‌مانند تا کارشان قطع نشود.
۲. جدول driver_invites (لینک/کد دعوت سازمان برای ثبت‌نام راننده).
۳. جدول driver_profiles (مشخصات فردی، سکونت، وسیله، نتیجه بررسی).
۴. جدول driver_documents (فایل مدارک — مسیر در MEDIA_ROOT).
"""
from alembic import op
import sqlalchemy as sa

revision = '0008_driver_onboarding'
down_revision = '0007_order_redesign'
branch_labels = None
depends_on = None

DRIVER_STATUSES = ("incomplete", "submitted", "approved", "rejected")


def _org_column():
    return sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                     nullable=False, index=True)


def upgrade():
    op.add_column('users', sa.Column('driver_status', sa.String(16), nullable=False, server_default='approved'))
    op.create_check_constraint(
        'ck_users_driver_status', 'users',
        "driver_status IN (" + ", ".join(f"'{s}'" for s in DRIVER_STATUSES) + ")",
    )

    op.create_table(
        'driver_invites',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org_column(),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('code', sa.String(16), nullable=False, unique=True, index=True),
        sa.Column('label', sa.String(100), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('max_uses', sa.Integer(), nullable=True),
        sa.Column('uses', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        'driver_profiles',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org_column(),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True, index=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('invite_id', sa.Integer(), sa.ForeignKey('driver_invites.id', ondelete='SET NULL'), nullable=True),
        sa.Column('first_name', sa.String(64), nullable=True),
        sa.Column('last_name', sa.String(64), nullable=True),
        sa.Column('national_code', sa.String(10), nullable=True),
        sa.Column('birth_date', sa.Date(), nullable=True),
        sa.Column('mobile', sa.String(11), nullable=True),
        sa.Column('province', sa.String(64), nullable=True),
        sa.Column('city', sa.String(64), nullable=True),
        sa.Column('address', sa.String(500), nullable=True),
        sa.Column('postal_code', sa.String(10), nullable=True),
        sa.Column('vehicle_type', sa.String(16), nullable=True),
        sa.Column('vehicle_model', sa.String(64), nullable=True),
        sa.Column('vehicle_color', sa.String(32), nullable=True),
        sa.Column('license_plate', sa.String(15), nullable=True),
        sa.Column('max_weight_kg', sa.Integer(), nullable=True),
        sa.Column('intercity', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('inspection_expiry', sa.Date(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('rejection_reason', sa.String(500), nullable=True),
        sa.Column('vehicle_id', sa.Integer(), sa.ForeignKey('vehicles.id', ondelete='SET NULL'), nullable=True),
    )

    op.create_table(
        'driver_documents',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org_column(),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('file_path', sa.String(255), nullable=False),
        sa.Column('content_type', sa.String(64), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('user_id', 'kind', name='uq_driver_documents_user_kind'),
    )


def downgrade():
    op.drop_table('driver_documents')
    op.drop_table('driver_profiles')
    op.drop_table('driver_invites')
    op.drop_constraint('ck_users_driver_status', 'users', type_='check')
    op.drop_column('users', 'driver_status')
