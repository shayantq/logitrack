"""
کنترل و آمادگی راه‌اندازی (فصل‌های ۲۲، ۲۷، ۳۴ و ۳۵):
  • RolePermission — تفاوت مجوزهای یک نقش در یک سازمان با پیش‌فرض app/core/permissions.py
  • LabelPrint — سابقه چاپ برچسب کالا، محل و بسته؛ چاپ دوباره فقط با دلیل
  • CutoverCheck — موارد دستی چک‌لیست راه‌اندازی (آموزش، موجودی اول دوره، تأیید بکاپ، …)
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, event

from app.core.tenancy import TenantScoped
from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RolePermission(TenantScoped, Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("organization_id", "role", "permission", name="uq_role_permissions"),
        CheckConstraint("role IN ('org_admin', 'warehouse_manager', 'driver')", name="ck_role_permissions_role"),
    )

    id = Column(Integer, primary_key=True, index=True)
    role = Column(String(32), nullable=False)
    permission = Column(String(48), nullable=False)
    allowed = Column(Boolean, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=_now)
    updated_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class LabelPrint(TenantScoped, Base):
    __tablename__ = "label_prints"
    __table_args__ = (
        CheckConstraint("label_type IN ('product', 'location', 'package')", name="ck_label_prints_type"),
        CheckConstraint("copies > 0 AND copies <= 500", name="ck_label_prints_copies"),
        CheckConstraint("NOT is_reprint OR reason IS NOT NULL", name="ck_label_prints_reason"),
    )

    id = Column(Integer, primary_key=True, index=True)
    label_type = Column(String(16), nullable=False)
    target_id = Column(Integer, nullable=False)
    target_code = Column(String(64), nullable=False)
    copies = Column(Integer, nullable=False)
    is_reprint = Column(Boolean, nullable=False, default=False)
    reason = Column(String(300), nullable=True)
    printed_at = Column(DateTime, nullable=False, default=_now, index=True)
    printed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


# ---------------------------------------------------------------------------
# گزارش فعالیت تغییرناپذیر (فصل ۲۶) — مایگریشن ۰۰۲۷ همین را می‌سازد؛ این برای create_all تست‌های یکپارچگی است
# ---------------------------------------------------------------------------
AUDIT_GUARD_SQL = (
    """
    CREATE OR REPLACE FUNCTION pasineh_guard_audit_log() RETURNS trigger AS $$
    BEGIN
        IF current_setting('pasineh.ledger_maintenance', true) = 'on' THEN
            RETURN COALESCE(NEW, OLD);
        END IF;
        IF TG_OP = 'DELETE' THEN
            IF OLD.organization_id IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM organizations WHERE id = OLD.organization_id) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'audit log rows are immutable' USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.actor_id IS NULL AND (to_jsonb(NEW) - 'actor_id') = (to_jsonb(OLD) - 'actor_id') THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'audit log rows are immutable' USING ERRCODE = 'check_violation';
    END $$ LANGUAGE plpgsql
    """,
    "CREATE TRIGGER trg_audit_logs_guard BEFORE UPDATE OR DELETE ON audit_logs "
    "FOR EACH ROW EXECUTE FUNCTION pasineh_guard_audit_log()",
)


@event.listens_for(Base.metadata, "after_create")
def _create_audit_trigger(target, connection, **kw):
    if connection.dialect.name != "postgresql":
        return
    for statement in AUDIT_GUARD_SQL:
        connection.exec_driver_sql(statement)


class CutoverCheck(TenantScoped, Base):
    __tablename__ = "cutover_checks"
    __table_args__ = (UniqueConstraint("organization_id", "item_key", name="uq_cutover_checks_item"),)

    id = Column(Integer, primary_key=True, index=True)
    item_key = Column(String(48), nullable=False)
    done = Column(Boolean, nullable=False, default=False)
    note = Column(String(500), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=_now)
    updated_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
