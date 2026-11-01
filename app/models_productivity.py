"""
بهره‌وری عملیات (docs/productivity.md):
  • SavedView — نمای ذخیره‌شده یک فهرست (فیلترهای همان آدرس صفحه)؛ برای خود کاربر یا مشترک با یک نقش
  • DeliveryAttempt — هر تلاش تحویل: مدرک تحویل موفق، یا دلیل و تعیین تکلیف تلاش ناموفق
  • OperationException — کاری که از روند عادی خارج شده، با مسئول، مهلت و تاریخچه
  • OutboundMessage — پیامک و ایمیل در صف پایدار (همان تراکنش عملیات)
  • TaskFailure — وظیفه پس‌زمینه شکست‌خورده، برای دیدن و اجرای دوباره
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import relationship

from app.core.tenancy import TenantScoped
from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


SAVED_VIEW_PAGES = ("orders", "receipts", "inventory", "transfers", "tickets")


class SavedView(TenantScoped, Base):
    __tablename__ = "saved_views"
    __table_args__ = (
        UniqueConstraint("owner_id", "page_key", "name", name="uq_saved_views_owner_page_name"),
        CheckConstraint("page_key IN ('orders', 'receipts', 'inventory', 'transfers', 'tickets')", name="ck_saved_views_page"),
        CheckConstraint("shared_role IS NULL OR shared_role IN ('org_admin', 'warehouse_manager')", name="ck_saved_views_role"),
    )

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    page_key = Column(String(16), nullable=False)
    name = Column(String(60), nullable=False)
    filters = Column(JSON, nullable=False, default=dict)
    shared_role = Column(String(32), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)

    owner = relationship("User")


class DeliveryAttempt(TenantScoped, Base):
    """یک تلاش تحویل. نتیجه و مدرک آن در همین سطر می‌ماند؛ تعیین تکلیف تلاش ناموفق هم روی آخرین سطر ثبت می‌شود."""
    __tablename__ = "delivery_attempts"
    __table_args__ = (
        UniqueConstraint("order_id", "attempt_no", name="uq_delivery_attempts_order_no"),
        CheckConstraint("outcome IN ('delivered', 'failed')", name="ck_delivery_attempts_outcome"),
        CheckConstraint("recipient_role IS NULL OR recipient_role IN ('self', 'family', 'colleague', 'guard', 'other')",
                        name="ck_delivery_attempts_recipient_role"),
        CheckConstraint("failure_reason IS NULL OR failure_reason IN ('recipient_absent', 'wrong_address', 'refused', 'damaged', "
                        "'access_issue', 'vehicle_issue', 'other')", name="ck_delivery_attempts_reason"),
        CheckConstraint("resolution IS NULL OR resolution IN ('redeliver', 'return_to_warehouse', 'dispute')",
                        name="ck_delivery_attempts_resolution"),
        CheckConstraint("photo_type IS NULL OR photo_type IN ('delivery', 'damage', 'door', 'other')",
                        name="ck_delivery_attempts_photo_type"),
    )

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_no = Column(Integer, nullable=False)
    driver_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    outcome = Column(String(16), nullable=False)
    at = Column(DateTime, nullable=False, default=_now, index=True)
    recipient_name = Column(String(150), nullable=True)
    recipient_role = Column(String(16), nullable=True)
    photo_path = Column(String(255), nullable=True)
    photo_type = Column(String(16), nullable=True)
    exception_note = Column(String(500), nullable=True)      # کمبود یا آسیب هنگام تحویل
    failure_reason = Column(String(24), nullable=True)
    note = Column(String(500), nullable=True)
    next_attempt_at = Column(DateTime, nullable=True)        # پیشنهاد راننده برای تلاش بعدی
    resolution = Column(String(24), nullable=True)
    resolved_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)


ACTIVE_EXCEPTION_STATUSES = ("open", "in_progress", "waiting")


class OperationException(TenantScoped, Base):
    """برای هر مورد فقط یک استثنای باز هست (ایندکس یکتای جزئی)؛ این همان قاعده ادغام موارد تکراری است."""
    __tablename__ = "operation_exceptions"
    __table_args__ = (
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="ck_operation_exceptions_severity"),
        CheckConstraint("team IN ('warehouse', 'fleet', 'support', 'management')", name="ck_operation_exceptions_team"),
        CheckConstraint("status IN ('open', 'in_progress', 'waiting', 'resolved', 'merged')", name="ck_operation_exceptions_status"),
        Index("uq_operation_exceptions_active", "organization_id", "kind", "entity_type", "entity_id", unique=True,
              postgresql_where=text("status IN ('open', 'in_progress', 'waiting')"),
              sqlite_where=text("status IN ('open', 'in_progress', 'waiting')")),
    )

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(32), nullable=False, index=True)
    entity_type = Column(String(16), nullable=False)
    entity_id = Column(Integer, nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True, index=True)
    severity = Column(String(16), nullable=False)
    team = Column(String(16), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(16), nullable=False, default="open", index=True)
    opened_at = Column(DateTime, nullable=False, default=_now, index=True)
    due_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    trigger_reason = Column(String(300), nullable=False)
    suggested_action = Column(String(300), nullable=True)
    resolution = Column(String(500), nullable=True)
    resolved_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)   # خالی = حل خودکار سیستم
    merged_into_id = Column(Integer, ForeignKey("operation_exceptions.id", ondelete="SET NULL"), nullable=True)


class OperationExceptionEvent(TenantScoped, Base):
    """تاریخچه رسیدگی: چه کسی، چه وقت، چه تغییری، با چه یادداشتی."""
    __tablename__ = "operation_exception_events"

    id = Column(Integer, primary_key=True, index=True)
    exception_id = Column(Integer, ForeignKey("operation_exceptions.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(120), nullable=False)
    note = Column(String(500), nullable=True)
    at = Column(DateTime, nullable=False, default=_now)


MESSAGE_ACTIVE_STATUSES = ("pending", "sending")


class OutboundMessage(Base):
    """
    پیام بیرونی در صف پایدار. سازمانی نیست چون پیام‌های درخواست سازمان و بازیابی رمز به هیچ سازمانی وابسته نیستند
    و ناشر برای همه سازمان‌ها کار می‌کند. متن فقط تا پایان ارسال می‌ماند (app/services/outbox_service.py).
    """
    __tablename__ = "outbound_messages"
    __table_args__ = (
        CheckConstraint("channel IN ('sms', 'email')", name="ck_outbound_messages_channel"),
        CheckConstraint("status IN ('pending', 'sending', 'sent', 'skipped', 'failed', 'expired')", name="ck_outbound_messages_status"),
        Index("ix_outbound_messages_due", "status", "next_attempt_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    channel = Column(String(8), nullable=False)
    recipient = Column(String(254), nullable=False)
    subject = Column(String(300), nullable=True)
    body = Column(Text, nullable=True)
    sensitive = Column(Boolean, nullable=False, default=False, server_default="false")
    dedupe_key = Column(String(120), nullable=True, unique=True)
    status = Column(String(16), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at = Column(DateTime, nullable=False, default=_now)
    lease_until = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    sent_at = Column(DateTime, nullable=True)
    last_error = Column(String(300), nullable=True)


class TaskFailure(Base):
    """وظیفه‌ای که شکست خورد. ورودی‌های وظیفه عمداً ذخیره نمی‌شوند تا داده شخصی اینجا نیاید."""
    __tablename__ = "task_failures"
    __table_args__ = (CheckConstraint("status IN ('failed', 'replayed')", name="ck_task_failures_status"),)

    id = Column(Integer, primary_key=True, index=True)
    task_name = Column(String(80), nullable=False, index=True)
    task_id = Column(String(64), nullable=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    error = Column(String(300), nullable=False)
    status = Column(String(16), nullable=False, default="failed", index=True)
    created_at = Column(DateTime, nullable=False, default=_now, index=True)
    replayed_at = Column(DateTime, nullable=True)
    replayed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
