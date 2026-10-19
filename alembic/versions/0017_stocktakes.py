"""periodic stocktaking: blind counts by warehouse managers, approval and ledger adjustment by the org admin

Revision ID: 0017_stocktakes
Revises: 0016_tickets
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa

revision = '0017_stocktakes'
down_revision = '0016_tickets'
branch_labels = None
depends_on = None


def _org():
    return sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True)


def upgrade():
    op.add_column('warehouses', sa.Column('stocktake_interval_days', sa.Integer(), nullable=True))
    op.create_table(
        'stocktakes',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('code', sa.String(16), nullable=False, unique=True, index=True),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('title', sa.String(200), nullable=True),
        sa.Column('scope', sa.String(16), nullable=False, server_default='full'),
        sa.Column('status', sa.String(16), nullable=False, server_default='counting', index=True),
        sa.Column('note', sa.String(1000), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, index=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('submitted_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('canceled_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('counting', 'review', 'approved', 'canceled')", name='ck_stocktakes_status'),
        sa.CheckConstraint("scope IN ('full', 'partial')", name='ck_stocktakes_scope'),
    )
    op.create_table(
        'stocktake_lines',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('stocktake_id', sa.Integer(), sa.ForeignKey('stocktakes.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('inventory_id', sa.Integer(), sa.ForeignKey('inventories.id', ondelete='SET NULL'), nullable=True),
        sa.Column('product_name', sa.String(200), nullable=False),
        sa.Column('product_sku', sa.String(64), nullable=True),
        sa.Column('unit_price', sa.Float(), nullable=False, server_default='0'),
        sa.Column('added_during_count', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('counted_qty', sa.Integer(), nullable=True),
        sa.Column('expected_qty', sa.Integer(), nullable=True),
        sa.Column('counted_at', sa.DateTime(), nullable=True),
        sa.Column('counted_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('previous_count', sa.Integer(), nullable=True),
        sa.Column('recount_note', sa.String(300), nullable=True),
        sa.Column('variance_reason', sa.String(32), nullable=True),
        sa.Column('adjustment', sa.Integer(), nullable=True),
        sa.UniqueConstraint('stocktake_id', 'product_id', name='uq_stocktake_lines_product'),
        sa.CheckConstraint('counted_qty IS NULL OR counted_qty >= 0', name='ck_stocktake_lines_counted'),
    )


def downgrade():
    op.drop_table('stocktake_lines')
    op.drop_table('stocktakes')
    op.drop_column('warehouses', 'stocktake_interval_days')
