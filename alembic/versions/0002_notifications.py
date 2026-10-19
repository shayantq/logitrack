"""add notifications table

Revision ID: 0002_notifications
Revises: 0001_baseline
Create Date: 2026-08-09

جدول اعلان‌های موجودی رو‌به‌اتمام — برای بررسی خودکار دوره‌ای (Celery Beat)
که بدون نیاز به باز کردن دستی صفحه انبار، هشدار کم‌شدن موجودی را ثبت می‌کند.
"""
from alembic import op
import sqlalchemy as sa

revision = '0002_notifications'
down_revision = '0001_baseline'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=True),
        sa.Column('message', sa.String(), nullable=False),
        sa.Column('is_read', sa.Boolean(), server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_table('notifications')
