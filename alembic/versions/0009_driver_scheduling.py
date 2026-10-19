"""driver scheduling: weekly shifts, time off, employment type, daily cap

Revision ID: 0009_driver_scheduling
Revises: 0008_driver_onboarding
Create Date: 2026-10-11

۱. driver_profiles: employment_type (تمام‌وقت/پاره‌وقت) و max_daily_orders.
۲. جدول driver_shifts (شیفت هفتگی به وقت ایران) و driver_time_off (مرخصی).
۳. از این مرحله در دسترس بودن خودرو از روی بازه زمانی سفارش‌ها حساب می‌شود و
   وضعیت «busy» دیگر تنظیم نمی‌شود؛ خودروهای «busy» فعلی «available» می‌شوند.
"""
from alembic import op
import sqlalchemy as sa

revision = '0009_driver_scheduling'
down_revision = '0008_driver_onboarding'
branch_labels = None
depends_on = None


def _org_column():
    return sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                     nullable=False, index=True)


def upgrade():
    op.add_column('driver_profiles', sa.Column('employment_type', sa.String(16), nullable=False, server_default='full_time'))
    op.add_column('driver_profiles', sa.Column('max_daily_orders', sa.Integer(), nullable=True))

    op.create_table(
        'driver_shifts',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org_column(),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('weekday', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.CheckConstraint('weekday BETWEEN 0 AND 6', name='ck_driver_shifts_weekday'),
        sa.CheckConstraint('start_time < end_time', name='ck_driver_shifts_order'),
    )
    op.create_table(
        'driver_time_off',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org_column(),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('starts_at', sa.DateTime(), nullable=False, index=True),
        sa.Column('ends_at', sa.DateTime(), nullable=False, index=True),
        sa.Column('reason', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.CheckConstraint('starts_at < ends_at', name='ck_driver_time_off_order'),
    )
    op.execute("UPDATE vehicles SET status = 'available' WHERE status = 'busy'")


def downgrade():
    op.drop_table('driver_time_off')
    op.drop_table('driver_shifts')
    op.drop_column('driver_profiles', 'max_daily_orders')
    op.drop_column('driver_profiles', 'employment_type')
