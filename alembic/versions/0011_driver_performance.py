"""driver performance: fares, frozen commission per order, ratings, commission plans

Revision ID: 0011_driver_performance
Revises: 0010_driver_requests
Create Date: 2026-10-11

۱. orders: راننده سفارش، کرایه، زمان تحویل، تسویه منجمد (سطح، چندمین سفر روز، درصد، پورسانت، سهم راننده) و توکن نظرسنجی.
   driver_id سفارش‌های قبلی از راننده خودرو و delivered_at از تاریخچه وضعیت پر می‌شود.
۲. جدول driver_ratings و commission_plans.
"""
from alembic import op
import sqlalchemy as sa

revision = '0011_driver_performance'
down_revision = '0010_driver_requests'
branch_labels = None
depends_on = None


def _order_columns():
    return [
        sa.Column('driver_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('delivery_fee', sa.Float(), nullable=True),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.Column('commission_level', sa.String(32), nullable=True),
        sa.Column('day_trip_number', sa.Integer(), nullable=True),
        sa.Column('commission_percent', sa.Float(), nullable=True),
        sa.Column('commission_amount', sa.Float(), nullable=True),
        sa.Column('driver_earning', sa.Float(), nullable=True),
        sa.Column('rating_token', sa.String(32), nullable=True),
    ]


def _org_column():
    return sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                     nullable=False, index=True)


def upgrade():
    for column in _order_columns():
        op.add_column('orders', column)
    op.create_index('ix_orders_driver_id', 'orders', ['driver_id'])
    op.create_index('ix_orders_delivered_at', 'orders', ['delivered_at'])
    op.create_index('ix_orders_rating_token', 'orders', ['rating_token'], unique=True)
    op.execute("UPDATE orders SET driver_id = v.driver_id FROM vehicles v WHERE orders.vehicle_id = v.id")
    op.execute("""
        UPDATE orders SET delivered_at = h.at FROM (
            SELECT order_id, max(changed_at) AS at FROM order_status_history WHERE to_status = 'delivered' GROUP BY order_id
        ) h WHERE orders.id = h.order_id AND orders.status = 'delivered'
    """)

    op.create_table(
        'driver_ratings',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org_column(),
        sa.Column('driver_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('source', sa.String(16), nullable=False, index=True),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('comment', sa.String(500), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, index=True),
        sa.CheckConstraint('score BETWEEN 1 AND 5', name='ck_driver_ratings_score'),
        sa.UniqueConstraint('order_id', 'source', name='uq_driver_ratings_order_source'),
    )
    op.create_table(
        'commission_plans',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org_column(),
        sa.Column('base_fare', sa.Float(), nullable=False, server_default='0'),
        sa.Column('fare_per_kg', sa.Float(), nullable=False, server_default='0'),
        sa.Column('levels', sa.JSON(), nullable=False),
        sa.Column('tiers', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.UniqueConstraint('organization_id', name='uq_commission_plans_org'),
    )


def downgrade():
    op.drop_table('commission_plans')
    op.drop_table('driver_ratings')
    op.drop_index('ix_orders_rating_token', 'orders')
    op.drop_index('ix_orders_delivered_at', 'orders')
    op.drop_index('ix_orders_driver_id', 'orders')
    for column in reversed(_order_columns()):
        op.drop_column('orders', column.name)
