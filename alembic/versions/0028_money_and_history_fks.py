"""مبلغ‌ها دقیق (Numeric به‌جای Float) و حفظ تاریخچه انبارگردانی هنگام حذف کالا/انبار

- ۱۴ ستون پولی: Float ← NUMERIC(18,2) (گردکردن به دو رقم اعشار؛ مبلغ‌های ریالی عدد صحیح‌اند و تغییری نمی‌کنند)
- stocktake_lines.product_id و stocktakes.warehouse_id: ON DELETE CASCADE ← RESTRICT

Revision ID: 0028_money_and_history_fks
Revises: 0027_wms_control
"""
import sqlalchemy as sa
from alembic import op

revision = '0028_money_and_history_fks'
down_revision = '0027_wms_control'
branch_labels = None
depends_on = None

MONEY_COLUMNS = [
    ("products", "price"),
    ("orders", "total_price"), ("orders", "delivery_fee"), ("orders", "commission_amount"), ("orders", "driver_earning"),
    ("order_items", "unit_price"),
    ("commission_plans", "base_fare"), ("commission_plans", "fare_per_kg"),
    ("stocktake_lines", "unit_price"),
    ("product_prices", "base_price"), ("product_prices", "final_price"), ("product_prices", "cost_price"),
    ("backorders", "unit_price"),
    ("product_suppliers", "last_price"),
]

HISTORY_FKS = [
    # (جدول، ستون، جدول مرجع، نام قید)
    ("stocktake_lines", "product_id", "products", "stocktake_lines_product_id_fkey"),
    ("stocktakes", "warehouse_id", "warehouses", "stocktakes_warehouse_id_fkey"),
]


def _retype(table: str, column: str, to_money: bool) -> None:
    if op.get_bind().dialect.name == "postgresql":
        target = "NUMERIC(18, 2)" if to_money else "DOUBLE PRECISION"
        using = f"round({column}::numeric, 2)" if to_money else f"{column}::double precision"
        op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE {target} USING {using}')
    else:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, type_=sa.Numeric(18, 2) if to_money else sa.Float())


def _fk(table: str, column: str, ref: str, name: str, ondelete: str) -> None:
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(name, table, ref, [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    for table, column in MONEY_COLUMNS:
        _retype(table, column, to_money=True)
    for table, column, ref, name in HISTORY_FKS:
        _fk(table, column, ref, name, "RESTRICT")


def downgrade() -> None:
    for table, column, ref, name in HISTORY_FKS:
        _fk(table, column, ref, name, "CASCADE")
    for table, column in MONEY_COLUMNS:
        _retype(table, column, to_money=False)
