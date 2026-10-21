"""password_resets: one-time codes for self-service password recovery (SMS or email)

Revision ID: 0023_password_resets
Revises: 0022_rich_notifications
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = '0023_password_resets'
down_revision = '0022_rich_notifications'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'password_resets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('code_hash', sa.String(64), nullable=False),
        sa.Column('channel', sa.String(8), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, index=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('used_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('password_resets')
