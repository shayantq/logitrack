"""order redesign: customers, multi-item orders, tracking code, address, status history

Revision ID: 0007_order_redesign
Revises: 0006_stock_ledger
Create Date: 2026-10-10

۱. جدول‌های customers، order_items و order_status_history ساخته می‌شوند.
۲. هر سفارش قبلی (یک کالا) به یک قلم در order_items تبدیل می‌شود — با نام،
   کد، قیمت و وزن فعلی کالا به‌عنوان «قیمت لحظه ثبت».
۳. مقصد قبلی (فقط نام شهر) به destination_city منتقل و استانش تعیین می‌شود.
۴. هر سفارش یک کد پیگیری یکتا می‌گیرد.
۵. وضعیت از enum دیتابیس به رشته تبدیل می‌شود و completed → delivered.
۶. برای هر سفارش قبلی یک ردیف تاریخچه (وضعیت فعلی) ثبت می‌شود.
"""
import secrets

from alembic import op
import sqlalchemy as sa

revision = '0007_order_redesign'
down_revision = '0006_stock_ledger'
branch_labels = None
depends_on = None

ORDER_STATUSES = ("pending", "assigned", "picking_up", "picked_up", "in_transit", "delivered", "failed", "canceled", "expired")
# شهرهای موجود در داده‌های قبلی → استان
CITY_PROVINCE = {
    "تهران": "تهران", "تبریز": "آذربایجان شرقی", "مشهد": "خراسان رضوی", "اصفهان": "اصفهان",
    "شیراز": "فارس", "کرج": "البرز", "اهواز": "خوزستان", "قم": "قم", "رشت": "گیلان",
    "قزوین": "قزوین", "تاکستان": "قزوین", "آبیک": "قزوین", "کاشان": "اصفهان", "یزد": "یزد",
    "کرمان": "کرمان", "همدان": "همدان", "اراک": "مرکزی", "ساری": "مازندران", "زنجان": "زنجان",
    "ارومیه": "آذربایجان غربی", "اردبیل": "اردبیل", "سنندج": "کردستان", "کرمانشاه": "کرمانشاه",
    "بندرعباس": "هرمزگان", "بوشهر": "بوشهر", "گرگان": "گلستان", "زاهدان": "سیستان و بلوچستان",
}
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # بدون O/0/I/1 برای خوانایی


def _tracking_code() -> str:
    return "LT-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


def upgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        'customers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('mobile', sa.String(11), nullable=False),
        sa.Column('email', sa.String(254), nullable=True),
        sa.UniqueConstraint('organization_id', 'mobile', name='uq_customers_org_mobile'),
    )
    for column in ('id', 'organization_id', 'mobile'):
        op.create_index(f'ix_customers_{column}', 'customers', [column])

    # ---- ستون‌های جدید سفارش ----
    for column in (
        sa.Column('tracking_code', sa.String(16), nullable=True),
        sa.Column('notes', sa.String(1000), nullable=True),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id', ondelete='SET NULL'), nullable=True),
        sa.Column('recipient_name', sa.String(150), nullable=True),
        sa.Column('recipient_mobile', sa.String(11), nullable=True),
        sa.Column('destination_province', sa.String(64), nullable=True),
        sa.Column('destination_city', sa.String(64), nullable=True),
        sa.Column('destination_address', sa.String(500), nullable=True),
        sa.Column('destination_postal_code', sa.String(10), nullable=True),
        sa.Column('total_quantity', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_weight_kg', sa.Float(), nullable=False, server_default='0'),
        sa.Column('total_price', sa.Float(), nullable=False, server_default='0'),
    ):
        op.add_column('orders', column)

    op.create_table(
        'order_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='SET NULL'), nullable=True),
        sa.Column('product_name', sa.String(200), nullable=False),
        sa.Column('product_sku', sa.String(64), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('unit_price', sa.Float(), nullable=False, server_default='0'),
        sa.Column('unit_weight_kg', sa.Float(), nullable=False, server_default='0'),
        sa.CheckConstraint('quantity > 0', name='ck_order_items_quantity_positive'),
    )
    for column in ('id', 'organization_id', 'order_id', 'product_id'):
        op.create_index(f'ix_order_items_{column}', 'order_items', [column])

    op.create_table(
        'order_status_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False),
        sa.Column('from_status', sa.String(32), nullable=True),
        sa.Column('to_status', sa.String(32), nullable=False),
        sa.Column('changed_at', sa.DateTime(), nullable=False),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('note', sa.String(500), nullable=True),
    )
    for column in ('id', 'organization_id', 'order_id'):
        op.create_index(f'ix_order_status_history_{column}', 'order_status_history', [column])

    # ---- وضعیت: enum → رشته، completed → delivered ----
    op.execute("ALTER TABLE orders ALTER COLUMN status TYPE VARCHAR(32) USING status::text")
    op.execute("UPDATE orders SET status = 'delivered' WHERE status = 'completed'")
    op.execute("DROP TYPE IF EXISTS delivery_status")

    # ---- انتقال داده هر سفارش ----
    orders = conn.execute(sa.text("""
        SELECT o.id, o.organization_id, o.destination, o.product_id, o.quantity, o.status, o.created_at,
               p.name, p.sku, p.price, p.weight_kg
        FROM orders o LEFT JOIN products p ON p.id = o.product_id
    """)).fetchall()
    used_codes = set()
    for row in orders:
        code = _tracking_code()
        while code in used_codes:
            code = _tracking_code()
        used_codes.add(code)

        quantity = row.quantity or 1
        unit_price = row.price or 0
        unit_weight = row.weight_kg or 0
        conn.execute(sa.text("""
            UPDATE orders SET tracking_code = :code, destination_city = :city, destination_province = :province,
                   total_quantity = :qty, total_weight_kg = :weight, total_price = :price
            WHERE id = :id
        """), {"code": code, "city": row.destination, "province": CITY_PROVINCE.get((row.destination or "").strip()),
               "qty": quantity, "weight": unit_weight * quantity, "price": unit_price * quantity, "id": row.id})
        conn.execute(sa.text("""
            INSERT INTO order_items (organization_id, order_id, product_id, product_name, product_sku, quantity, unit_price, unit_weight_kg)
            VALUES (:org, :order_id, :product_id, :name, :sku, :qty, :price, :weight)
        """), {"org": row.organization_id, "order_id": row.id, "product_id": row.product_id,
               "name": row.name or "کالای حذف‌شده", "sku": row.sku, "qty": quantity,
               "price": unit_price, "weight": unit_weight})
        conn.execute(sa.text("""
            INSERT INTO order_status_history (organization_id, order_id, from_status, to_status, changed_at, note)
            VALUES (:org, :order_id, NULL, :status, COALESCE(:created_at, now()), 'وضعیت منتقل‌شده از نسخه قبل')
        """), {"org": row.organization_id, "order_id": row.id, "status": row.status, "created_at": row.created_at})

    # ---- قیدها و حذف ستون‌های قدیمی ----
    op.alter_column('orders', 'tracking_code', nullable=False)
    op.alter_column('orders', 'destination_city', nullable=False)
    op.create_index('ix_orders_tracking_code', 'orders', ['tracking_code'], unique=True)
    for column in ('created_at', 'status', 'delivery_window_end', 'customer_id', 'destination_province', 'destination_city'):
        op.create_index(f'ix_orders_{column}', 'orders', [column])
    op.create_check_constraint('ck_orders_status', 'orders', "status IN (" + ", ".join(f"'{s}'" for s in ORDER_STATUSES) + ")")

    op.drop_constraint('orders_product_id_fkey', 'orders', type_='foreignkey')
    op.drop_column('orders', 'product_id')
    op.drop_column('orders', 'quantity')
    op.drop_column('orders', 'destination')


def downgrade() -> None:
    conn = op.get_bind()
    op.add_column('orders', sa.Column('destination', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='SET NULL'), nullable=True))
    op.add_column('orders', sa.Column('quantity', sa.Integer(), server_default='1'))
    # نسخه قبل فقط یک کالا در هر سفارش داشت: اولین قلم برگردانده می‌شود
    conn.execute(sa.text("""
        UPDATE orders o SET destination = o.destination_city,
               product_id = i.product_id, quantity = i.quantity
        FROM (SELECT DISTINCT ON (order_id) order_id, product_id, quantity FROM order_items ORDER BY order_id, id) i
        WHERE i.order_id = o.id
    """))
    op.execute("UPDATE orders SET destination = destination_city WHERE destination IS NULL")
    op.alter_column('orders', 'destination', nullable=False)

    op.drop_constraint('ck_orders_status', 'orders', type_='check')
    op.execute("""
        UPDATE orders SET status = CASE status
            WHEN 'delivered' THEN 'completed'
            WHEN 'picking_up' THEN 'in_transit' WHEN 'picked_up' THEN 'in_transit'
            WHEN 'canceled' THEN 'failed' WHEN 'expired' THEN 'failed'
            ELSE status END
    """)
    op.execute("CREATE TYPE delivery_status AS ENUM ('pending', 'in_transit', 'completed', 'failed', 'assigned')")
    op.execute("ALTER TABLE orders ALTER COLUMN status TYPE delivery_status USING status::delivery_status")

    for column in ('created_at', 'status', 'delivery_window_end', 'customer_id', 'destination_province', 'destination_city'):
        op.drop_index(f'ix_orders_{column}', table_name='orders')
    op.drop_index('ix_orders_tracking_code', table_name='orders')
    op.drop_table('order_status_history')
    op.drop_table('order_items')
    for column in ('total_price', 'total_weight_kg', 'total_quantity', 'destination_postal_code', 'destination_address',
                   'destination_city', 'destination_province', 'recipient_mobile', 'recipient_name', 'customer_id',
                   'notes', 'tracking_code'):
        op.drop_column('orders', column)
    op.drop_table('customers')
