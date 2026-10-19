"""rich notifications: kind/title/severity/link/details/audience + per-user read & dismiss receipts; inventories.low_alerted

Revision ID: 0022_rich_notifications
Revises: 0021_replenishment_tours
Create Date: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa

revision = '0022_rich_notifications'
down_revision = '0021_replenishment_tours'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('notifications', sa.Column('kind', sa.String(32), nullable=False, server_default='low_stock'))
    op.add_column('notifications', sa.Column('severity', sa.String(16), nullable=False, server_default='warning'))
    op.add_column('notifications', sa.Column('title', sa.String(160), nullable=True))
    op.add_column('notifications', sa.Column('link', sa.String(255), nullable=True))
    op.add_column('notifications', sa.Column('details', sa.JSON(), nullable=True))
    op.add_column('notifications', sa.Column('audience', sa.String(8), nullable=False, server_default='staff'))
    op.add_column('notifications', sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True))
    op.add_column('notifications', sa.Column('dedupe_key', sa.String(120), nullable=True))
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])
    op.create_index('ix_notifications_dedupe_key', 'notifications', ['dedupe_key'])
    op.create_index('ix_notifications_created_at', 'notifications', ['created_at'])
    # اعلان‌های قدیمی موجودی: تمام‌شده‌ها قرمز، بقیه هشدار؛ مسیر صفحه کالا
    op.execute("UPDATE notifications SET kind = 'out_of_stock', severity = 'danger', title = 'موجودی کالا تمام شد' "
               "WHERE message LIKE '%تمام شده%'")
    op.execute("UPDATE notifications SET title = 'کالا به نقطه سفارش رسید' WHERE title IS NULL")
    op.execute("UPDATE notifications SET link = '/app/inventory?product=' || product_id WHERE product_id IS NOT NULL")

    op.create_table(
        'notification_receipts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('notification_id', sa.Integer(), sa.ForeignKey('notifications.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('dismissed_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('notification_id', 'user_id', name='uq_notification_receipt'),
    )
    # اعلانی که قبلاً (به‌صورت مشترک) خوانده شده بود، برای همه کارکنان همان سازمان خوانده‌شده می‌ماند
    op.execute("""
        INSERT INTO notification_receipts (organization_id, notification_id, user_id, read_at)
        SELECT n.organization_id, n.id, u.id, now()
        FROM notifications n JOIN users u ON u.organization_id = n.organization_id
        WHERE n.is_read IS TRUE AND u.role IN ('org_admin', 'warehouse_manager')
    """)
    op.drop_column('notifications', 'is_read')

    op.add_column('inventories', sa.Column('low_alerted', sa.Boolean(), nullable=False, server_default=sa.false()))
    # ردیف‌هایی که الان زیر نقطه سفارش‌اند هشدارشان را گرفته‌اند (یا از اول کم بوده‌اند) — دوباره اعلان نمی‌گیرند
    op.execute("UPDATE inventories SET low_alerted = TRUE WHERE quantity <= COALESCE(reorder_point, 10)")


def downgrade():
    op.drop_column('inventories', 'low_alerted')
    op.add_column('notifications', sa.Column('is_read', sa.Boolean(), server_default=sa.false()))
    op.drop_table('notification_receipts')
    op.drop_index('ix_notifications_created_at', 'notifications')
    op.drop_index('ix_notifications_dedupe_key', 'notifications')
    op.drop_index('ix_notifications_user_id', 'notifications')
    for column in ('dedupe_key', 'user_id', 'audience', 'details', 'link', 'title', 'severity', 'kind'):
        op.drop_column('notifications', column)
