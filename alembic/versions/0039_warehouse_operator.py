"""نقش اپراتور انبار و برداشتن کار از صف

قید نقش فقط گسترده می‌شود و ستون‌های تازه تهی‌پذیرند، پس داده موجود عوض نمی‌شود و بازنویسی جدول لازم نیست.
برگشت: اگر کاربر اپراتور ساخته شده باشد، پیش از downgrade باید نقشش عوض شود؛ وگرنه قید قدیمی برقرار نمی‌شود.

Revision ID: 0039_warehouse_operator
Revises: 0038_delivery_evidence
"""
from alembic import op
import sqlalchemy as sa

revision = '0039_warehouse_operator'
down_revision = '0038_delivery_evidence'
branch_labels = None
depends_on = None

OLD = ("platform_admin", "platform_support", "org_admin", "warehouse_manager", "driver")
NEW = (*OLD, "warehouse_operator")
TABLES = ("pick_lines", "putaway_tasks")


def _roles(roles) -> str:
    return "role IN (" + ", ".join(f"'{r}'" for r in roles) + ")"


def upgrade() -> None:
    op.drop_constraint('ck_users_role', 'users', type_='check')
    op.create_check_constraint('ck_users_role', 'users', _roles(NEW))
    for table in TABLES:
        op.add_column(table, sa.Column('claimed_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))
        op.add_column(table, sa.Column('claimed_until', sa.DateTime(), nullable=True))


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, 'claimed_until')
        op.drop_column(table, 'claimed_by_id')
    op.drop_constraint('ck_users_role', 'users', type_='check')
    op.create_check_constraint('ck_users_role', 'users', _roles(OLD))
