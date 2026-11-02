"""اثر انگشت حساب کاوه‌نگار و پیوند پیام به کد بازیابی

هر دو ستون تهی‌پذیرند و پیام‌های قبلی پر نمی‌شوند: پیام بدون اثر انگشت پاسخ وضعیتش قابل اعتماد نیست و «نامعلوم» می‌ماند.
downgrade این دو ستون را حذف می‌کند؛ پس از آن پیوند کد بازیابی و سنجش حساب از دست می‌رود.

Revision ID: 0045_outbound_account_reset_link
Revises: 0044_outbound_provider_ref
"""
from alembic import op
import sqlalchemy as sa

revision = '0045_outbound_account_reset'
down_revision = '0044_outbound_provider_ref'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('outbound_messages', sa.Column('provider_account', sa.String(64), nullable=True))
    op.add_column('outbound_messages', sa.Column('password_reset_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_outbound_messages_password_reset', 'outbound_messages', 'password_resets', ['password_reset_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_outbound_messages_password_reset', 'outbound_messages', type_='foreignkey')
    op.drop_column('outbound_messages', 'password_reset_id')
    op.drop_column('outbound_messages', 'provider_account')
