"""شناسه پایدار پیام نزد سرویس‌دهنده، وضعیت سرویس‌دهنده و وضعیت «نتیجه نامعلوم»

پیام‌های موجود با همان localid قبلی فرستاده شده‌اند، پس provider_ref = id می‌گیرند. پیش از پر کردن، سازگاری شناسه‌ها
سنجیده می‌شود. downgrade اگر پیام نامعلوم حل‌نشده‌ای باشد متوقف می‌شود، چون آن وضعیت در ساختار قبلی جایی ندارد؛
در غیر این صورت شناسه‌های تصادفی و وضعیت سرویس‌دهنده از دست می‌روند و کد قبلی دوباره شناسه ردیف را localid می‌فرستد.

Revision ID: 0044_outbound_provider_ref
Revises: 0043_export_attempts
"""
from alembic import op
import sqlalchemy as sa

revision = '0044_outbound_provider_ref'
down_revision = '0043_export_attempts'
branch_labels = None
depends_on = None

OLD_STATUSES = "status IN ('pending', 'sending', 'sent', 'skipped', 'failed', 'expired')"
NEW_STATUSES = "status IN ('pending', 'sending', 'sent', 'skipped', 'failed', 'expired', 'unconfirmed')"
LONG_SAFE = 2 ** 53


def upgrade() -> None:
    bind = op.get_bind()
    bad = bind.execute(sa.text("SELECT count(*) FROM outbound_messages WHERE id <= 0 OR id >= :limit"), {"limit": LONG_SAFE}).scalar()
    if bad:
        raise RuntimeError(f"{bad} پیام شناسه‌ای بیرون از بازه localid دارد؛ provider_ref پر نمی‌شود.")
    op.add_column('outbound_messages', sa.Column('provider_ref', sa.BigInteger(), nullable=True))
    op.add_column('outbound_messages', sa.Column('provider_message_id', sa.BigInteger(), nullable=True))
    op.add_column('outbound_messages', sa.Column('provider_status', sa.Integer(), nullable=True))
    op.add_column('outbound_messages', sa.Column('first_attempt_at', sa.DateTime(), nullable=True))
    op.execute("UPDATE outbound_messages SET provider_ref = id")
    op.alter_column('outbound_messages', 'provider_ref', nullable=False)
    op.create_unique_constraint('uq_outbound_messages_provider_ref', 'outbound_messages', ['provider_ref'])
    op.drop_constraint('ck_outbound_messages_status', 'outbound_messages', type_='check')
    op.create_check_constraint('ck_outbound_messages_status', 'outbound_messages', NEW_STATUSES)


def downgrade() -> None:
    open_rows = op.get_bind().execute(sa.text("SELECT count(*) FROM outbound_messages WHERE status = 'unconfirmed'")).scalar()
    if open_rows:
        raise RuntimeError(f"{open_rows} پیام با نتیجه نامعلوم حل نشده است؛ پیش از downgrade آن‌ها را از پنل پلتفرم حل کنید.")
    op.drop_constraint('ck_outbound_messages_status', 'outbound_messages', type_='check')
    op.create_check_constraint('ck_outbound_messages_status', 'outbound_messages', OLD_STATUSES)
    op.drop_constraint('uq_outbound_messages_provider_ref', 'outbound_messages', type_='unique')
    for column in ('first_attempt_at', 'provider_status', 'provider_message_id', 'provider_ref'):
        op.drop_column('outbound_messages', column)
