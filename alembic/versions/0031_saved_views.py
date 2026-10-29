"""نماهای ذخیره‌شده فهرست‌ها (فیلترهای صفحه، برای خود کاربر یا مشترک با یک نقش)

Revision ID: 0031_saved_views
Revises: 0030_user_totp
"""
import sqlalchemy as sa
from alembic import op

revision = '0031_saved_views'
down_revision = '0030_user_totp'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'saved_views',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('page_key', sa.String(16), nullable=False),
        sa.Column('name', sa.String(60), nullable=False),
        sa.Column('filters', sa.JSON(), nullable=False),
        sa.Column('shared_role', sa.String(32), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('owner_id', 'page_key', 'name', name='uq_saved_views_owner_page_name'),
        sa.CheckConstraint("page_key IN ('orders', 'receipts', 'inventory', 'transfers', 'tickets')", name='ck_saved_views_page'),
        sa.CheckConstraint("shared_role IS NULL OR shared_role IN ('org_admin', 'warehouse_manager')", name='ck_saved_views_role'),
    )


def downgrade() -> None:
    op.drop_table('saved_views')
