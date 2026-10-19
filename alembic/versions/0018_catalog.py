"""product catalog: detailed attributes, variants, effective-dated prices with subsidy

Revision ID: 0018_catalog
Revises: 0017_stocktakes
Create Date: 2026-10-13

قیمت فعلی هر کالای موجود به‌عنوان اولین قیمت تاریخ‌دار (از ۱۳۸۰) ثبت می‌شود تا همه سفارش‌های گذشته قیمت مرجع داشته باشند.
"""
from alembic import op
import sqlalchemy as sa

revision = '0018_catalog'
down_revision = '0017_stocktakes'
branch_labels = None
depends_on = None

_COLUMNS = [
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('category', sa.String(100), nullable=True),
    sa.Column('brand', sa.String(100), nullable=True),
    sa.Column('unit', sa.String(32), nullable=False, server_default='عدد'),
    sa.Column('barcode', sa.String(64), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('origin', sa.String(16), nullable=False, server_default='domestic'),
    sa.Column('origin_country', sa.String(64), nullable=True),
    sa.Column('export_eligible', sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column('hs_code', sa.String(16), nullable=True),
    sa.Column('specs', sa.JSON(), nullable=True),
    sa.Column('parent_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='SET NULL'), nullable=True),
    sa.Column('variant_label', sa.String(100), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
]


def upgrade():
    for column in _COLUMNS:
        op.add_column('products', column)
    op.create_index('ix_products_category', 'products', ['category'])
    op.create_index('ix_products_parent_id', 'products', ['parent_id'])
    op.create_table(
        'product_prices',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('base_price', sa.Float(), nullable=False),
        sa.Column('subsidy_percent', sa.Float(), nullable=False, server_default='0'),
        sa.Column('final_price', sa.Float(), nullable=False),
        sa.Column('cost_price', sa.Float(), nullable=True),
        sa.Column('note', sa.String(300), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.UniqueConstraint('product_id', 'effective_from', name='uq_product_prices_day'),
        sa.CheckConstraint('subsidy_percent >= 0 AND subsidy_percent < 100', name='ck_product_prices_subsidy'),
        sa.CheckConstraint('base_price >= 0', name='ck_product_prices_base'),
    )
    op.execute("""
        INSERT INTO product_prices (organization_id, product_id, effective_from, base_price, subsidy_percent, final_price, note, created_at)
        SELECT organization_id, id, DATE '2001-03-21', price, 0, price, 'قیمت اولیه کالا', created_at FROM products
    """)


def downgrade():
    op.drop_table('product_prices')
    op.drop_index('ix_products_parent_id', 'products')
    op.drop_index('ix_products_category', 'products')
    for column in reversed(_COLUMNS):
        op.drop_column('products', column.name)
