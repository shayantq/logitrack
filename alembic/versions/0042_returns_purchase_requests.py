"""محل دریافت کالای برگشتی و درخواست خرید با تاریخچه تصمیم

محل دریافت فقط ثبت می‌شود و موجودی را جابه‌جا نمی‌کند. برگشت‌های قدیمی بدون محل می‌مانند، چون محلشان ثبت نشده بود.
رویدادهای درخواست خرید با تریگر تغییرناپذیرند.

Revision ID: 0042_returns_purchase_requests
Revises: 0041_fleet_manager
"""
from alembic import op
import sqlalchemy as sa

revision = '0042_returns_purchase'
down_revision = '0041_fleet_manager'
branch_labels = None
depends_on = None


def _org():
    return sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True)


def upgrade() -> None:
    op.add_column('driver_returns', sa.Column('received_location_id', sa.Integer(), sa.ForeignKey('locations.id', ondelete='SET NULL'), nullable=True))
    op.create_table(
        'purchase_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        _org(),
        sa.Column('code', sa.String(16), nullable=False, unique=True),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id'), nullable=False, index=True),
        sa.Column('status', sa.String(12), nullable=False, index=True),
        sa.Column('note', sa.String(500), nullable=True),
        sa.Column('requested_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'canceled')", name='ck_purchase_requests_status'),
    )
    op.create_table(
        'purchase_request_lines',
        sa.Column('id', sa.Integer(), primary_key=True),
        _org(),
        sa.Column('request_id', sa.Integer(), sa.ForeignKey('purchase_requests.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='SET NULL'), nullable=True),
        sa.Column('product_name', sa.String(200), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('estimated_unit_cost', sa.Float(), nullable=True),
        sa.CheckConstraint('quantity > 0', name='ck_purchase_request_lines_quantity'),
    )
    op.create_table(
        'purchase_request_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        _org(),
        sa.Column('request_id', sa.Integer(), sa.ForeignKey('purchase_requests.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('action', sa.String(12), nullable=False),
        sa.Column('note', sa.String(500), nullable=True),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("action IN ('created', 'approved', 'rejected', 'canceled')", name='ck_purchase_request_events_action'),
    )
    op.execute("CREATE TRIGGER trg_purchase_request_events_immutable BEFORE UPDATE OR DELETE ON purchase_request_events "
               "FOR EACH ROW EXECUTE FUNCTION pasineh_immutable_row()")


def downgrade() -> None:
    op.drop_table('purchase_request_events')
    op.drop_table('purchase_request_lines')
    op.drop_table('purchase_requests')
    op.drop_column('driver_returns', 'received_location_id')
