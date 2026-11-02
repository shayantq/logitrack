"""ثبت روش ورود کالا: اسکن یا ورود دستی با کد دلیل (WH-IN-12)

جدول تازه است و داده موجود را تغییر نمی‌دهد. برای ورودهای پیش از این مایگریشن ردیفی ساخته نمی‌شود، چون روش ورودشان ثبت نشده بود.

Revision ID: 0040_inbound_entries
Revises: 0039_warehouse_operator
"""
from alembic import op
import sqlalchemy as sa

revision = '0040_inbound_entries'
down_revision = '0039_warehouse_operator'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'inbound_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('receipt_id', sa.Integer(), sa.ForeignKey('inbound_receipts.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('movement_id', sa.Integer(), sa.ForeignKey('stock_movements.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='SET NULL'), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('entry_mode', sa.String(8), nullable=False),
        sa.Column('scanned_code', sa.String(64), nullable=True),
        sa.Column('reason_code', sa.String(16), nullable=True),
        sa.Column('note', sa.String(300), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("entry_mode IN ('scan', 'manual')", name='ck_inbound_entries_mode'),
        sa.CheckConstraint("reason_code IS NULL OR reason_code IN ('no_barcode', 'label_damaged', 'scanner_down', 'other')", name='ck_inbound_entries_reason'),
        sa.CheckConstraint("entry_mode = 'scan' OR reason_code IS NOT NULL", name='ck_inbound_entries_manual_reason'),
    )


def downgrade() -> None:
    op.drop_table('inbound_entries')
