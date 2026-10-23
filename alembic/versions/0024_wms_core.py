"""WMS core: warehouse types/codes/hierarchy, product master data, partners, units of measure,
inventory buckets per quality status with reservations, inventory documents with reversal,
immutable ledger and domain events, idempotency keys

Revision ID: 0024_wms_core
Revises: 0023_password_resets
Create Date: 2026-10-23
"""
from alembic import op
import sqlalchemy as sa

revision = '0024_wms_core'
down_revision = '0023_password_resets'
branch_labels = None
depends_on = None

STOCK_STATUSES = "'available', 'quarantine', 'blocked', 'damaged'"
WAREHOUSE_TYPES = "'general', 'finished_goods', 'distribution', 'raw_materials', 'quarantine', 'returns', 'transit', 'site'"
DOC_TYPES = ("'opening', 'receipt', 'order_issue', 'order_return', 'adjustment', 'write_off', 'transfer', "
             "'status_change', 'stocktake', 'reversal'")
DOC_STATUSES = "'draft', 'posted', 'reversed', 'canceled'"

TRIGGERS = (
    """
    CREATE OR REPLACE FUNCTION pasineh_immutable_row() RETURNS trigger AS $$
    BEGIN
        IF current_setting('pasineh.ledger_maintenance', true) = 'on' THEN
            RETURN COALESCE(NEW, OLD);
        END IF;
        RAISE EXCEPTION USING MESSAGE = 'rows of ' || TG_TABLE_NAME || ' are immutable (use a reversal document)', ERRCODE = 'check_violation';
    END $$ LANGUAGE plpgsql
    """,
    """
    CREATE OR REPLACE FUNCTION pasineh_guard_stock_document() RETURNS trigger AS $$
    BEGIN
        IF current_setting('pasineh.ledger_maintenance', true) = 'on' THEN
            RETURN COALESCE(NEW, OLD);
        END IF;
        IF TG_OP = 'DELETE' THEN
            IF OLD.status IN ('draft', 'canceled') THEN RETURN OLD; END IF;
            RAISE EXCEPTION 'posted stock documents cannot be deleted' USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.status = 'draft' THEN RETURN NEW; END IF;
        IF (to_jsonb(NEW) - 'status') IS DISTINCT FROM (to_jsonb(OLD) - 'status')
           OR NOT (NEW.status = OLD.status OR (OLD.status = 'posted' AND NEW.status = 'reversed')) THEN
            RAISE EXCEPTION 'posted stock documents are immutable' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END $$ LANGUAGE plpgsql
    """,
    "CREATE TRIGGER trg_stock_movements_immutable BEFORE UPDATE OR DELETE ON stock_movements "
    "FOR EACH ROW EXECUTE FUNCTION pasineh_immutable_row()",
    "CREATE TRIGGER trg_domain_events_immutable BEFORE UPDATE OR DELETE ON domain_events "
    "FOR EACH ROW EXECUTE FUNCTION pasineh_immutable_row()",
    "CREATE TRIGGER trg_stock_documents_guard BEFORE UPDATE OR DELETE ON stock_documents "
    "FOR EACH ROW EXECUTE FUNCTION pasineh_guard_stock_document()",
)


def _org():
    return sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True)


def _replace_fk(table: str, column: str, ref_table: str, ondelete: str | None):
    """کلید خارجی یک ستون را با رفتار حذف جدید از نو می‌سازد (نام قبلی از خود دیتابیس خوانده می‌شود)."""
    inspector = sa.inspect(op.get_bind())
    for fk in inspector.get_foreign_keys(table):
        if fk["constrained_columns"] == [column]:
            op.drop_constraint(fk["name"], table, type_="foreignkey")
    op.create_foreign_key(None, table, ref_table, [column], ["id"], ondelete=ondelete)


def upgrade():
    bind = op.get_bind()

    # ---- انبار: کد، نوع، سلسله‌مراتب، فعال/غیرفعال ----
    op.add_column('warehouses', sa.Column('code', sa.String(16), nullable=True))
    op.add_column('warehouses', sa.Column('type', sa.String(24), nullable=False, server_default='general'))
    op.add_column('warehouses', sa.Column('parent_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=True))
    op.add_column('warehouses', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_index('ix_warehouses_parent_id', 'warehouses', ['parent_id'])
    op.execute("""
        UPDATE warehouses w SET code = 'WH-' || lpad(x.n::text, 2, '0')
        FROM (SELECT id, row_number() OVER (PARTITION BY organization_id ORDER BY id) AS n FROM warehouses) x
        WHERE x.id = w.id
    """)
    op.alter_column('warehouses', 'code', nullable=False)
    op.create_unique_constraint('uq_warehouses_org_code', 'warehouses', ['organization_id', 'code'])
    op.create_check_constraint('ck_warehouses_type', 'warehouses', f"type IN ({WAREHOUSE_TYPES})")
    op.create_check_constraint('ck_warehouses_parent_self', 'warehouses', "parent_id IS NULL OR parent_id <> id")

    # ---- کالا: داده پایه ----
    for column in (
        sa.Column('short_name', sa.String(60), nullable=True),
        sa.Column('net_weight_kg', sa.Float(), nullable=True),
        sa.Column('length_cm', sa.Float(), nullable=True),
        sa.Column('width_cm', sa.Float(), nullable=True),
        sa.Column('height_cm', sa.Float(), nullable=True),
        sa.Column('lot_tracked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('serial_tracked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('expiry_tracked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('shelf_life_days', sa.Integer(), nullable=True),
        sa.Column('min_stock', sa.Integer(), nullable=True),
        sa.Column('max_stock', sa.Integer(), nullable=True),
        sa.Column('reorder_point', sa.Integer(), nullable=True),
    ):
        op.add_column('products', column)
    # بارکد خالی ← NULL؛ بارکد تکراری در یک سازمان فقط روی قدیمی‌ترین کالا می‌ماند
    op.execute("UPDATE products SET barcode = NULL WHERE barcode IS NOT NULL AND btrim(barcode) = ''")
    op.execute("""
        UPDATE products p SET barcode = NULL
        FROM (SELECT id, row_number() OVER (PARTITION BY organization_id, barcode ORDER BY id) AS n
              FROM products WHERE barcode IS NOT NULL) d
        WHERE d.id = p.id AND d.n > 1
    """)
    op.create_unique_constraint('uq_products_org_barcode', 'products', ['organization_id', 'barcode'])
    op.create_check_constraint('ck_products_net_weight', 'products',
                               "net_weight_kg IS NULL OR weight_kg IS NULL OR net_weight_kg <= weight_kg")
    op.create_check_constraint('ck_products_dimensions', 'products',
                               "(length_cm IS NULL OR length_cm > 0) AND (width_cm IS NULL OR width_cm > 0) AND (height_cm IS NULL OR height_cm > 0)")
    op.create_check_constraint('ck_products_expiry_needs_lot', 'products', "NOT expiry_tracked OR lot_tracked")
    op.create_check_constraint('ck_products_shelf_life', 'products', "shelf_life_days IS NULL OR shelf_life_days > 0")
    op.create_check_constraint('ck_products_thresholds', 'products',
                               "(min_stock IS NULL OR min_stock >= 0) AND (reorder_point IS NULL OR reorder_point >= 0) "
                               "AND (max_stock IS NULL OR min_stock IS NULL OR max_stock >= min_stock)")

    # ---- طرف‌های تجاری، واحدهای فرعی، تأمین‌کننده کالا ----
    op.create_table(
        'partners',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('code', sa.String(16), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('is_supplier', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_customer', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_carrier', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('legal_name', sa.String(200), nullable=True),
        sa.Column('national_id', sa.String(11), nullable=True),
        sa.Column('economic_code', sa.String(14), nullable=True),
        sa.Column('registration_number', sa.String(32), nullable=True),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('mobile', sa.String(11), nullable=True),
        sa.Column('email', sa.String(254), nullable=True),
        sa.Column('website', sa.String(200), nullable=True),
        sa.Column('province', sa.String(64), nullable=True),
        sa.Column('city', sa.String(64), nullable=True),
        sa.Column('address', sa.String(500), nullable=True),
        sa.Column('postal_code', sa.String(10), nullable=True),
        sa.Column('contact_name', sa.String(100), nullable=True),
        sa.Column('contact_mobile', sa.String(11), nullable=True),
        sa.Column('iban', sa.String(26), nullable=True),
        sa.Column('payment_terms_days', sa.Integer(), nullable=True),
        sa.Column('lead_time_days', sa.Integer(), nullable=True),
        sa.Column('carrier_service', sa.String(16), nullable=True),
        sa.Column('tracking_url', sa.String(300), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.UniqueConstraint('organization_id', 'code', name='uq_partners_org_code'),
        sa.UniqueConstraint('organization_id', 'national_id', name='uq_partners_org_national_id'),
        sa.CheckConstraint('is_supplier OR is_customer OR is_carrier', name='ck_partners_role'),
        sa.CheckConstraint("kind IN ('legal', 'individual')", name='ck_partners_kind'),
        sa.CheckConstraint("carrier_service IS NULL OR carrier_service IN ('road', 'rail', 'air', 'sea', 'courier', 'post')",
                           name='ck_partners_carrier_service'),
        sa.CheckConstraint('payment_terms_days IS NULL OR (payment_terms_days >= 0 AND payment_terms_days <= 365)',
                           name='ck_partners_payment_terms'),
        sa.CheckConstraint('lead_time_days IS NULL OR (lead_time_days >= 0 AND lead_time_days <= 365)', name='ck_partners_lead_time'),
    )
    op.create_table(
        'product_uoms',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(32), nullable=False),
        sa.Column('factor', sa.Integer(), nullable=False),
        sa.Column('barcode', sa.String(64), nullable=True),
        sa.Column('is_purchase_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_sales_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint('product_id', 'name', name='uq_product_uoms_name'),
        sa.UniqueConstraint('organization_id', 'barcode', name='uq_product_uoms_org_barcode'),
        sa.CheckConstraint('factor >= 2', name='ck_product_uoms_factor'),
    )
    op.create_table(
        'product_suppliers',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('partner_id', sa.Integer(), sa.ForeignKey('partners.id'), nullable=False, index=True),
        sa.Column('supplier_sku', sa.String(64), nullable=True),
        sa.Column('lead_time_days', sa.Integer(), nullable=True),
        sa.Column('min_order_qty', sa.Integer(), nullable=True),
        sa.Column('last_price', sa.Float(), nullable=True),
        sa.Column('is_preferred', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint('product_id', 'partner_id', name='uq_product_suppliers_pair'),
        sa.CheckConstraint('lead_time_days IS NULL OR lead_time_days >= 0', name='ck_product_suppliers_lead_time'),
        sa.CheckConstraint('min_order_qty IS NULL OR min_order_qty > 0', name='ck_product_suppliers_moq'),
        sa.CheckConstraint('last_price IS NULL OR last_price >= 0', name='ck_product_suppliers_price'),
    )

    # ---- موجودی: هر کالا × انبار × وضعیت کیفی یک ردیف، با رزرو ----
    # ردیف‌های بی‌انبار به اولین انبار سازمان می‌روند (اگر سازمانی انبار ندارد، «انبار مرکزی» ساخته می‌شود)
    op.execute("""
        INSERT INTO warehouses (organization_id, name, location, code, type, is_active)
        SELECT DISTINCT i.organization_id, 'انبار مرکزی', NULL, 'WH-01', 'general', true
        FROM inventories i
        WHERE i.warehouse_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM warehouses w WHERE w.organization_id = i.organization_id)
    """)
    op.execute("""
        UPDATE inventories i SET warehouse_id = (
            SELECT min(w.id) FROM warehouses w WHERE w.organization_id = i.organization_id)
        WHERE i.warehouse_id IS NULL
    """)
    # ردیف‌های تکراری یک کالا در یک انبار در ردیف قدیمی‌تر ادغام می‌شوند (گردش‌ها به همان ردیف منتقل می‌شوند)
    duplicates = bind.execute(sa.text("""
        SELECT i.id, k.keep_id, i.quantity FROM inventories i
        JOIN (SELECT organization_id, product_id, warehouse_id, min(id) AS keep_id FROM inventories
              GROUP BY organization_id, product_id, warehouse_id HAVING count(*) > 1) k
          ON k.organization_id = i.organization_id AND k.product_id = i.product_id AND k.warehouse_id = i.warehouse_id
        WHERE i.id <> k.keep_id
    """)).all()
    for dup_id, keep_id, quantity in duplicates:
        bind.execute(sa.text("UPDATE inventories SET quantity = quantity + :q WHERE id = :k"), {"q": quantity or 0, "k": keep_id})
        bind.execute(sa.text("UPDATE stock_movements SET inventory_id = :k WHERE inventory_id = :d"), {"k": keep_id, "d": dup_id})
        bind.execute(sa.text("UPDATE stocktake_lines SET inventory_id = :k WHERE inventory_id = :d"), {"k": keep_id, "d": dup_id})
        bind.execute(sa.text("DELETE FROM inventories WHERE id = :d"), {"d": dup_id})

    op.add_column('inventories', sa.Column('stock_status', sa.String(16), nullable=False, server_default='available'))
    op.add_column('inventories', sa.Column('reserved_quantity', sa.Integer(), nullable=False, server_default='0'))
    op.alter_column('inventories', 'warehouse_id', nullable=False)
    op.create_index('ix_inventories_warehouse_id', 'inventories', ['warehouse_id'])
    _replace_fk('inventories', 'product_id', 'products', None)
    _replace_fk('inventories', 'warehouse_id', 'warehouses', None)
    op.create_unique_constraint('uq_inventories_bucket', 'inventories', ['organization_id', 'product_id', 'warehouse_id', 'stock_status'])
    op.create_check_constraint('ck_inventories_stock_status', 'inventories', f"stock_status IN ({STOCK_STATUSES})")
    op.create_check_constraint('ck_inventories_reserved', 'inventories', "reserved_quantity >= 0 AND reserved_quantity <= quantity")
    op.create_check_constraint('ck_inventories_reserve_available_only', 'inventories',
                               "stock_status = 'available' OR reserved_quantity = 0")

    # ---- اسناد انبار ----
    op.create_table(
        'stock_documents',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('code', sa.String(16), nullable=False, unique=True, index=True),
        sa.Column('doc_type', sa.String(24), nullable=False, index=True),
        sa.Column('status', sa.String(16), nullable=False, index=True),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=True, index=True),
        sa.Column('partner_id', sa.Integer(), sa.ForeignKey('partners.id'), nullable=True, index=True),
        sa.Column('reference_type', sa.String(32), nullable=True),
        sa.Column('reference_id', sa.Integer(), nullable=True),
        sa.Column('external_ref', sa.String(64), nullable=True),
        sa.Column('note', sa.String(500), nullable=True),
        sa.Column('idempotency_key', sa.String(64), nullable=True),
        sa.Column('request_hash', sa.String(64), nullable=True),
        sa.Column('reversal_of_id', sa.Integer(), sa.ForeignKey('stock_documents.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, index=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('posted_at', sa.DateTime(), nullable=True),
        sa.Column('posted_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('migration_key', sa.String(64), nullable=True),
        sa.UniqueConstraint('organization_id', 'idempotency_key', name='uq_stock_documents_idempotency'),
        sa.UniqueConstraint('reversal_of_id', name='uq_stock_documents_reversal'),
        sa.CheckConstraint(f"doc_type IN ({DOC_TYPES})", name='ck_stock_documents_type'),
        sa.CheckConstraint(f"status IN ({DOC_STATUSES})", name='ck_stock_documents_status'),
    )
    op.create_index('ix_stock_documents_reference', 'stock_documents', ['reference_type', 'reference_id'])

    # ---- گردش‌ها: سند، وضعیت کیفی، برگشت ----
    op.add_column('stock_movements', sa.Column('document_id', sa.Integer(), nullable=True))
    op.add_column('stock_movements', sa.Column('stock_status', sa.String(16), nullable=False, server_default='available'))
    op.add_column('stock_movements', sa.Column('reversal_of_id', sa.Integer(), nullable=True))
    # هر گردش قدیمی یک سند می‌گیرد؛ دو گردش یک انتقال، و گردش‌های یک سفارش/انبارگردانی هم‌نوع یک سند مشترک
    op.add_column('stock_movements', sa.Column('migration_key', sa.String(64), nullable=True))
    op.execute("""
        UPDATE stock_movements SET migration_key = CASE
            WHEN movement_type IN ('transfer_out', 'transfer_in') AND reference_id IS NOT NULL THEN 'transfer:' || reference_id
            WHEN reference_type = 'order' AND reference_id IS NOT NULL THEN movement_type || ':order:' || reference_id
            WHEN reference_type = 'stocktake' AND reference_id IS NOT NULL THEN 'stocktake:' || reference_id
            ELSE 'movement:' || id END
    """)
    op.execute("""
        INSERT INTO stock_documents (organization_id, code, doc_type, status, warehouse_id, reference_type, reference_id,
                                     note, created_at, created_by_id, posted_at, posted_by_id, migration_key)
        SELECT DISTINCT ON (migration_key)
            organization_id,
            CASE movement_type
                WHEN 'initial' THEN 'OB' WHEN 'receipt' THEN 'RC' WHEN 'order_out' THEN 'GI' WHEN 'order_return' THEN 'RT'
                WHEN 'damage' THEN 'WO' WHEN 'transfer_out' THEN 'TR' WHEN 'transfer_in' THEN 'TR' WHEN 'stocktake' THEN 'IC'
                ELSE 'AJ' END || '-M' || lpad(id::text, 7, '0'),
            CASE movement_type
                WHEN 'initial' THEN 'opening' WHEN 'receipt' THEN 'receipt' WHEN 'order_out' THEN 'order_issue'
                WHEN 'order_return' THEN 'order_return' WHEN 'damage' THEN 'write_off' WHEN 'transfer_out' THEN 'transfer'
                WHEN 'transfer_in' THEN 'transfer' WHEN 'stocktake' THEN 'stocktake' ELSE 'adjustment' END,
            'posted', warehouse_id, reference_type, reference_id, left(reason, 500),
            COALESCE(created_at, now()), created_by_id, COALESCE(created_at, now()), created_by_id, migration_key
        FROM stock_movements
        ORDER BY migration_key, id
    """)
    op.execute("""
        UPDATE stock_movements m SET document_id = d.id
        FROM stock_documents d WHERE d.migration_key = m.migration_key
    """)
    op.drop_column('stock_movements', 'migration_key')
    op.drop_column('stock_documents', 'migration_key')
    op.alter_column('stock_movements', 'document_id', nullable=False)
    op.create_foreign_key(None, 'stock_movements', 'stock_documents', ['document_id'], ['id'])
    op.create_foreign_key(None, 'stock_movements', 'stock_movements', ['reversal_of_id'], ['id'])
    op.create_index('ix_stock_movements_document_id', 'stock_movements', ['document_id'])
    op.create_unique_constraint('uq_stock_movements_reversal', 'stock_movements', ['reversal_of_id'])
    _replace_fk('stock_movements', 'inventory_id', 'inventories', None)
    _replace_fk('stock_movements', 'product_id', 'products', None)
    _replace_fk('stock_movements', 'warehouse_id', 'warehouses', None)

    # ---- رزرو موجودی ----
    op.create_table(
        'stock_reservations',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('inventory_id', sa.Integer(), sa.ForeignKey('inventories.id'), nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=False, index=True),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, index=True),
        sa.Column('reference_type', sa.String(32), nullable=False),
        sa.Column('reference_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('closed_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('close_reason', sa.String(200), nullable=True),
        sa.Column('movement_id', sa.Integer(), sa.ForeignKey('stock_movements.id'), nullable=True),
        sa.CheckConstraint('quantity > 0', name='ck_stock_reservations_quantity'),
        sa.CheckConstraint("status IN ('active', 'consumed', 'released')", name='ck_stock_reservations_status'),
    )
    op.create_index('ix_stock_reservations_reference', 'stock_reservations', ['reference_type', 'reference_id'])

    # ---- سفارش: وضعیت کالا و کلید یکتایی ----
    # سفارش‌های قبلی هنگام ثبت از موجودی کم شده بودند (نه رزرو)
    op.add_column('orders', sa.Column('stock_state', sa.String(16), nullable=True))
    op.execute("""
        UPDATE orders SET stock_state = CASE WHEN status IN ('failed', 'canceled', 'expired') THEN 'returned' ELSE 'issued' END
    """)
    op.alter_column('orders', 'stock_state', nullable=False)
    op.add_column('orders', sa.Column('idempotency_key', sa.String(64), nullable=True))
    op.add_column('orders', sa.Column('request_hash', sa.String(64), nullable=True))
    op.create_unique_constraint('uq_orders_idempotency', 'orders', ['organization_id', 'idempotency_key'])
    op.create_check_constraint('ck_orders_stock_state', 'orders', "stock_state IN ('reserved', 'issued', 'released', 'returned')")

    # ---- رویدادهای دامنه ----
    op.create_table(
        'domain_events',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('occurred_at', sa.DateTime(), nullable=False, index=True),
        sa.Column('event_type', sa.String(48), nullable=False, index=True),
        sa.Column('aggregate_type', sa.String(32), nullable=False),
        sa.Column('aggregate_id', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('actor_name', sa.String(150), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=False),
    )
    op.create_index('ix_domain_events_aggregate', 'domain_events', ['aggregate_type', 'aggregate_id'])

    # ---- تغییرناپذیری سوابق در خود دیتابیس ----
    for statement in TRIGGERS:
        op.execute(statement)


def downgrade():
    bind = op.get_bind()
    blocked = bind.execute(sa.text(
        "SELECT count(*) FROM inventories WHERE (stock_status <> 'available' AND quantity <> 0) OR reserved_quantity <> 0"
    )).scalar()
    if blocked:
        raise RuntimeError("موجودی غیرسالم یا رزرو فعال وجود دارد؛ برگشت این مایگریشن داده را از دست می‌دهد.")

    op.execute("DROP TRIGGER IF EXISTS trg_stock_documents_guard ON stock_documents")
    op.execute("DROP TRIGGER IF EXISTS trg_domain_events_immutable ON domain_events")
    op.execute("DROP TRIGGER IF EXISTS trg_stock_movements_immutable ON stock_movements")
    op.execute("DROP FUNCTION IF EXISTS pasineh_guard_stock_document()")
    op.execute("DROP FUNCTION IF EXISTS pasineh_immutable_row()")

    op.drop_index('ix_domain_events_aggregate', 'domain_events')
    op.drop_table('domain_events')

    op.drop_constraint('ck_orders_stock_state', 'orders', type_='check')
    op.drop_constraint('uq_orders_idempotency', 'orders', type_='unique')
    for column in ('request_hash', 'idempotency_key', 'stock_state'):
        op.drop_column('orders', column)

    op.drop_index('ix_stock_reservations_reference', 'stock_reservations')
    op.drop_table('stock_reservations')

    # گردش‌های برگشت و تغییر وضعیت (که در مدل قبلی معنا ندارند) با ردیف‌های غیرسالم حذف می‌شوند
    op.execute("DELETE FROM stock_movements WHERE stock_status <> 'available'")
    op.execute("DELETE FROM inventories WHERE stock_status <> 'available'")
    op.drop_constraint('uq_stock_movements_reversal', 'stock_movements', type_='unique')
    op.drop_index('ix_stock_movements_document_id', 'stock_movements')
    _replace_fk('stock_movements', 'inventory_id', 'inventories', 'CASCADE')
    _replace_fk('stock_movements', 'product_id', 'products', 'CASCADE')
    _replace_fk('stock_movements', 'warehouse_id', 'warehouses', 'SET NULL')
    inspector = sa.inspect(bind)
    for fk in inspector.get_foreign_keys('stock_movements'):
        if fk["constrained_columns"] in (["document_id"], ["reversal_of_id"]):
            op.drop_constraint(fk["name"], 'stock_movements', type_='foreignkey')
    for column in ('reversal_of_id', 'stock_status', 'document_id'):
        op.drop_column('stock_movements', column)

    op.drop_index('ix_stock_documents_reference', 'stock_documents')
    op.drop_table('stock_documents')

    op.drop_constraint('ck_inventories_reserve_available_only', 'inventories', type_='check')
    op.drop_constraint('ck_inventories_reserved', 'inventories', type_='check')
    op.drop_constraint('ck_inventories_stock_status', 'inventories', type_='check')
    op.drop_constraint('uq_inventories_bucket', 'inventories', type_='unique')
    _replace_fk('inventories', 'product_id', 'products', 'CASCADE')
    _replace_fk('inventories', 'warehouse_id', 'warehouses', None)
    op.drop_index('ix_inventories_warehouse_id', 'inventories')
    op.alter_column('inventories', 'warehouse_id', nullable=True)
    op.drop_column('inventories', 'reserved_quantity')
    op.drop_column('inventories', 'stock_status')

    op.drop_table('product_suppliers')
    op.drop_table('product_uoms')
    op.drop_table('partners')

    for name in ('ck_products_thresholds', 'ck_products_shelf_life', 'ck_products_expiry_needs_lot',
                 'ck_products_dimensions', 'ck_products_net_weight'):
        op.drop_constraint(name, 'products', type_='check')
    op.drop_constraint('uq_products_org_barcode', 'products', type_='unique')
    for column in ('reorder_point', 'max_stock', 'min_stock', 'shelf_life_days', 'expiry_tracked', 'serial_tracked',
                   'lot_tracked', 'height_cm', 'width_cm', 'length_cm', 'net_weight_kg', 'short_name'):
        op.drop_column('products', column)

    op.drop_constraint('ck_warehouses_parent_self', 'warehouses', type_='check')
    op.drop_constraint('ck_warehouses_type', 'warehouses', type_='check')
    op.drop_constraint('uq_warehouses_org_code', 'warehouses', type_='unique')
    op.drop_index('ix_warehouses_parent_id', 'warehouses')
    for column in ('is_active', 'parent_id', 'type', 'code'):
        op.drop_column('warehouses', column)
