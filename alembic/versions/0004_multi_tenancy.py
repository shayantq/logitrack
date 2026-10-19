"""multi-tenancy: organizations + organization_id on all tenant tables + new roles

Revision ID: 0004_multi_tenancy
Revises: 0003_safe_deletes
Create Date: 2026-10-10

۱. جدول organizations ساخته می‌شود و یک «سازمان پیش‌فرض» برای همه داده‌های
   موجود ایجاد می‌شود.
۲. ستون organization_id به users, warehouses, products, inventories,
   vehicles, orders, notifications اضافه و با سازمان پیش‌فرض پر می‌شود
   (برای users اجباری نیست چون کارکنان پلتفرم سازمان ندارند).
۳. ستون users.role از enum دیتابیس به رشته تبدیل می‌شود (مقدار به‌جای نام:
   ADMIN → admin) و نقش admin قدیمی به org_admin (ادمین سازمان) تغییر می‌کند.
۴. یکتایی SKU و پلاک به «داخل هر سازمان» محدود می‌شود.
۵. جدول قدیمی و بی‌استفاده items حذف می‌شود.
"""
from alembic import op
import sqlalchemy as sa

revision = '0004_multi_tenancy'
down_revision = '0003_safe_deletes'
branch_labels = None
depends_on = None

TENANT_TABLES = ('users', 'warehouses', 'products', 'inventories', 'vehicles', 'orders', 'notifications')
ROLES = ('platform_admin', 'platform_support', 'org_admin', 'warehouse_manager', 'driver')


def upgrade() -> None:
    op.create_table(
        'organizations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('slug', sa.String(64), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index('ix_organizations_id', 'organizations', ['id'])
    op.create_index('ix_organizations_slug', 'organizations', ['slug'], unique=True)

    conn = op.get_bind()
    default_org_id = conn.execute(sa.text(
        "INSERT INTO organizations (created_at, name, slug, is_active) "
        "VALUES (now(), 'سازمان پیش‌فرض', 'default', true) RETURNING id"
    )).scalar_one()

    for table in TENANT_TABLES:
        op.add_column(table, sa.Column('organization_id', sa.Integer(), nullable=True))
        conn.execute(sa.text(f"UPDATE {table} SET organization_id = :org"), {"org": default_org_id})
        if table != 'users':
            op.alter_column(table, 'organization_id', nullable=False)
        op.create_foreign_key(f'{table}_organization_id_fkey', table, 'organizations',
                              ['organization_id'], ['id'], ondelete='CASCADE')
        op.create_index(f'ix_{table}_organization_id', table, ['organization_id'])

    # ---- نقش‌ها: enum دیتابیس (نام‌ها با حروف بزرگ) → رشته (مقدارها) ----
    op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(32) USING lower(role::text)")
    op.execute("UPDATE users SET role = 'org_admin' WHERE role = 'admin'")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'driver'")
    op.execute("DROP TYPE IF EXISTS roleenum")
    op.create_check_constraint('ck_users_role', 'users', "role IN (" + ", ".join(f"'{r}'" for r in ROLES) + ")")
    # قاعده: کاربر سازمانی حتماً سازمان دارد و کارکنان پلتفرم هرگز
    op.create_check_constraint(
        'ck_users_role_organization', 'users',
        "(role IN ('platform_admin', 'platform_support')) = (organization_id IS NULL)"
    )

    # ---- یکتایی در محدوده سازمان ----
    op.drop_index('ix_products_sku', table_name='products')
    op.create_index('ix_products_sku', 'products', ['sku'])
    op.create_unique_constraint('uq_products_org_sku', 'products', ['organization_id', 'sku'])
    op.create_unique_constraint('uq_vehicles_org_plate', 'vehicles', ['organization_id', 'license_plate'])

    op.drop_table('items')


def downgrade() -> None:
    # برگشت به ساختار تک‌سازمانی فقط وقتی امن است که یک سازمان وجود داشته باشد؛
    # با چند سازمان، داده‌ها (مثل SKUهای یکسان) با هم تداخل پیدا می‌کنند
    org_count = op.get_bind().execute(sa.text("SELECT count(*) FROM organizations")).scalar_one()
    if org_count > 1:
        raise RuntimeError(
            f"{org_count} سازمان وجود دارد؛ برگشت به نسخه تک‌سازمانی بدون از دست رفتن داده ممکن نیست. "
            "ابتدا سازمان‌های اضافه را حذف کنید."
        )

    op.create_table(
        'items',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('name', sa.String()),
        sa.Column('sku', sa.String(), unique=True),
        sa.Column('weight_kg', sa.Float()),
        sa.Column('quantity', sa.Integer()),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id')),
    )

    op.drop_constraint('uq_vehicles_org_plate', 'vehicles', type_='unique')
    op.drop_constraint('uq_products_org_sku', 'products', type_='unique')
    op.drop_index('ix_products_sku', table_name='products')
    op.create_index('ix_products_sku', 'products', ['sku'], unique=True)

    op.drop_constraint('ck_users_role_organization', 'users', type_='check')
    op.drop_constraint('ck_users_role', 'users', type_='check')
    # کارکنان پلتفرم در نسخه قبلی معادلی ندارند
    op.execute("DELETE FROM users WHERE role IN ('platform_admin', 'platform_support')")
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'org_admin'")
    op.execute("CREATE TYPE roleenum AS ENUM ('ADMIN', 'WAREHOUSE_MANAGER', 'DRIVER')")
    op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE roleenum USING upper(role)::roleenum")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'DRIVER'")

    for table in reversed(TENANT_TABLES):
        op.drop_index(f'ix_{table}_organization_id', table_name=table)
        op.drop_constraint(f'{table}_organization_id_fkey', table, type_='foreignkey')
        op.drop_column(table, 'organization_id')

    op.drop_index('ix_organizations_slug', table_name='organizations')
    op.drop_index('ix_organizations_id', table_name='organizations')
    op.drop_table('organizations')
