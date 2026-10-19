"""safe deletes + warehouse scope for orders/notifications

Revision ID: 0003_safe_deletes
Revises: 0002_notifications
Create Date: 2026-10-10

۱. کلیدهای خارجی vehicles.driver_id و orders.vehicle_id دیگر CASCADE نیستند
   (SET NULL شده‌اند): قبلاً حذف یک راننده، خودروهایش و سپس تمام سفارش‌های
   آن خودروها را هم پاک می‌کرد.
۲. ستون orders.warehouse_id: انباری که موجودی سفارش از آن کم شده، تا هنگام
   حذف/ناموفق شدن سفارش، موجودی به همان انبار برگردد.
۳. ستون notifications.warehouse_id: اعلان‌های موجودی به تفکیک انبار.
"""
from alembic import op
import sqlalchemy as sa

revision = '0003_safe_deletes'
down_revision = '0002_notifications'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # نام‌های پیش‌فرض PostgreSQL برای FKهایی که در 0001 بدون نام ساخته شدند
    op.drop_constraint('vehicles_driver_id_fkey', 'vehicles', type_='foreignkey')
    op.create_foreign_key('vehicles_driver_id_fkey', 'vehicles', 'users', ['driver_id'], ['id'], ondelete='SET NULL')

    op.drop_constraint('orders_vehicle_id_fkey', 'orders', type_='foreignkey')
    op.create_foreign_key('orders_vehicle_id_fkey', 'orders', 'vehicles', ['vehicle_id'], ['id'], ondelete='SET NULL')

    op.add_column('orders', sa.Column('warehouse_id', sa.Integer(), nullable=True))
    op.create_foreign_key('orders_warehouse_id_fkey', 'orders', 'warehouses', ['warehouse_id'], ['id'], ondelete='SET NULL')

    op.add_column('notifications', sa.Column('warehouse_id', sa.Integer(), nullable=True))
    op.create_foreign_key('notifications_warehouse_id_fkey', 'notifications', 'warehouses', ['warehouse_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    op.drop_constraint('notifications_warehouse_id_fkey', 'notifications', type_='foreignkey')
    op.drop_column('notifications', 'warehouse_id')

    op.drop_constraint('orders_warehouse_id_fkey', 'orders', type_='foreignkey')
    op.drop_column('orders', 'warehouse_id')

    op.drop_constraint('orders_vehicle_id_fkey', 'orders', type_='foreignkey')
    op.create_foreign_key('orders_vehicle_id_fkey', 'orders', 'vehicles', ['vehicle_id'], ['id'], ondelete='CASCADE')

    op.drop_constraint('vehicles_driver_id_fkey', 'vehicles', type_='foreignkey')
    op.create_foreign_key('vehicles_driver_id_fkey', 'vehicles', 'users', ['driver_id'], ['id'], ondelete='CASCADE')
