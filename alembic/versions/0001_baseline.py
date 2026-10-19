"""baseline schema — matches current models.py

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-25

این migration نقطه شروع (baseline) است: دقیقاً همان جدول‌هایی که تا امروز با
Base.metadata.create_all() ساخته می‌شدند را می‌سازد. از این به بعد هر تغییر
مدل باید با یک migration جدید (alembic revision --autogenerate) اضافه شود،
نه با پاک کردن کامل دیتابیس.

اگر این migration را روی دیتابیسی اجرا می‌کنید که از قبل (با create_all)
ساخته شده، ابتدا باید آن را کامل پاک کنید (docker compose down -v) — این
migration فرض می‌کند دیتابیس خالی است.

⚠️ نکته مهم درباره roleenum: کلاس RoleEnum در models.py یک زیرکلاس str/Enum
است (مثلاً ADMIN = "admin"). SQLAlchemy برای چنین enum ای، به‌طور پیش‌فرض
هنگام INSERT از nام عضو (مثل "ADMIN") استفاده می‌کند، نه از مقدار آن
("admin"). به همین دلیل مقادیر enum پایگاه‌داده باید حروف بزرگ باشند.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # مقادیر باید دقیقاً با نام اعضای RoleEnum (نه مقدار آن‌ها) یکی باشند
    role_enum = sa.Enum('ADMIN', 'WAREHOUSE_MANAGER', 'DRIVER', name='roleenum')
    vehicle_type_enum = sa.Enum('motorcycle', 'sedan', 'pickup', 'van', 'truck', name='vehicle_type')
    vehicle_status_enum = sa.Enum('available', 'on_route', 'maintenance', 'inactive', 'busy', name='vehicle_status')
    package_size_enum = sa.Enum('xs', 's', 'm', 'l', 'xl', name='package_size')
    delivery_status_enum = sa.Enum('pending', 'in_transit', 'completed', 'failed', 'assigned', name='delivery_status')

    # ---- warehouses (بدون وابستگی) ----
    op.create_table(
        'warehouses',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('name', sa.String()),
        sa.Column('location', sa.String()),
    )

    # ---- users (وابسته به warehouses، و به vehicles.id که هنوز نساختیم -> nullable FK اضافه می‌شود بعداً) ----
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, index=True, nullable=False),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('username', sa.String(), nullable=False, unique=True, index=True),
        sa.Column('email', sa.String(), nullable=True, unique=True),
        sa.Column('full_name', sa.String(), nullable=True),
        sa.Column('driver_code', sa.String(), unique=True, nullable=True),
        sa.Column('role', role_enum, nullable=False, server_default='DRIVER'),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=True),
        sa.Column('vehicle_id', sa.Integer(), nullable=True),  # FK به vehicles بعد از ساخت جدول vehicles اضافه می‌شود
        sa.Column('city', sa.String(), nullable=True),
    )

    # ---- vehicles (وابسته به users.id برای driver_id) ----
    op.create_table(
        'vehicles',
        sa.Column('id', sa.Integer(), primary_key=True, index=True, nullable=False),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
        sa.Column('license_plate', sa.String(15), nullable=True),
        sa.Column('plate_number', sa.String(), unique=True, nullable=True),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('type', vehicle_type_enum, nullable=True),
        sa.Column('capacity_kg', sa.Integer(), nullable=True),
        sa.Column('max_weight_kg', sa.Float(), nullable=True),
        sa.Column('max_volume_m3', sa.Float(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true()),
        sa.Column('status', vehicle_status_enum, server_default='available'),
        sa.Column('city', sa.String(), nullable=True),
        sa.Column('driver_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=True),
    )

    # حالا که vehicles ساخته شد، FK ستون users.vehicle_id را اضافه می‌کنیم
    op.create_foreign_key('fk_users_vehicle_id', 'users', 'vehicles', ['vehicle_id'], ['id'])

    # ---- items (جدول قدیمی/غیرفعال، برای سازگاری با کد نگه داشته شده) ----
    op.create_table(
        'items',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('name', sa.String()),
        sa.Column('sku', sa.String(), unique=True),
        sa.Column('weight_kg', sa.Float()),
        sa.Column('quantity', sa.Integer()),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id')),
    )

    # ---- products ----
    op.create_table(
        'products',
        sa.Column('id', sa.Integer(), primary_key=True, index=True, nullable=False),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('sku', sa.String(), unique=True, index=True, nullable=False),
        sa.Column('weight_kg', sa.Float(), server_default='1.0'),
        sa.Column('price', sa.Float(), nullable=False, server_default='0.0'),
    )

    # ---- inventories ----
    op.create_table(
        'inventories',
        sa.Column('id', sa.Integer(), primary_key=True, index=True, nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=True),
        sa.Column('quantity', sa.Integer(), server_default='0'),
        sa.Column('reorder_point', sa.Integer(), server_default='10'),
        sa.Column('ever_exceeded_reorder', sa.Boolean(), server_default=sa.false()),
        sa.Column('warehouse_name', sa.String(), server_default='Central Warehouse'),
    )

    # ---- orders ----
    op.create_table(
        'orders',
        sa.Column('id', sa.Integer(), primary_key=True, index=True, nullable=False),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
        sa.Column('destination', sa.String(), nullable=False),
        sa.Column('size', package_size_enum, nullable=False),
        sa.Column('priority', sa.Boolean(), nullable=False),
        sa.Column('delivery_window_start', sa.DateTime(), nullable=False),
        sa.Column('delivery_window_end', sa.DateTime(), nullable=False),
        sa.Column('status', delivery_status_enum, nullable=False),
        sa.Column('vehicle_id', sa.Integer(), sa.ForeignKey('vehicles.id', ondelete='CASCADE'), index=True, nullable=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='SET NULL'), nullable=True),
        sa.Column('quantity', sa.Integer(), server_default='1'),
    )


def downgrade() -> None:
    op.drop_table('orders')
    op.drop_table('inventories')
    op.drop_table('products')
    op.drop_table('items')
    op.drop_constraint('fk_users_vehicle_id', 'users', type_='foreignkey')
    op.drop_table('vehicles')
    op.drop_table('users')
    op.drop_table('warehouses')

    sa.Enum(name='delivery_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='package_size').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='vehicle_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='vehicle_type').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='roleenum').drop(op.get_bind(), checkfirst=True)
