"""ورود دومرحله‌ای (TOTP) برای کاربران

Revision ID: 0030_user_totp
Revises: 0029_auth_sessions
"""
import sqlalchemy as sa
from alembic import op

revision = '0030_user_totp'
down_revision = '0029_auth_sessions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("totp_enabled_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("totp_last_step", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "totp_last_step")
    op.drop_column("users", "totp_enabled_at")
    op.drop_column("users", "totp_secret")
