"""صف پایدار پیام‌های بیرونی، ثبت وظایف شکست‌خورده، و حالت held برای کالای سفارش

Revision ID: 0033_outbox_failures
Revises: 0032_delivery_exceptions
"""
import sqlalchemy as sa
from alembic import op

revision = '0033_outbox_failures'
down_revision = '0032_delivery_exceptions'
branch_labels = None
depends_on = None

OLD_STATES = "'reserved', 'issued', 'released', 'returned'"
NEW_STATES = "'reserved', 'held', 'issued', 'released', 'returned'"


def upgrade() -> None:
    op.drop_constraint('ck_orders_stock_state', 'orders', type_='check')
    op.create_check_constraint('ck_orders_stock_state', 'orders', f"stock_state IN ({NEW_STATES})")
    op.create_table(
        'outbound_messages',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('channel', sa.String(8), nullable=False),
        sa.Column('recipient', sa.String(254), nullable=False),
        sa.Column('subject', sa.String(300), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('sensitive', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('dedupe_key', sa.String(120), nullable=True, unique=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.DateTime(), nullable=False),
        sa.Column('lease_until', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.String(300), nullable=True),
        sa.CheckConstraint("channel IN ('sms', 'email')", name='ck_outbound_messages_channel'),
        sa.CheckConstraint("status IN ('pending', 'sending', 'sent', 'skipped', 'failed', 'expired')", name='ck_outbound_messages_status'),
    )
    op.create_index('ix_outbound_messages_due', 'outbound_messages', ['status', 'next_attempt_at'])
    op.create_table(
        'task_failures',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('task_name', sa.String(80), nullable=False, index=True),
        sa.Column('task_id', sa.String(64), nullable=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('error', sa.String(300), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, index=True),
        sa.Column('replayed_at', sa.DateTime(), nullable=True),
        sa.Column('replayed_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.CheckConstraint("status IN ('failed', 'replayed')", name='ck_task_failures_status'),
    )


def downgrade() -> None:
    op.drop_table('task_failures')
    op.drop_index('ix_outbound_messages_due', table_name='outbound_messages')
    op.drop_table('outbound_messages')
    op.execute("UPDATE orders SET stock_state = 'released' WHERE stock_state = 'held'")
    op.drop_constraint('ck_orders_stock_state', 'orders', type_='check')
    op.create_check_constraint('ck_orders_stock_state', 'orders', f"stock_state IN ({OLD_STATES})")
