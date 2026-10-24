"""WMS operations: locations with capacity and mixing rules, multi-dimensional stock balances
(location, owner, lot, serial, expiry) with ledger detail lines, inbound receipts with discrepancies,
quality inspections with new quality statuses, putaway tasks

Revision ID: 0025_wms_operations
Revises: 0024_wms_core
Create Date: 2026-10-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0025_wms_operations'
down_revision = '0024_wms_core'
branch_labels = None
depends_on = None

OLD_STATUSES = "'available', 'quarantine', 'blocked', 'damaged'"
STATUSES = "'available', 'pending', 'quarantine', 'blocked', 'rejected', 'defective', 'damaged'"
OLD_DOC_TYPES = ("'opening', 'receipt', 'order_issue', 'order_return', 'adjustment', 'write_off', 'transfer', "
                 "'status_change', 'stocktake', 'reversal'")
DOC_TYPES = OLD_DOC_TYPES + ", 'inbound_receipt', 'inspection', 'putaway', 'location_move'"
LEVELS = "'zone', 'aisle', 'rack', 'shelf', 'bin'"
LOCATION_TYPES = "'receiving', 'storage', 'picking', 'quarantine', 'staging', 'shipping'"
PROBLEMS = "'destination_full', 'destination_blocked', 'item_damaged', 'item_missing', 'scan_mismatch', 'rule_violation'"

LINE_TRIGGER = ("CREATE TRIGGER trg_stock_movement_lines_immutable BEFORE UPDATE OR DELETE ON stock_movement_lines "
                "FOR EACH ROW EXECUTE FUNCTION pasineh_immutable_row()")


def _org():
    return sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True)


def _user_fk(name: str):
    return sa.Column(name, sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)


def upgrade():
    # ---- طرف تجاری: مالک کالای امانی ----
    op.add_column('partners', sa.Column('is_owner', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.drop_constraint('ck_partners_role', 'partners', type_='check')
    op.create_check_constraint('ck_partners_role', 'partners', "is_supplier OR is_customer OR is_carrier OR is_owner")

    # ---- کالا: بازرسی اجباری و تعداد در پالت ----
    op.add_column('products', sa.Column('inspection_required', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('products', sa.Column('units_per_pallet', sa.Integer(), nullable=True))
    op.create_check_constraint('ck_products_units_per_pallet', 'products', "units_per_pallet IS NULL OR units_per_pallet > 0")

    # ---- وضعیت‌های کیفی و انواع سند جدید ----
    op.drop_constraint('ck_inventories_stock_status', 'inventories', type_='check')
    op.create_check_constraint('ck_inventories_stock_status', 'inventories', f"stock_status IN ({STATUSES})")
    op.drop_constraint('ck_stock_documents_type', 'stock_documents', type_='check')
    op.create_check_constraint('ck_stock_documents_type', 'stock_documents', f"doc_type IN ({DOC_TYPES})")

    # ---- محل‌ها ----
    op.create_table(
        'locations',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False, index=True),
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True, index=True),
        sa.Column('level', sa.String(8), nullable=False),
        sa.Column('code', sa.String(32), nullable=False),
        sa.Column('barcode', sa.String(64), nullable=False),
        sa.Column('name', sa.String(100), nullable=True),
        sa.Column('location_type', sa.String(16), nullable=False),
        sa.Column('max_weight_kg', sa.Float(), nullable=True),
        sa.Column('max_volume_m3', sa.Float(), nullable=True),
        sa.Column('max_pallets', sa.Integer(), nullable=True),
        sa.Column('allow_mixed_products', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('allow_mixed_lots', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('allow_mixed_owners', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('is_blocked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('block_reason', sa.String(200), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('warehouse_id', 'code', name='uq_locations_warehouse_code'),
        sa.UniqueConstraint('organization_id', 'barcode', name='uq_locations_org_barcode'),
        sa.CheckConstraint(f"level IN ({LEVELS})", name='ck_locations_level'),
        sa.CheckConstraint(f"location_type IN ({LOCATION_TYPES})", name='ck_locations_type'),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name='ck_locations_parent_self'),
        sa.CheckConstraint("(max_weight_kg IS NULL OR max_weight_kg > 0) AND (max_volume_m3 IS NULL OR max_volume_m3 > 0) "
                           "AND (max_pallets IS NULL OR max_pallets > 0)", name='ck_locations_capacity'),
    )

    # ---- موجودی ریز ----
    op.create_table(
        'stock_balances',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('inventory_id', sa.Integer(), sa.ForeignKey('inventories.id'), nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False, index=True),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False, index=True),
        sa.Column('stock_status', sa.String(16), nullable=False),
        sa.Column('location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True, index=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('partners.id'), nullable=True, index=True),
        sa.Column('lot_number', sa.String(64), nullable=True),
        sa.Column('serial_number', sa.String(64), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('inventory_id', 'location_id', 'owner_id', 'lot_number', 'serial_number', 'expiry_date',
                            name='uq_stock_balances_key', postgresql_nulls_not_distinct=True),
        sa.CheckConstraint('quantity >= 0', name='ck_stock_balances_quantity'),
        sa.CheckConstraint('serial_number IS NULL OR quantity <= 1', name='ck_stock_balances_serial_quantity'),
        sa.CheckConstraint(f"stock_status IN ({STATUSES})", name='ck_stock_balances_status'),
    )
    op.create_index('uq_stock_balances_serial', 'stock_balances', ['organization_id', 'product_id', 'serial_number'],
                    unique=True, postgresql_where=sa.text("serial_number IS NOT NULL AND quantity > 0"))
    op.create_index('ix_stock_balances_product_lot', 'stock_balances', ['product_id', 'lot_number'])

    op.create_table(
        'stock_movement_lines',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('movement_id', sa.Integer(), sa.ForeignKey('stock_movements.id'), nullable=False, index=True),
        sa.Column('balance_id', sa.Integer(), sa.ForeignKey('stock_balances.id'), nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False),
        sa.Column('stock_status', sa.String(16), nullable=False),
        sa.Column('location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True, index=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('partners.id'), nullable=True),
        sa.Column('lot_number', sa.String(64), nullable=True),
        sa.Column('serial_number', sa.String(64), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('quantity_change', sa.Integer(), nullable=False),
        sa.Column('balance_after', sa.Integer(), nullable=False),
        sa.CheckConstraint('quantity_change <> 0', name='ck_stock_movement_lines_nonzero'),
    )
    op.create_index('ix_stock_movement_lines_product_warehouse', 'stock_movement_lines', ['product_id', 'warehouse_id'])

    # داده‌های قبلی: هر ردیف موجودی یک ردیف ریز «بدون محل، بدون بچ» و هر گردش یک ردیف ریز روی آن
    op.execute("""
        INSERT INTO stock_balances (organization_id, inventory_id, product_id, warehouse_id, stock_status, quantity)
        SELECT organization_id, id, product_id, warehouse_id, stock_status, quantity FROM inventories
    """)
    op.execute("""
        INSERT INTO stock_movement_lines (organization_id, movement_id, balance_id, product_id, warehouse_id,
                                          stock_status, quantity_change, balance_after)
        SELECT m.organization_id, m.id, b.id, b.product_id, b.warehouse_id, b.stock_status, m.quantity_change, m.balance_after
        FROM stock_movements m JOIN stock_balances b ON b.inventory_id = m.inventory_id
        ORDER BY m.id
    """)
    op.execute(LINE_TRIGGER)

    # ---- رسید دریافت ----
    op.create_table(
        'inbound_receipts',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('code', sa.String(16), nullable=False, unique=True, index=True),
        sa.Column('receipt_type', sa.String(16), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, index=True),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False, index=True),
        sa.Column('partner_id', sa.Integer(), sa.ForeignKey('partners.id'), nullable=True, index=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('partners.id'), nullable=True),
        sa.Column('source_warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=True),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id'), nullable=True),
        sa.Column('reference_number', sa.String(64), nullable=True),
        sa.Column('external_ref', sa.String(64), nullable=True),
        sa.Column('expected_date', sa.Date(), nullable=True),
        sa.Column('receiving_location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('over_tolerance_pct', sa.Float(), nullable=False, server_default='0'),
        sa.Column('note', sa.String(500), nullable=True),
        sa.Column('idempotency_key', sa.String(64), nullable=True),
        sa.Column('request_hash', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, index=True),
        _user_fk('created_by_id'),
        sa.Column('received_at', sa.DateTime(), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        _user_fk('closed_by_id'),
        sa.Column('close_note', sa.String(500), nullable=True),
        sa.UniqueConstraint('organization_id', 'idempotency_key', name='uq_inbound_receipts_idempotency'),
        sa.CheckConstraint("receipt_type IN ('purchase', 'transfer', 'return', 'unexpected')", name='ck_inbound_receipts_type'),
        sa.CheckConstraint("status IN ('open', 'receiving', 'closed', 'canceled')", name='ck_inbound_receipts_status'),
        sa.CheckConstraint("over_tolerance_pct >= 0 AND over_tolerance_pct <= 100", name='ck_inbound_receipts_tolerance'),
        sa.CheckConstraint("receipt_type <> 'transfer' OR source_warehouse_id IS NOT NULL", name='ck_inbound_receipts_transfer_source'),
    )
    op.create_index('uq_inbound_receipts_partner_ref', 'inbound_receipts', ['organization_id', 'partner_id', 'external_ref'],
                    unique=True, postgresql_where=sa.text("external_ref IS NOT NULL AND status <> 'canceled'"))
    op.create_table(
        'inbound_receipt_lines',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('receipt_id', sa.Integer(), sa.ForeignKey('inbound_receipts.id'), nullable=False, index=True),
        sa.Column('line_no', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False, index=True),
        sa.Column('expected_quantity', sa.Integer(), nullable=False),
        sa.Column('received_quantity', sa.Integer(), nullable=False),
        sa.Column('accepted_quantity', sa.Integer(), nullable=False),
        sa.Column('rejected_quantity', sa.Integer(), nullable=False),
        sa.Column('lot_number', sa.String(64), nullable=True),
        sa.Column('note', sa.String(300), nullable=True),
        sa.Column('over_reason', sa.String(300), nullable=True),
        sa.Column('discrepancy_type', sa.String(16), nullable=True),
        sa.Column('discrepancy_quantity', sa.Integer(), nullable=True),
        sa.Column('discrepancy_reason', sa.String(300), nullable=True),
        sa.UniqueConstraint('receipt_id', 'line_no', name='uq_inbound_receipt_lines_no'),
        sa.CheckConstraint("expected_quantity >= 0 AND received_quantity >= 0 AND accepted_quantity >= 0 "
                           "AND rejected_quantity >= 0", name='ck_inbound_receipt_lines_non_negative'),
        sa.CheckConstraint("accepted_quantity + rejected_quantity <= received_quantity", name='ck_inbound_receipt_lines_inspected'),
        sa.CheckConstraint("discrepancy_type IS NULL OR discrepancy_type IN ('shortage', 'over', 'unexpected_item')",
                           name='ck_inbound_receipt_lines_discrepancy'),
    )

    # ---- بازرسی کیفی ----
    op.create_table(
        'quality_inspections',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('code', sa.String(16), nullable=False, unique=True, index=True),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False, index=True),
        sa.Column('location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('lot_number', sa.String(64), nullable=True),
        sa.Column('from_status', sa.String(16), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('receipt_id', sa.Integer(), sa.ForeignKey('inbound_receipts.id'), nullable=True, index=True),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('stock_documents.id'), nullable=True),
        sa.Column('note', sa.String(500), nullable=True),
        _user_fk('inspector_id'),
        sa.Column('created_at', sa.DateTime(), nullable=False, index=True),
        sa.CheckConstraint('quantity > 0', name='ck_quality_inspections_quantity'),
        sa.CheckConstraint(f"from_status IN ({STATUSES})", name='ck_quality_inspections_from_status'),
    )
    op.create_table(
        'quality_inspection_results',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('inspection_id', sa.Integer(), sa.ForeignKey('quality_inspections.id'), nullable=False, index=True),
        sa.Column('to_status', sa.String(16), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(300), nullable=True),
        sa.CheckConstraint('quantity > 0', name='ck_quality_inspection_results_quantity'),
        sa.CheckConstraint(f"to_status IN ({STATUSES})", name='ck_quality_inspection_results_status'),
    )

    # ---- جانمایی ----
    op.create_table(
        'putaway_tasks',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('code', sa.String(16), nullable=False, unique=True, index=True),
        sa.Column('status', sa.String(16), nullable=False, index=True),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False, index=True),
        sa.Column('stock_status', sa.String(16), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('quantity_done', sa.Integer(), nullable=False),
        sa.Column('source_location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('partners.id'), nullable=True),
        sa.Column('lot_number', sa.String(64), nullable=True),
        sa.Column('expiry_date', sa.Date(), nullable=True),
        sa.Column('suggested_location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('destination_location_id', sa.Integer(), sa.ForeignKey('locations.id'), nullable=True),
        sa.Column('receipt_id', sa.Integer(), sa.ForeignKey('inbound_receipts.id'), nullable=True, index=True),
        sa.Column('inspection_id', sa.Integer(), sa.ForeignKey('quality_inspections.id'), nullable=True),
        sa.Column('excluded_location_ids', sa.JSON(), nullable=False),
        sa.Column('failure_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_problem', sa.String(24), nullable=True),
        sa.Column('last_error', sa.String(300), nullable=True),
        sa.Column('note', sa.String(300), nullable=True),
        _user_fk('assigned_to_id'),
        sa.Column('created_at', sa.DateTime(), nullable=False, index=True),
        _user_fk('created_by_id'),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        _user_fk('completed_by_id'),
        sa.Column('cancel_reason', sa.String(300), nullable=True),
        sa.CheckConstraint("quantity > 0 AND quantity_done >= 0 AND quantity_done <= quantity", name='ck_putaway_tasks_quantity'),
        sa.CheckConstraint("status IN ('open', 'partial', 'done', 'canceled')", name='ck_putaway_tasks_status'),
        sa.CheckConstraint(f"stock_status IN ({STATUSES})", name='ck_putaway_tasks_stock_status'),
        sa.CheckConstraint(f"last_problem IS NULL OR last_problem IN ({PROBLEMS})", name='ck_putaway_tasks_problem'),
    )


def downgrade():
    bind = op.get_bind()
    blocked = bind.execute(sa.text("""
        SELECT (SELECT count(*) FROM locations) + (SELECT count(*) FROM inbound_receipts)
             + (SELECT count(*) FROM quality_inspections) + (SELECT count(*) FROM putaway_tasks)
             + (SELECT count(*) FROM stock_balances WHERE quantity <> 0 AND (lot_number IS NOT NULL
                    OR serial_number IS NOT NULL OR owner_id IS NOT NULL OR expiry_date IS NOT NULL))
             + (SELECT count(*) FROM inventories i WHERE stock_status IN ('pending', 'rejected', 'defective')
                    AND (quantity <> 0 OR EXISTS (SELECT 1 FROM stock_movements m WHERE m.inventory_id = i.id)))
             + (SELECT count(*) FROM stock_documents WHERE doc_type IN ('inbound_receipt', 'inspection', 'putaway', 'location_move'))
    """)).scalar()
    if blocked:
        raise RuntimeError("محل، رسید دریافت، بازرسی، جانمایی یا موجودی بچ/سریال‌دار وجود دارد؛ برگشت این مایگریشن داده را از دست می‌دهد.")

    op.drop_table('putaway_tasks')
    op.drop_table('quality_inspection_results')
    op.drop_table('quality_inspections')
    op.drop_table('inbound_receipt_lines')
    op.drop_index('uq_inbound_receipts_partner_ref', 'inbound_receipts')
    op.drop_table('inbound_receipts')
    op.execute("DROP TRIGGER IF EXISTS trg_stock_movement_lines_immutable ON stock_movement_lines")
    op.drop_index('ix_stock_movement_lines_product_warehouse', 'stock_movement_lines')
    op.drop_table('stock_movement_lines')
    op.drop_index('ix_stock_balances_product_lot', 'stock_balances')
    op.drop_index('uq_stock_balances_serial', 'stock_balances')
    op.drop_table('stock_balances')
    op.drop_table('locations')

    op.execute("DELETE FROM inventories WHERE stock_status IN ('pending', 'rejected', 'defective')")
    op.drop_constraint('ck_stock_documents_type', 'stock_documents', type_='check')
    op.create_check_constraint('ck_stock_documents_type', 'stock_documents', f"doc_type IN ({OLD_DOC_TYPES})")
    op.drop_constraint('ck_inventories_stock_status', 'inventories', type_='check')
    op.create_check_constraint('ck_inventories_stock_status', 'inventories', f"stock_status IN ({OLD_STATUSES})")

    op.drop_constraint('ck_products_units_per_pallet', 'products', type_='check')
    op.drop_column('products', 'units_per_pallet')
    op.drop_column('products', 'inspection_required')

    op.drop_constraint('ck_partners_role', 'partners', type_='check')
    op.execute("UPDATE partners SET is_customer = true WHERE is_owner AND NOT (is_supplier OR is_customer OR is_carrier)")
    op.create_check_constraint('ck_partners_role', 'partners', "is_supplier OR is_customer OR is_carrier")
    op.drop_column('partners', 'is_owner')
