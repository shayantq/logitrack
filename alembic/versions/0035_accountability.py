"""پاسخگویی: حالت‌های تازه استثنا، تکرار و مدرک، مهلت پاسخ تیکت، و تأیید دونفره اصلاح موجودی

زمان اولین پاسخ تیکت‌های موجود از اولین پیام کارکنان که درخواست‌کننده یا طرف مقابل دیده پر می‌شود.

Revision ID: 0035_accountability
Revises: 0034_field_operations
"""
import sqlalchemy as sa
from alembic import op

revision = '0035_accountability'
down_revision = '0034_field_operations'
branch_labels = None
depends_on = None

OLD_ACTIVE = "'open', 'in_progress', 'waiting'"
NEW_ACTIVE = "'open', 'acknowledged', 'in_progress', 'waiting', 'waiting_external'"


def upgrade() -> None:
    op.drop_index('uq_operation_exceptions_active', table_name='operation_exceptions')
    op.drop_constraint('ck_operation_exceptions_status', 'operation_exceptions', type_='check')
    op.create_check_constraint('ck_operation_exceptions_status', 'operation_exceptions', f"status IN ({NEW_ACTIVE}, 'resolved', 'merged')")
    op.create_index('uq_operation_exceptions_active', 'operation_exceptions', ['organization_id', 'kind', 'entity_type', 'entity_id'],
                    unique=True, postgresql_where=sa.text(f"status IN ({NEW_ACTIVE})"))
    op.add_column('operation_exceptions', sa.Column('occurrence_count', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('operation_exceptions', sa.Column('acknowledged_at', sa.DateTime(), nullable=True))
    op.add_column('operation_exceptions', sa.Column('evidence_refs', sa.JSON(), nullable=True))
    op.add_column('operation_exceptions', sa.Column('resolution_code', sa.String(24), nullable=True))
    op.add_column('operation_exceptions', sa.Column('reminded_at', sa.DateTime(), nullable=True))
    op.add_column('operation_exceptions', sa.Column('escalated_at', sa.DateTime(), nullable=True))

    op.add_column('tickets', sa.Column('first_response_at', sa.DateTime(), nullable=True))
    op.execute("""
        UPDATE tickets SET first_response_at = first.at FROM (
            SELECT ticket_id, min(created_at) AS at FROM ticket_messages
            WHERE author_side IN ('org', 'platform') AND visibility <> 'side' GROUP BY ticket_id
        ) AS first WHERE first.ticket_id = tickets.id
    """)

    op.create_table(
        'adjustment_approvals',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('warehouse_id', sa.Integer(), sa.ForeignKey('warehouses.id', ondelete='SET NULL'), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('reason', sa.String(500), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, index=True),
        sa.Column('requested_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('decided_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('decision_note', sa.String(500), nullable=True),
        sa.CheckConstraint("kind IN ('movement', 'set_balance')", name='ck_adjustment_approvals_kind'),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name='ck_adjustment_approvals_status'),
    )


def downgrade() -> None:
    op.drop_table('adjustment_approvals')
    op.drop_column('tickets', 'first_response_at')
    op.drop_column('operation_exceptions', 'escalated_at')
    op.drop_column('operation_exceptions', 'reminded_at')
    op.drop_column('operation_exceptions', 'resolution_code')
    op.drop_column('operation_exceptions', 'evidence_refs')
    op.drop_column('operation_exceptions', 'acknowledged_at')
    op.drop_column('operation_exceptions', 'occurrence_count')
    op.execute("UPDATE operation_exceptions SET status = 'open' WHERE status = 'acknowledged'")
    op.execute("UPDATE operation_exceptions SET status = 'waiting' WHERE status = 'waiting_external'")
    op.drop_index('uq_operation_exceptions_active', table_name='operation_exceptions')
    op.drop_constraint('ck_operation_exceptions_status', 'operation_exceptions', type_='check')
    op.create_check_constraint('ck_operation_exceptions_status', 'operation_exceptions', f"status IN ({OLD_ACTIVE}, 'resolved', 'merged')")
    op.create_index('uq_operation_exceptions_active', 'operation_exceptions', ['organization_id', 'kind', 'entity_type', 'entity_id'],
                    unique=True, postgresql_where=sa.text(f"status IN ({OLD_ACTIVE})"))
