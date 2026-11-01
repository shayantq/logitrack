"""تلاش‌های تحویل و مدرک آن‌ها، تعیین تکلیف تحویل ناموفق، و مرکز استثنا

سفارش‌های ناموفق موجود موجودی‌شان همان موقع برگشت خورده؛ failure_resolution='legacy' می‌گیرند تا بی‌تکلیف شمرده نشوند.

Revision ID: 0032_delivery_exceptions
Revises: 0031_saved_views
"""
import sqlalchemy as sa
from alembic import op

revision = '0032_delivery_exceptions'
down_revision = '0031_saved_views'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('delivery_attempt_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('orders', sa.Column('failure_resolution', sa.String(24), nullable=True))
    op.create_check_constraint(
        'ck_orders_failure_resolution', 'orders',
        "failure_resolution IS NULL OR failure_resolution IN ('redeliver', 'return_to_warehouse', 'dispute', 'legacy')")
    op.execute("UPDATE orders SET failure_resolution = 'legacy' WHERE status = 'failed'")

    op.create_table(
        'delivery_attempts',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('attempt_no', sa.Integer(), nullable=False),
        sa.Column('driver_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('vehicle_id', sa.Integer(), sa.ForeignKey('vehicles.id', ondelete='SET NULL'), nullable=True),
        sa.Column('outcome', sa.String(16), nullable=False),
        sa.Column('at', sa.DateTime(), nullable=False, index=True),
        sa.Column('recipient_name', sa.String(150), nullable=True),
        sa.Column('recipient_role', sa.String(16), nullable=True),
        sa.Column('photo_path', sa.String(255), nullable=True),
        sa.Column('photo_type', sa.String(16), nullable=True),
        sa.Column('exception_note', sa.String(500), nullable=True),
        sa.Column('failure_reason', sa.String(24), nullable=True),
        sa.Column('note', sa.String(500), nullable=True),
        sa.Column('next_attempt_at', sa.DateTime(), nullable=True),
        sa.Column('resolution', sa.String(24), nullable=True),
        sa.Column('resolved_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('order_id', 'attempt_no', name='uq_delivery_attempts_order_no'),
        sa.CheckConstraint("outcome IN ('delivered', 'failed')", name='ck_delivery_attempts_outcome'),
        sa.CheckConstraint("recipient_role IS NULL OR recipient_role IN ('self', 'family', 'colleague', 'guard', 'other')",
                           name='ck_delivery_attempts_recipient_role'),
        sa.CheckConstraint("failure_reason IS NULL OR failure_reason IN ('recipient_absent', 'wrong_address', 'refused', 'damaged', "
                           "'access_issue', 'vehicle_issue', 'other')", name='ck_delivery_attempts_reason'),
        sa.CheckConstraint("resolution IS NULL OR resolution IN ('redeliver', 'return_to_warehouse', 'dispute')",
                           name='ck_delivery_attempts_resolution'),
        sa.CheckConstraint("photo_type IS NULL OR photo_type IN ('delivery', 'damage', 'door', 'other')",
                           name='ck_delivery_attempts_photo_type'),
    )

    op.create_table(
        'operation_exceptions',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('kind', sa.String(32), nullable=False, index=True),
        sa.Column('entity_type', sa.String(16), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('severity', sa.String(16), nullable=False),
        sa.Column('team', sa.String(16), nullable=False),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('status', sa.String(16), nullable=False, index=True),
        sa.Column('opened_at', sa.DateTime(), nullable=False, index=True),
        sa.Column('due_at', sa.DateTime(), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('trigger_reason', sa.String(300), nullable=False),
        sa.Column('suggested_action', sa.String(300), nullable=True),
        sa.Column('resolution', sa.String(500), nullable=True),
        sa.Column('resolved_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('merged_into_id', sa.Integer(), sa.ForeignKey('operation_exceptions.id', ondelete='SET NULL'), nullable=True),
        sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name='ck_operation_exceptions_severity'),
        sa.CheckConstraint("team IN ('warehouse', 'fleet', 'support', 'management')", name='ck_operation_exceptions_team'),
        sa.CheckConstraint("status IN ('open', 'in_progress', 'waiting', 'resolved', 'merged')", name='ck_operation_exceptions_status'),
    )
    op.create_index('uq_operation_exceptions_active', 'operation_exceptions',
                    ['organization_id', 'kind', 'entity_type', 'entity_id'], unique=True,
                    postgresql_where=sa.text("status IN ('open', 'in_progress', 'waiting')"))
    op.create_table(
        'operation_exception_events',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('exception_id', sa.Integer(), sa.ForeignKey('operation_exceptions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action', sa.String(120), nullable=False),
        sa.Column('note', sa.String(500), nullable=True),
        sa.Column('at', sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('operation_exception_events')
    op.drop_index('uq_operation_exceptions_active', table_name='operation_exceptions')
    op.drop_table('operation_exceptions')
    op.drop_table('delivery_attempts')
    op.drop_constraint('ck_orders_failure_resolution', 'orders', type_='check')
    op.drop_column('orders', 'failure_resolution')
    op.drop_column('orders', 'delivery_attempt_count')
