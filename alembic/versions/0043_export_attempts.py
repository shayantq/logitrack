"""اجرای خروجی سازمان با توکن و lease، و تلاش دوباره به‌صورت ردیف تازه

ستون‌ها تهی‌پذیرند و ردیف‌های قدیمی دست نمی‌خورند. خروجی‌ای که پیش از این مایگریشن در pending مانده توکن ندارد و
شروع‌نشده دیده می‌شود، پس خودکار ناموفق نمی‌شود و فقط هشدار می‌گیرد.
downgrade زنجیره تلاش‌ها و توکن اجراها را حذف می‌کند؛ وضعیت ردیف‌ها همان می‌ماند.

Revision ID: 0043_export_attempts
Revises: 0042_returns_purchase
"""
from alembic import op
import sqlalchemy as sa

revision = '0043_export_attempts'
down_revision = '0042_returns_purchase'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tenant_exports', sa.Column('run_token', sa.String(32), nullable=True))
    op.add_column('tenant_exports', sa.Column('started_at', sa.DateTime(), nullable=True))
    op.add_column('tenant_exports', sa.Column('lease_until', sa.DateTime(), nullable=True))
    op.add_column('tenant_exports', sa.Column('retry_of_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_tenant_exports_retry_of', 'tenant_exports', 'tenant_exports', ['retry_of_id'], ['id'], ondelete='SET NULL')
    op.create_unique_constraint('uq_tenant_exports_retry_of', 'tenant_exports', ['retry_of_id'])


def downgrade() -> None:
    op.drop_constraint('uq_tenant_exports_retry_of', 'tenant_exports', type_='unique')
    op.drop_constraint('fk_tenant_exports_retry_of', 'tenant_exports', type_='foreignkey')
    for column in ('retry_of_id', 'lease_until', 'started_at', 'run_token'):
        op.drop_column('tenant_exports', column)
