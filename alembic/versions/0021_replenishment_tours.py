"""replenishment: reorder-point formula fields per inventory + org inventory policy; users.tour_state (onboarding tours)

Revision ID: 0021_replenishment_tours
Revises: 0020_users_audit
Create Date: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa

revision = '0021_replenishment_tours'
down_revision = '0020_users_audit'
branch_labels = None
depends_on = None


def upgrade():
    # نقطه سفارش: حالت دستی (همان عدد قبلی) یا خودکار از فرمول؛ پارامترهای خالی = پیش‌فرض سازمان
    op.add_column('inventories', sa.Column('rop_mode', sa.String(8), nullable=False, server_default='manual'))
    op.add_column('inventories', sa.Column('lead_time_days', sa.Float(), nullable=True))
    op.add_column('inventories', sa.Column('lead_time_std_days', sa.Float(), nullable=True))
    op.add_column('inventories', sa.Column('service_level', sa.Float(), nullable=True))
    # آخرین محاسبه (برای نمایش و گزارش؛ با هر محاسبه دوباره نوشته می‌شود)
    op.add_column('inventories', sa.Column('avg_daily_demand', sa.Float(), nullable=True))
    op.add_column('inventories', sa.Column('demand_std', sa.Float(), nullable=True))
    op.add_column('inventories', sa.Column('safety_stock', sa.Integer(), nullable=True))
    op.add_column('inventories', sa.Column('suggested_order_qty', sa.Integer(), nullable=True))
    op.add_column('inventories', sa.Column('rop_calculated_at', sa.DateTime(), nullable=True))
    op.create_check_constraint('ck_inventories_rop_mode', 'inventories', "rop_mode IN ('manual', 'auto')")
    op.create_check_constraint('ck_inventories_service_level', 'inventories',
                               'service_level IS NULL OR (service_level >= 0.5 AND service_level < 1)')
    op.create_check_constraint('ck_inventories_lead_time', 'inventories',
                               'lead_time_days IS NULL OR lead_time_days >= 0')

    op.add_column('organizations', sa.Column('inventory_policy', sa.JSON(), nullable=True))
    # راهنمای تعاملی: کدام راهنماها دیده/رد شده‌اند ({"main": "done", "inventory": "skipped", ...})
    op.add_column('users', sa.Column('tour_state', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('users', 'tour_state')
    op.drop_column('organizations', 'inventory_policy')
    op.drop_constraint('ck_inventories_lead_time', 'inventories', type_='check')
    op.drop_constraint('ck_inventories_service_level', 'inventories', type_='check')
    op.drop_constraint('ck_inventories_rop_mode', 'inventories', type_='check')
    for column in ('rop_calculated_at', 'suggested_order_qty', 'safety_stock', 'demand_std', 'avg_daily_demand',
                   'service_level', 'lead_time_std_days', 'lead_time_days', 'rop_mode'):
        op.drop_column('inventories', column)
