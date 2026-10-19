"""support tickets: customer → organization → platform support

Revision ID: 0016_tickets
Revises: 0015_clean_cities
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa

revision = '0016_tickets'
down_revision = '0015_clean_cities'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tickets',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('code', sa.String(16), nullable=False, unique=True, index=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, index=True),
        sa.Column('last_activity_at', sa.DateTime(), nullable=True, index=True),
        sa.Column('subject', sa.String(200), nullable=False),
        sa.Column('category', sa.String(32), nullable=False),
        sa.Column('priority', sa.String(16), nullable=False, server_default='normal'),
        sa.Column('source', sa.String(16), nullable=False, index=True),
        sa.Column('handler', sa.String(16), nullable=False, index=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='open', index=True),
        sa.Column('waiting_on', sa.String(16), nullable=False, index=True),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('requester_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('requester_name', sa.String(150), nullable=True),
        sa.Column('requester_mobile', sa.String(11), nullable=True),
        sa.Column('access_token', sa.String(48), nullable=True, unique=True, index=True),
        sa.Column('assignee_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('escalated_at', sa.DateTime(), nullable=True),
        sa.Column('escalation_reason', sa.String(1000), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("source IN ('customer', 'driver', 'org')", name='ck_tickets_source'),
        sa.CheckConstraint("handler IN ('org', 'platform')", name='ck_tickets_handler'),
        sa.CheckConstraint("status IN ('open', 'resolved', 'closed')", name='ck_tickets_status'),
        sa.CheckConstraint("waiting_on IN ('requester', 'org', 'platform', 'none')", name='ck_tickets_waiting_on'),
        sa.CheckConstraint("priority IN ('normal', 'high', 'urgent')", name='ck_tickets_priority'),
    )
    op.create_table(
        'ticket_messages',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('ticket_id', sa.Integer(), sa.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('author_side', sa.String(16), nullable=False),
        sa.Column('author_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('author_name', sa.String(150), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('visibility', sa.String(16), nullable=False, server_default='all'),
        sa.Column('attachment_path', sa.String(255), nullable=True),
        sa.Column('attachment_type', sa.String(64), nullable=True),
        sa.CheckConstraint("visibility IN ('all', 'staff', 'side')", name='ck_ticket_messages_visibility'),
        sa.CheckConstraint("author_side IN ('requester', 'org', 'platform', 'system')", name='ck_ticket_messages_side'),
    )


def downgrade():
    op.drop_table('ticket_messages')
    op.drop_table('tickets')
