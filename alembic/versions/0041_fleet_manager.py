"""نقش مدیر ناوگان

قید نقش فقط گسترده می‌شود. برگشت: اگر کاربر مدیر ناوگان ساخته شده باشد، پیش از downgrade باید نقشش عوض شود.

Revision ID: 0041_fleet_manager
Revises: 0040_inbound_entries
"""
from alembic import op

revision = '0041_fleet_manager'
down_revision = '0040_inbound_entries'
branch_labels = None
depends_on = None

OLD = ("platform_admin", "platform_support", "org_admin", "warehouse_manager", "warehouse_operator", "driver")
NEW = (*OLD, "fleet_manager")


def _roles(roles) -> str:
    return "role IN (" + ", ".join(f"'{r}'" for r in roles) + ")"


def upgrade() -> None:
    op.drop_constraint('ck_users_role', 'users', type_='check')
    op.create_check_constraint('ck_users_role', 'users', _roles(NEW))


def downgrade() -> None:
    op.drop_constraint('ck_users_role', 'users', type_='check')
    op.create_check_constraint('ck_users_role', 'users', _roles(OLD))
