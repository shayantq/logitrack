"""افزونه pg_stat_statements برای رتبه‌بندی کوئری‌های گران

جمع‌آوری آمار به shared_preload_libraries در docker-compose.yml نیاز دارد؛ بدون آن افزونه فقط نصب است و خوانده نمی‌شود.

Revision ID: 0037_pg_stat_statements
Revises: 0036_platform_operations
"""
from alembic import op

revision = '0037_pg_stat_statements'
down_revision = '0036_platform_operations'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_stat_statements")
