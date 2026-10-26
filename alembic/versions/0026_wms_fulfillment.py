"""WMS fulfillment: backorders with priority allocation, two-step transfer orders with in-transit status,
picking-location replenishment rules and ABC classes, pick lists, packages and shipments, dispositions
(scrap, repair, supplier return, re-inspection); new statuses repair and in_transit

Revision ID: 0026_wms_fulfillment
Revises: 0025_wms_operations
Create Date: 2026-10-25
"""
from alembic import op
import sqlalchemy as sa

revision = '0026_wms_fulfillment'
down_revision = '0025_wms_operations'
branch_labels = None
depends_on = None

OLD_STATUSES = "'available', 'pending', 'quarantine', 'blocked', 'rejected', 'defective', 'damaged'"
STATUSES = OLD_STATUSES + ", 'repair', 'in_transit'"
OLD_DOC_TYPES = ("'opening', 'receipt', 'order_issue', 'order_return', 'adjustment', 'write_off', 'transfer', "
                 "'status_change', 'stocktake', 'reversal', 'inbound_receipt', 'inspection', 'putaway', 'location_move'")
DOC_TYPES = OLD_DOC_TYPES + (", 'transfer_ship', 'transfer_receive', 'pick', 'replenishment', 'scrap', 'supplier_return', "
                             "'disposition'")
# قیدهای وضعیت کیفی که با افزوده شدن «در تعمیر» و «در راه» باید از نو ساخته شوند
STATUS_CHECKS = (
    ("inventories", "ck_inventories_stock_status", "stock_status"),
    ("stock_balances", "ck_stock_balances_status", "stock_status"),
    ("quality_inspections", "ck_quality_inspections_from_status", "from_status"),
    ("quality_inspection_results", "ck_quality_inspection_results_status", "to_status"),
    ("putaway_tasks", "ck_putaway_tasks_stock_status", "stock_status"),
)


def _org():
    return sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True)


def _user_fk(name: str):
    return sa.Column(name, sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)


def _status_checks(values: str) -> None:
    for table, name, column in STATUS_CHECKS:
        op.drop_constraint(name, table, type_='check')
        op.create_check_constraint(name, table, f"{column} IN ({values})")


def upgrade():
    _status_checks(STATUSES)
    op.drop_constraint('ck_stock_documents_type', 'stock_documents', type_='check')
    op.create_check_constraint('ck_stock_documents_type', 'stock_documents', f"doc_type IN ({DOC_TYPES})")

    # ---- ABC روی کالا ----
    op.add_column('products', sa.Column('abc_class', sa.String(1), nullable=True))
    op.add_column('products', sa.Column('abc_value', sa.Float(), nullable=True))
    op.add_column('products', sa.Column('abc_updated_at', sa.DateTime(), nullable=True))

    # ---- نوع وظیفه انبار ----
    op.add_column('putaway_tasks', sa.Column('task_type', sa.String(16), nullable=False, server_default='putaway'))
    op.create_check_constraint('ck_putaway_tasks_type', 'putaway_tasks', "task_type IN ('putaway', 'replenishment')")

    # ---- محموله (پیش از ستون orders.shipment_id) ----
    op.create_table(
        'shipments',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('code', sa.String(16), nullable=False, unique=True, index=True),
        sa.Column('status', sa.String(16), nullable=False, index=True),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False, index=True),
        sa.Column('vehicle_id', sa.Integer(), sa.ForeignKey('vehicles.id', ondelete='SET NULL'), nullable=True, index=True),
        _user_fk('driver_id'),
        sa.Column('note', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, index=True),
        _user_fk('created_by_id'),
        sa.Column('dispatched_at', sa.DateTime(), nullable=True),
        _user_fk('dispatched_by_id'),
        sa.CheckConstraint("status IN ('open', 'dispatched', 'canceled')", name='ck_shipments_status'),
    )

    # ---- سفارش: وضعیت آماده‌سازی، محموله، سفارش مادر ----
    op.add_column('orders', sa.Column('fulfillment_state', sa.String(16), nullable=False, server_default='open'))
    op.execute("UPDATE orders SET fulfillment_state = 'shipped' WHERE stock_state IN ('issued', 'returned')")
    op.create_check_constraint('ck_orders_fulfillment_state', 'orders',
                               "fulfillment_state IN ('open', 'picking', 'picked', 'packed', 'shipped')")
    op.add_column('orders', sa.Column('shipment_id', sa.Integer(), sa.ForeignKey('shipments.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_orders_shipment_id', 'orders', ['shipment_id'])
    op.add_column('orders', sa.Column('parent_order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='SET NULL'), nullable=True))

    # ---- سفارش معوق ----
    op.create_table(
        'backorders',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id'), nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False, index=True),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Float(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('priority', sa.Boolean(), nullable=False),
        sa.Column('due_at', sa.DateTime(), nullable=False),
        sa.Column('fulfilled_order_id', sa.Integer(), sa.ForeignKey('orders.id'), nullable=True),
        sa.Column('note', sa.String(300), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, index=True),
        sa.Column('allocated_at', sa.DateTime(), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        _user_fk('created_by_id'),
        sa.CheckConstraint('quantity > 0', name='ck_backorders_quantity'),
        sa.CheckConstraint("status IN ('open', 'allocated', 'fulfilled', 'canceled')", name='ck_backorders_status'),
    )
    op.create_index('ix_backorders_queue', 'backorders', ['status', 'warehouse_id', 'product_id'])

    # ---- سفارش انتقال ----
    op.create_table(
        'transfer_orders',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('code', sa.String(16), nullable=False, unique=True, index=True),
        sa.Column('status', sa.String(16), nullable=False, index=True),
        sa.Column('from_warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False, index=True),
        sa.Column('to_warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False, index=True),
        sa.Column('from_location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('to_location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('note', sa.String(500), nullable=True),
        sa.Column('idempotency_key', sa.String(64), nullable=True),
        sa.Column('request_hash', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, index=True),
        _user_fk('created_by_id'),
        sa.Column('shipped_at', sa.DateTime(), nullable=True),
        sa.Column('received_at', sa.DateTime(), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('close_note', sa.String(500), nullable=True),
        sa.Column('resolution', sa.String(16), nullable=True),
        sa.UniqueConstraint('organization_id', 'idempotency_key', name='uq_transfer_orders_idempotency'),
        sa.CheckConstraint("status IN ('open', 'in_transit', 'received', 'closed', 'canceled')", name='ck_transfer_orders_status'),
        sa.CheckConstraint("from_warehouse_id <> to_warehouse_id OR from_location_id IS DISTINCT FROM to_location_id",
                           name='ck_transfer_orders_route'),
    )
    op.create_table(
        'transfer_order_lines',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('transfer_id', sa.Integer(), sa.ForeignKey('transfer_orders.id'), nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False, index=True),
        sa.Column('lot_number', sa.String(64), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('shipped_quantity', sa.Integer(), nullable=False),
        sa.Column('received_quantity', sa.Integer(), nullable=False),
        sa.Column('damaged_quantity', sa.Integer(), nullable=False),
        sa.Column('resolved_quantity', sa.Integer(), nullable=False),
        sa.Column('discrepancy_reason', sa.String(300), nullable=True),
        sa.CheckConstraint("quantity > 0 AND shipped_quantity >= 0 AND received_quantity >= 0 AND damaged_quantity >= 0 "
                           "AND resolved_quantity >= 0", name='ck_transfer_lines_quantities'),
        sa.CheckConstraint("received_quantity + damaged_quantity + resolved_quantity <= shipped_quantity",
                           name='ck_transfer_lines_balance'),
    )

    # ---- تأمین مجدد ----
    op.create_table(
        'replenishment_rules',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False, index=True),
        sa.Column('location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False, index=True),
        sa.Column('min_quantity', sa.Integer(), nullable=False),
        sa.Column('max_quantity', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('location_id', 'product_id', name='uq_replenishment_rules_location_product'),
        sa.CheckConstraint("min_quantity >= 0 AND max_quantity > min_quantity", name='ck_replenishment_rules_range'),
    )

    # ---- پیکینگ ----
    op.create_table(
        'pick_lists',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('code', sa.String(16), nullable=False, unique=True, index=True),
        sa.Column('strategy', sa.String(8), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, index=True),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False, index=True),
        sa.Column('zone_location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('staging_location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('wave_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, index=True),
        _user_fk('created_by_id'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("strategy IN ('single', 'batch', 'wave', 'zone')", name='ck_pick_lists_strategy'),
        sa.CheckConstraint("status IN ('open', 'in_progress', 'picked', 'canceled')", name='ck_pick_lists_status'),
    )
    op.create_table(
        'pick_lines',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('pick_list_id', sa.Integer(), sa.ForeignKey('pick_lists.id'), nullable=False, index=True),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False, index=True),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False),
        sa.Column('location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('lot_number', sa.String(64), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('staged_location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('picked_quantity', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(8), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('short_reason', sa.String(300), nullable=True),
        sa.Column('issued', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('picked_at', sa.DateTime(), nullable=True),
        _user_fk('picked_by_id'),
        sa.CheckConstraint("quantity > 0 AND picked_quantity >= 0 AND picked_quantity <= quantity", name='ck_pick_lines_quantity'),
        sa.CheckConstraint("status IN ('open', 'picked', 'short', 'canceled')", name='ck_pick_lines_status'),
    )
    op.create_index('ix_pick_lines_order_status', 'pick_lines', ['order_id', 'status'])

    # ---- بسته ----
    op.create_table(
        'packages',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('code', sa.String(20), nullable=False, unique=True, index=True),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('length_cm', sa.Float(), nullable=False),
        sa.Column('width_cm', sa.Float(), nullable=False),
        sa.Column('height_cm', sa.Float(), nullable=False),
        sa.Column('weight_kg', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        _user_fk('packed_by_id'),
        sa.CheckConstraint("weight_kg > 0 AND length_cm > 0 AND width_cm > 0 AND height_cm > 0", name='ck_packages_size'),
        sa.UniqueConstraint('order_id', 'sequence', name='uq_packages_order_sequence'),
    )
    op.create_table(
        'package_items',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('package_id', sa.Integer(), sa.ForeignKey('packages.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.CheckConstraint('quantity > 0', name='ck_package_items_quantity'),
    )

    # ---- تعیین تکلیف ----
    op.create_table(
        'dispositions',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('code', sa.String(16), nullable=False, unique=True, index=True),
        sa.Column('action', sa.String(24), nullable=False),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False, index=True),
        sa.Column('location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('lot_number', sa.String(64), nullable=True),
        sa.Column('from_status', sa.String(16), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('partner_id', sa.Integer(), sa.ForeignKey('partners.id'), nullable=True),
        sa.Column('receipt_id', sa.Integer(), sa.ForeignKey('inbound_receipts.id'), nullable=True, index=True),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('stock_documents.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, index=True),
        _user_fk('created_by_id'),
        sa.CheckConstraint('quantity > 0', name='ck_dispositions_quantity'),
        sa.CheckConstraint("action IN ('scrap', 'repair', 'return_to_supplier', 'reinspect')", name='ck_dispositions_action'),
        sa.CheckConstraint(f"from_status IN ({STATUSES})", name='ck_dispositions_from_status'),
    )


def downgrade():
    bind = op.get_bind()
    blocked = bind.execute(sa.text("""
        SELECT (SELECT count(*) FROM backorders) + (SELECT count(*) FROM transfer_orders) + (SELECT count(*) FROM pick_lists)
             + (SELECT count(*) FROM shipments) + (SELECT count(*) FROM dispositions) + (SELECT count(*) FROM replenishment_rules)
             + (SELECT count(*) FROM putaway_tasks WHERE task_type <> 'putaway')
             + (SELECT count(*) FROM inventories i WHERE stock_status IN ('repair', 'in_transit')
                    AND (quantity <> 0 OR EXISTS (SELECT 1 FROM stock_movements m WHERE m.inventory_id = i.id)))
             + (SELECT count(*) FROM stock_documents WHERE doc_type IN ('transfer_ship', 'transfer_receive', 'pick',
                    'replenishment', 'scrap', 'supplier_return', 'disposition'))
    """)).scalar()
    if blocked:
        raise RuntimeError("سفارش معوق، انتقال، پیکینگ، محموله، تأمین مجدد یا تعیین تکلیف ثبت شده است؛ برگشت این مایگریشن داده را از دست می‌دهد.")

    op.drop_table('dispositions')
    op.drop_table('package_items')
    op.drop_table('packages')
    op.drop_index('ix_pick_lines_order_status', 'pick_lines')
    op.drop_table('pick_lines')
    op.drop_table('pick_lists')
    op.drop_table('replenishment_rules')
    op.drop_table('transfer_order_lines')
    op.drop_table('transfer_orders')
    op.drop_index('ix_backorders_queue', 'backorders')
    op.drop_table('backorders')
    op.drop_column('orders', 'parent_order_id')
    op.drop_index('ix_orders_shipment_id', 'orders')
    op.drop_column('orders', 'shipment_id')
    op.drop_constraint('ck_orders_fulfillment_state', 'orders', type_='check')
    op.drop_column('orders', 'fulfillment_state')
    op.drop_table('shipments')
    op.drop_constraint('ck_putaway_tasks_type', 'putaway_tasks', type_='check')
    op.drop_column('putaway_tasks', 'task_type')
    for column in ('abc_updated_at', 'abc_value', 'abc_class'):
        op.drop_column('products', column)
    op.execute("DELETE FROM stock_balances WHERE stock_status IN ('repair', 'in_transit')")
    op.execute("DELETE FROM inventories WHERE stock_status IN ('repair', 'in_transit')")
    op.drop_constraint('ck_stock_documents_type', 'stock_documents', type_='check')
    op.create_check_constraint('ck_stock_documents_type', 'stock_documents', f"doc_type IN ({OLD_DOC_TYPES})")
    _status_checks(OLD_STATUSES)
