"""عملیات پلتفرم: تعلیق، پلن، دسترسی موقت پشتیبانی، پرچم قابلیت، خروجی و خروج سازمان

همه سازمان‌های موجود پلن «سازمانی» می‌گیرند تا چیزی برایشان بسته نشود (تصمیم ت۱۱).

Revision ID: 0036_platform_operations
Revises: 0035_accountability
"""
import sqlalchemy as sa
from alembic import op

revision = '0036_platform_operations'
down_revision = '0035_accountability'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('organizations', sa.Column('plan_id', sa.String(16), nullable=False, server_default='enterprise'))
    op.add_column('organizations', sa.Column('plan_version', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('organizations', sa.Column('plan_grace_until', sa.DateTime(), nullable=True))
    op.add_column('organizations', sa.Column('suspended_at', sa.DateTime(), nullable=True))
    op.add_column('organizations', sa.Column('suspension_reason', sa.String(500), nullable=True))
    op.add_column('organizations', sa.Column('deprovision_requested_at', sa.DateTime(), nullable=True))
    op.add_column('organizations', sa.Column('deprovisioned_at', sa.DateTime(), nullable=True))
    op.create_check_constraint('ck_organizations_plan', 'organizations', "plan_id IN ('trial', 'basic', 'pro', 'enterprise')")
    org = lambda: sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True)  # noqa: E731
    op.create_table(
        'plan_changes',
        sa.Column('id', sa.Integer(), primary_key=True, index=True), org(),
        sa.Column('from_plan', sa.String(16), nullable=False),
        sa.Column('to_plan', sa.String(16), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('limits', sa.JSON(), nullable=False),
        sa.Column('modules', sa.JSON(), nullable=False),
        sa.Column('reason', sa.String(500), nullable=True),
        sa.Column('changed_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_table(
        'support_access_grants',
        sa.Column('id', sa.Integer(), primary_key=True, index=True), org(),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('granted_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )
    op.create_table(
        'feature_flags',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('key', sa.String(48), nullable=False, unique=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('kill_switch', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('allowlist', sa.JSON(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )
    op.create_table(
        'tenant_exports',
        sa.Column('id', sa.Integer(), primary_key=True, index=True), org(),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('path', sa.String(255), nullable=True),
        sa.Column('reason', sa.String(500), nullable=True),
        sa.Column('error', sa.String(200), nullable=True),
        sa.Column('requested_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'done', 'failed')", name='ck_tenant_exports_status'),
    )


def downgrade() -> None:
    op.drop_table('tenant_exports')
    op.drop_table('feature_flags')
    op.drop_table('support_access_grants')
    op.drop_table('plan_changes')
    op.drop_constraint('ck_organizations_plan', 'organizations', type_='check')
    for column in ('deprovisioned_at', 'deprovision_requested_at', 'suspension_reason', 'suspended_at', 'plan_grace_until', 'plan_version', 'plan_id'):
        op.drop_column('organizations', column)
