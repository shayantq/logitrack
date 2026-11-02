"""انقضای رمز موقت

کاربرانی که همین حالا رمز موقت عوض‌نشده دارند (must_change_password) از لحظه این مایگریشن همان مهلت عادی
(TEMP_PASSWORD_TTL، ۲۴ ساعت) را می‌گیرند؛ زمان صدور رمزشان ثبت نشده بود. downgrade فقط ستون را حذف می‌کند.

Revision ID: 0046_temp_password_expiry
Revises: 0045_outbound_account_reset
"""
from alembic import op
import sqlalchemy as sa

revision = '0046_temp_password_expiry'
down_revision = '0045_outbound_account_reset'
branch_labels = None
depends_on = None

TTL_HOURS = 24        # همان app.services.messaging.TEMP_PASSWORD_TTL هنگام نوشتن این مایگریشن


def upgrade() -> None:
    op.add_column('users', sa.Column('temp_password_expires_at', sa.DateTime(), nullable=True))
    op.execute(sa.text("UPDATE users SET temp_password_expires_at = (now() AT TIME ZONE 'utc') + make_interval(hours => :h) WHERE must_change_password")
               .bindparams(h=TTL_HOURS))


def downgrade() -> None:
    op.drop_column('users', 'temp_password_expires_at')
