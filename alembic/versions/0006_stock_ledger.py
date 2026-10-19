"""stock ledger: stock_movements + opening balances for existing inventories

Revision ID: 0006_stock_ledger
Revises: 0005_org_onboarding
Create Date: 2026-10-10

۱. جدول stock_movements (دفتر گردش کالا) ساخته می‌شود.
۲. برای هر ردیف موجودی فعلی با مانده غیرصفر، یک گردش «موجودی اولیه» ثبت
   می‌شود تا از همین لحظه «مانده = مجموع گردش‌ها» برقرار باشد.
۳. موجودی هرگز منفی نمی‌شود (CHECK) و ستون quantity اجباری می‌شود.
"""
from alembic import op
import sqlalchemy as sa

revision = '0006_stock_ledger'
down_revision = '0005_org_onboarding'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'stock_movements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('inventory_id', sa.Integer(), sa.ForeignKey('inventories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id', ondelete='SET NULL'), nullable=True),
        sa.Column('movement_type', sa.String(32), nullable=False),
        sa.Column('quantity_change', sa.Integer(), nullable=False),
        sa.Column('balance_after', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(500), nullable=True),
        sa.Column('reference_type', sa.String(32), nullable=True),
        sa.Column('reference_id', sa.Integer(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.CheckConstraint('quantity_change <> 0', name='ck_stock_movements_nonzero'),
    )
    for column in ('id', 'organization_id', 'created_at', 'inventory_id', 'product_id', 'warehouse_id', 'movement_type'):
        op.create_index(f'ix_stock_movements_{column}', 'stock_movements', [column])

    # مانده فعلی هر ردیف موجودی = گردش «موجودی اولیه»
    op.execute("UPDATE inventories SET quantity = 0 WHERE quantity IS NULL")
    op.execute("""
        INSERT INTO stock_movements
            (organization_id, created_at, inventory_id, product_id, warehouse_id,
             movement_type, quantity_change, balance_after, reason)
        SELECT organization_id, now(), id, product_id, warehouse_id,
               'initial', quantity, quantity, 'موجودی اولیه (انتقال از نسخه قبل از دفتر گردش کالا)'
        FROM inventories
        WHERE quantity <> 0
    """)

    op.alter_column('inventories', 'quantity', nullable=False, server_default='0')
    op.create_check_constraint('ck_inventories_quantity_non_negative', 'inventories', 'quantity >= 0')


def downgrade() -> None:
    op.drop_constraint('ck_inventories_quantity_non_negative', 'inventories', type_='check')
    op.alter_column('inventories', 'quantity', nullable=True)
    op.drop_table('stock_movements')
