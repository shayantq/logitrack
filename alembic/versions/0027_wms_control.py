"""WMS control and launch readiness: location-level cycle/blind/full counts with location locks, fine-grained
role permissions per organization, label print log with reprint control, immutable audit log with reasons,
location route sequence for picking paths, cutover checklist

Revision ID: 0027_wms_control
Revises: 0026_wms_fulfillment
Create Date: 2026-10-26
"""
from alembic import op
import sqlalchemy as sa

revision = '0027_wms_control'
down_revision = '0026_wms_fulfillment'
branch_labels = None
depends_on = None

AUDIT_GUARD = """
CREATE OR REPLACE FUNCTION pasineh_guard_audit_log() RETURNS trigger AS $$
BEGIN
    IF current_setting('pasineh.ledger_maintenance', true) = 'on' THEN
        RETURN COALESCE(NEW, OLD);
    END IF;
    IF TG_OP = 'DELETE' THEN
        -- فقط حذف آبشاری همراه با حذف خود سازمان
        IF OLD.organization_id IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM organizations WHERE id = OLD.organization_id) THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'audit log rows are immutable' USING ERRCODE = 'check_violation';
    END IF;
    -- تنها تغییر مجاز: خالی شدن انجام‌دهنده وقتی کاربرش حذف می‌شود (نام او در actor_name می‌ماند)
    IF NEW.actor_id IS NULL AND (to_jsonb(NEW) - 'actor_id') = (to_jsonb(OLD) - 'actor_id') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'audit log rows are immutable' USING ERRCODE = 'check_violation';
END $$ LANGUAGE plpgsql
"""


def _org():
    return sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, index=True)


def _user_fk(name: str):
    return sa.Column(name, sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)


def upgrade():
    # ---- فصل ۱۶: نوع شمارش، شمارش کور/راهنما، قفل محل و شمارش در سطح محل ----
    op.add_column('stocktakes', sa.Column('count_type', sa.String(16), nullable=False, server_default='full'))
    op.add_column('stocktakes', sa.Column('blind', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('stocktakes', sa.Column('freeze_mode', sa.String(16), nullable=False, server_default='snapshot'))
    op.add_column('stocktakes', sa.Column('by_location', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('stocktakes', sa.Column('location_ids', sa.JSON(), nullable=True))
    op.add_column('stocktakes', sa.Column('approval_note', sa.String(500), nullable=True))
    op.execute("UPDATE stocktakes SET count_type = CASE WHEN scope = 'full' THEN 'full' ELSE 'partial' END")
    op.create_check_constraint('ck_stocktakes_count_type', 'stocktakes', "count_type IN ('full', 'partial', 'cycle')")
    op.create_check_constraint('ck_stocktakes_freeze_mode', 'stocktakes', "freeze_mode IN ('snapshot', 'lock')")

    op.add_column('stocktake_lines', sa.Column('location_id', sa.Integer(), sa.ForeignKey('locations.id', ondelete='SET NULL'),
                                               nullable=True))
    op.add_column('stocktake_lines', sa.Column('location_code', sa.String(32), nullable=True))
    op.drop_constraint('uq_stocktake_lines_product', 'stocktake_lines', type_='unique')
    op.create_unique_constraint('uq_stocktake_lines_product', 'stocktake_lines', ['stocktake_id', 'product_id', 'location_id'],
                                postgresql_nulls_not_distinct=True)

    op.add_column('locations', sa.Column('count_lock_id', sa.Integer(), sa.ForeignKey('stocktakes.id', ondelete='SET NULL'),
                                         nullable=True, index=True))
    # فصل ۳۰: ترتیب مسیر برداشت (خالی = مسیر مارپیچ خودکار از روی کد محل)
    op.add_column('locations', sa.Column('route_sequence', sa.Integer(), nullable=True))

    # ---- فصل ۲۲: مجوزهای ریز هر نقش در هر سازمان (فقط تفاوت با پیش‌فرض ذخیره می‌شود) ----
    op.create_table(
        'role_permissions',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('role', sa.String(32), nullable=False),
        sa.Column('permission', sa.String(48), nullable=False),
        sa.Column('allowed', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        _user_fk('updated_by_id'),
        sa.UniqueConstraint('organization_id', 'role', 'permission', name='uq_role_permissions'),
        sa.CheckConstraint("role IN ('org_admin', 'warehouse_manager', 'driver')", name='ck_role_permissions_role'),
    )

    # ---- فصل ۲۶: دلیل در گزارش فعالیت و تغییرناپذیری آن ----
    op.add_column('audit_logs', sa.Column('reason', sa.String(500), nullable=True))
    op.create_index('ix_audit_logs_target', 'audit_logs', ['target_type', 'target_id'])
    op.execute(AUDIT_GUARD)
    op.execute("CREATE TRIGGER trg_audit_logs_guard BEFORE UPDATE OR DELETE ON audit_logs "
               "FOR EACH ROW EXECUTE FUNCTION pasineh_guard_audit_log()")

    # ---- فصل ۲۷: سابقه چاپ برچسب (چاپ مجدد با دلیل) ----
    op.create_table(
        'label_prints',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('label_type', sa.String(16), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('target_code', sa.String(64), nullable=False),
        sa.Column('copies', sa.Integer(), nullable=False),
        sa.Column('is_reprint', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.String(300), nullable=True),
        sa.Column('printed_at', sa.DateTime(), nullable=False, index=True),
        _user_fk('printed_by_id'),
        sa.CheckConstraint("label_type IN ('product', 'location', 'package')", name='ck_label_prints_type'),
        sa.CheckConstraint("copies > 0 AND copies <= 500", name='ck_label_prints_copies'),
        sa.CheckConstraint("NOT is_reprint OR reason IS NOT NULL", name='ck_label_prints_reason'),
    )
    op.create_index('ix_label_prints_target', 'label_prints', ['organization_id', 'label_type', 'target_id'])

    # ---- فصل ۳۴ و ۳۵: چک‌لیست راه‌اندازی (موارد دستی) ----
    op.create_table(
        'cutover_checks',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        _org(),
        sa.Column('item_key', sa.String(48), nullable=False),
        sa.Column('done', sa.Boolean(), nullable=False),
        sa.Column('note', sa.String(500), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        _user_fk('updated_by_id'),
        sa.UniqueConstraint('organization_id', 'item_key', name='uq_cutover_checks_item'),
    )


def downgrade():
    op.drop_table('cutover_checks')
    op.drop_index('ix_label_prints_target', table_name='label_prints')
    op.drop_table('label_prints')
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_guard ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS pasineh_guard_audit_log()")
    op.drop_index('ix_audit_logs_target', table_name='audit_logs')
    op.drop_column('audit_logs', 'reason')
    op.drop_table('role_permissions')
    op.drop_column('locations', 'route_sequence')
    op.drop_column('locations', 'count_lock_id')
    op.execute("DELETE FROM stocktake_lines WHERE location_id IS NOT NULL")
    op.drop_constraint('uq_stocktake_lines_product', 'stocktake_lines', type_='unique')
    op.create_unique_constraint('uq_stocktake_lines_product', 'stocktake_lines', ['stocktake_id', 'product_id'])
    op.drop_column('stocktake_lines', 'location_code')
    op.drop_column('stocktake_lines', 'location_id')
    op.drop_constraint('ck_stocktakes_freeze_mode', 'stocktakes', type_='check')
    op.drop_constraint('ck_stocktakes_count_type', 'stocktakes', type_='check')
    for column in ('approval_note', 'location_ids', 'by_location', 'freeze_mode', 'blind', 'count_type'):
        op.drop_column('stocktakes', column)
