"""عملیات میدانی: تحویل جزئی، برگشت از راننده، تماس، مأموریت، تحویل بین رانندگان، درخواست مشتری

سفارش‌هایی که پیش از این stock_state=returned گرفته‌اند دست نمی‌خورند.

Revision ID: 0034_field_operations
Revises: 0033_outbox_failures
"""
import sqlalchemy as sa
from alembic import op

revision = '0034_field_operations'
down_revision = '0033_outbox_failures'
branch_labels = None
depends_on = None

OLD_STATES = "'reserved', 'held', 'issued', 'released', 'returned'"
NEW_STATES = "'reserved', 'held', 'issued', 'returning', 'released', 'returned'"


def _tenant():
    return sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True)


def upgrade() -> None:
    op.drop_constraint('ck_orders_stock_state', 'orders', type_='check')
    op.create_check_constraint('ck_orders_stock_state', 'orders', f"stock_state IN ({NEW_STATES})")
    op.add_column('orders', sa.Column('assignment_state', sa.String(16), nullable=True))
    op.add_column('orders', sa.Column('assignment_deadline', sa.DateTime(), nullable=True))
    op.create_check_constraint('ck_orders_assignment_state', 'orders', "assignment_state IS NULL OR assignment_state IN ('pending', 'accepted')")
    op.add_column('delivery_attempts', sa.Column('partial', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.drop_constraint('ck_shipments_status', 'shipments', type_='check')
    op.create_check_constraint('ck_shipments_status', 'shipments', "status IN ('open', 'dispatched', 'closed', 'canceled')")
    op.add_column('shipments', sa.Column('closed_at', sa.DateTime(), nullable=True))
    op.add_column('shipments', sa.Column('closed_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))

    op.create_table(
        'delivery_attempt_lines',
        sa.Column('id', sa.Integer(), primary_key=True, index=True), _tenant(),
        sa.Column('attempt_id', sa.Integer(), sa.ForeignKey('delivery_attempts.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('order_item_id', sa.Integer(), sa.ForeignKey('order_items.id', ondelete='CASCADE'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='SET NULL'), nullable=True),
        sa.Column('product_name', sa.String(200), nullable=False),
        sa.Column('delivered_quantity', sa.Integer(), nullable=False),
        sa.Column('returned_quantity', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(300), nullable=True),
        sa.CheckConstraint('delivered_quantity >= 0 AND returned_quantity >= 0', name='ck_delivery_attempt_lines_quantity'),
    )
    op.create_table(
        'driver_returns',
        sa.Column('id', sa.Integer(), primary_key=True, index=True), _tenant(),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('attempt_id', sa.Integer(), sa.ForeignKey('delivery_attempts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('shipment_id', sa.Integer(), sa.ForeignKey('shipments.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('driver_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, index=True),
        sa.Column('reason', sa.String(200), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('received_at', sa.DateTime(), nullable=True),
        sa.Column('received_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('note', sa.String(500), nullable=True),
        sa.CheckConstraint("status IN ('open', 'received')", name='ck_driver_returns_status'),
    )
    op.create_table(
        'driver_return_lines',
        sa.Column('id', sa.Integer(), primary_key=True, index=True), _tenant(),
        sa.Column('return_id', sa.Integer(), sa.ForeignKey('driver_returns.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='SET NULL'), nullable=True),
        sa.Column('product_name', sa.String(200), nullable=False),
        sa.Column('expected_quantity', sa.Integer(), nullable=False),
        sa.Column('received_quantity', sa.Integer(), nullable=True),
        sa.Column('shortage_reason', sa.String(500), nullable=True),
    )
    op.create_table(
        'contact_attempts',
        sa.Column('id', sa.Integer(), primary_key=True, index=True), _tenant(),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('method', sa.String(8), nullable=False),
        sa.Column('outcome', sa.String(16), nullable=False),
        sa.Column('note', sa.String(500), nullable=True),
        sa.Column('at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("method IN ('call', 'sms', 'door')", name='ck_contact_attempts_method'),
        sa.CheckConstraint("outcome IN ('answered', 'no_answer', 'busy', 'wrong_number', 'off')", name='ck_contact_attempts_outcome'),
    )
    op.create_table(
        'order_handovers',
        sa.Column('id', sa.Integer(), primary_key=True, index=True), _tenant(),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('from_driver_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('from_vehicle_id', sa.Integer(), sa.ForeignKey('vehicles.id', ondelete='SET NULL'), nullable=True),
        sa.Column('to_driver_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('to_vehicle_id', sa.Integer(), sa.ForeignKey('vehicles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, index=True),
        sa.Column('note', sa.String(500), nullable=True),
        sa.Column('response_note', sa.String(500), nullable=True),
        sa.Column('requested_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('responded_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('responded_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('requested', 'accepted', 'rejected')", name='ck_order_handovers_status'),
    )
    op.create_table(
        'customer_requests',
        sa.Column('id', sa.Integer(), primary_key=True, index=True), _tenant(),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, index=True),
        sa.Column('note', sa.String(500), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('decided_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('decision_note', sa.String(500), nullable=True),
        sa.CheckConstraint("kind IN ('address_change', 'cancel', 'return', 'dispute')", name='ck_customer_requests_kind'),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name='ck_customer_requests_status'),
    )


def downgrade() -> None:
    op.drop_table('customer_requests')
    op.drop_table('order_handovers')
    op.drop_table('contact_attempts')
    op.drop_table('driver_return_lines')
    op.drop_table('driver_returns')
    op.drop_table('delivery_attempt_lines')
    op.drop_column('shipments', 'closed_by_id')
    op.drop_column('shipments', 'closed_at')
    op.execute("UPDATE shipments SET status = 'dispatched' WHERE status = 'closed'")
    op.drop_constraint('ck_shipments_status', 'shipments', type_='check')
    op.create_check_constraint('ck_shipments_status', 'shipments', "status IN ('open', 'dispatched', 'canceled')")
    op.drop_column('delivery_attempts', 'partial')
    op.drop_constraint('ck_orders_assignment_state', 'orders', type_='check')
    op.drop_column('orders', 'assignment_deadline')
    op.drop_column('orders', 'assignment_state')
    op.execute("UPDATE orders SET stock_state = 'returned' WHERE stock_state = 'returning'")
    op.drop_constraint('ck_orders_stock_state', 'orders', type_='check')
    op.create_check_constraint('ck_orders_stock_state', 'orders', f"stock_state IN ({OLD_STATES})")
