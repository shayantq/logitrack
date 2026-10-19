"""users section: account status, temp passwords, lockout, token versions; audit_logs

Revision ID: 0020_users_audit
Revises: 0019_brand_color
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa

revision = '0020_users_audit'
down_revision = '0019_brand_color'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('mobile', sa.String(11), nullable=True))
    op.add_column('users', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('users', sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('users', sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('failed_logins', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('locked_until', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(), nullable=True))
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('actor_name', sa.String(150), nullable=True),
        sa.Column('action', sa.String(48), nullable=False),
        sa.Column('category', sa.String(16), nullable=False),
        sa.Column('target_type', sa.String(32), nullable=True),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('target_label', sa.String(200), nullable=True),
        sa.Column('summary', sa.String(500), nullable=False),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('ip', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(255), nullable=True),
    )
    for col in ('id', 'organization_id', 'created_at', 'actor_id', 'action', 'category', 'target_id'):
        op.create_index(f'ix_audit_logs_{col}', 'audit_logs', [col])


def downgrade():
    op.drop_table('audit_logs')
    for col in ('last_login_at', 'locked_until', 'failed_logins', 'token_version', 'must_change_password', 'is_active', 'mobile'):
        op.drop_column('users', col)
