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
    JSON, Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text,
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
    partial = Column(Boolean, nullable=False, default=False, server_default="false")

    lines = relationship("DeliveryAttemptLine", cascade="all, delete-orphan", order_by="DeliveryAttemptLine.id")


class DeliveryAttemptLine(TenantScoped, Base):
    """مقدار تحویل‌شده و برگشتی هر قلم در یک تلاش تحویل (فقط وقتی تحویل جزئی است)."""
    __tablename__ = "delivery_attempt_lines"
    __table_args__ = (CheckConstraint("delivered_quantity >= 0 AND returned_quantity >= 0", name="ck_delivery_attempt_lines_quantity"),)

    id = Column(Integer, primary_key=True, index=True)
    attempt_id = Column(Integer, ForeignKey("delivery_attempts.id", ondelete="CASCADE"), nullable=False, index=True)
    order_item_id = Column(Integer, ForeignKey("order_items.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    product_name = Column(String(200), nullable=False)
    delivered_quantity = Column(Integer, nullable=False)
    returned_quantity = Column(Integer, nullable=False)
    reason = Column(String(300), nullable=True)


DELIVERY_METHODS = ("handed_to_recipient", "left_at_door", "other")
EVIDENCE_METHODS = (*DELIVERY_METHODS, "unrecorded")


class DeliveryEvidence(TenantScoped, Base):
    """
    یک فایل مدرک تحویل. ردیف با تریگر تغییرناپذیر است و متن آزاد ندارد (توضیح در DeliveryEvidenceNote).
    delivery_method روش تحویل را می‌گوید و هویت گیرنده را تأیید نمی‌کند. unrecorded فقط برای داده پیش از این جدول است.
    """
    __tablename__ = "delivery_evidence"
    __table_args__ = (
        CheckConstraint("delivery_method IN ('handed_to_recipient', 'left_at_door', 'other', 'unrecorded')", name="ck_delivery_evidence_method"),
        CheckConstraint("delivery_method = 'unrecorded' OR (uploaded_by_id IS NOT NULL AND uploaded_at IS NOT NULL AND media_type IS NOT NULL "
                        "AND size_bytes IS NOT NULL AND sha256 IS NOT NULL)", name="ck_delivery_evidence_recorded"),
    )

    id = Column(Integer, primary_key=True)
    attempt_id = Column(Integer, ForeignKey("delivery_attempts.id", ondelete="RESTRICT"), nullable=False, index=True)
    storage_key = Column(String(255), nullable=False, unique=True)
    photo_type = Column(String(16), nullable=True)
    delivery_method = Column(String(24), nullable=False)
    media_type = Column(String(32), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    sha256 = Column(String(64), nullable=True)
    uploaded_by_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    uploaded_at = Column(DateTime, nullable=True)


class DeliveryEvidenceNote(TenantScoped, Base):
    """توضیح آزاد روش «سایر». ممکن است داده شخصی داشته باشد، پس بیرون از ردیف مدرک است و با خروج سازمان حذف می‌شود."""
    __tablename__ = "delivery_evidence_notes"

    id = Column(Integer, primary_key=True)
    evidence_id = Column(Integer, ForeignKey("delivery_evidence.id", ondelete="RESTRICT"), nullable=False, unique=True)
    note = Column(String(300), nullable=False)


class DeliveryEvidenceEvent(TenantScoped, Base):
    """رویداد فقط‌افزودنی پاک شدن فایل یا توضیح یک مدرک."""
    __tablename__ = "delivery_evidence_events"
    __table_args__ = (CheckConstraint("event_type IN ('file_deleted', 'note_redacted')", name="ck_delivery_evidence_events_type"),)

    id = Column(Integer, primary_key=True)
    evidence_id = Column(Integer, ForeignKey("delivery_evidence.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_type = Column(String(16), nullable=False)
    reason = Column(String(200), nullable=False)
    at = Column(DateTime, nullable=False, default=_now)


class DriverReturn(TenantScoped, Base):
    """کالایی که باید از راننده به انبار برگردد. موجودی فقط با شمارش انبار (received) تغییر می‌کند."""
    __tablename__ = "driver_returns"
    __table_args__ = (CheckConstraint("status IN ('open', 'received')", name="ck_driver_returns_status"),)

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_id = Column(Integer, ForeignKey("delivery_attempts.id", ondelete="SET NULL"), nullable=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id", ondelete="SET NULL"), nullable=True, index=True)
    driver_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(16), nullable=False, default="open", index=True)
    reason = Column(String(200), nullable=False)
    created_at = Column(DateTime, nullable=False, default=_now)
    received_at = Column(DateTime, nullable=True)
    received_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    received_location_id = Column(Integer, ForeignKey("locations.id", ondelete="SET NULL"), nullable=True)
    note = Column(String(500), nullable=True)

    lines = relationship("DriverReturnLine", cascade="all, delete-orphan", order_by="DriverReturnLine.id")


class DriverReturnLine(TenantScoped, Base):
    __tablename__ = "driver_return_lines"

    id = Column(Integer, primary_key=True, index=True)
    return_id = Column(Integer, ForeignKey("driver_returns.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    product_name = Column(String(200), nullable=False)
    expected_quantity = Column(Integer, nullable=False)
    received_quantity = Column(Integer, nullable=True)
    shortage_reason = Column(String(500), nullable=True)


class ContactAttempt(TenantScoped, Base):
    """تماس با گیرنده: چه کسی، کی، از چه راهی و با چه نتیجه‌ای."""
    __tablename__ = "contact_attempts"
    __table_args__ = (
        CheckConstraint("method IN ('call', 'sms', 'door')", name="ck_contact_attempts_method"),
        CheckConstraint("outcome IN ('answered', 'no_answer', 'busy', 'wrong_number', 'off')", name="ck_contact_attempts_outcome"),
    )

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    method = Column(String(8), nullable=False)
    outcome = Column(String(16), nullable=False)
    note = Column(String(500), nullable=True)
    at = Column(DateTime, nullable=False, default=_now)


class OrderHandover(TenantScoped, Base):
    """تحویل بار بین دو راننده؛ سفارش فقط با تأیید راننده مقصد منتقل می‌شود."""
    __tablename__ = "order_handovers"
    __table_args__ = (CheckConstraint("status IN ('requested', 'accepted', 'rejected')", name="ck_order_handovers_status"),)

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    from_driver_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    from_vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    to_driver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    to_vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(16), nullable=False, default="requested", index=True)
    note = Column(String(500), nullable=True)
    response_note = Column(String(500), nullable=True)
    requested_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    responded_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    responded_at = Column(DateTime, nullable=True)


class CustomerRequest(TenantScoped, Base):
    """درخواست مشتری از صفحه رهگیری. چیزی مستقیم تغییر نمی‌کند؛ سازمان تصمیم می‌گیرد."""
    __tablename__ = "customer_requests"
    __table_args__ = (
        CheckConstraint("kind IN ('address_change', 'cancel', 'return', 'dispute')", name="ck_customer_requests_kind"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_customer_requests_status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default="pending", index=True)
    note = Column(String(500), nullable=True)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=_now)
    decided_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    decision_note = Column(String(500), nullable=True)


ACTIVE_EXCEPTION_STATUSES = ("open", "acknowledged", "in_progress", "waiting", "waiting_external")


class OperationException(TenantScoped, Base):
    """برای هر مورد فقط یک استثنای باز هست (ایندکس یکتای جزئی)؛ این همان قاعده ادغام موارد تکراری است."""
    __tablename__ = "operation_exceptions"
    __table_args__ = (
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="ck_operation_exceptions_severity"),
        CheckConstraint("team IN ('warehouse', 'fleet', 'support', 'management')", name="ck_operation_exceptions_team"),
        CheckConstraint("status IN ('open', 'acknowledged', 'in_progress', 'waiting', 'waiting_external', 'resolved', 'merged')",
                        name="ck_operation_exceptions_status"),
        Index("uq_operation_exceptions_active", "organization_id", "kind", "entity_type", "entity_id", unique=True,
              postgresql_where=text("status IN ('open', 'acknowledged', 'in_progress', 'waiting', 'waiting_external')"),
              sqlite_where=text("status IN ('open', 'acknowledged', 'in_progress', 'waiting', 'waiting_external')")),
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
    occurrence_count = Column(Integer, nullable=False, default=1, server_default="1")
    acknowledged_at = Column(DateTime, nullable=True)
    evidence_refs = Column(JSON, nullable=True)                # پیوند داخلی به سند، عکس یا رویداد
    resolution_code = Column(String(24), nullable=True)
    reminded_at = Column(DateTime, nullable=True)
    escalated_at = Column(DateTime, nullable=True)


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


class AdjustmentApproval(TenantScoped, Base):
    """اصلاح موجودی بیشتر از سقف سازمان که منتظر تأیید شخص دوم است (app/services/approval_service.py)."""
    __tablename__ = "adjustment_approvals"
    __table_args__ = (
        CheckConstraint("kind IN ('movement', 'set_balance')", name="ck_adjustment_approvals_kind"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_adjustment_approvals_status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String(16), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True)
    quantity = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False)
    reason = Column(String(500), nullable=True)
    status = Column(String(16), nullable=False, default="pending", index=True)
    requested_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    decided_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    decision_note = Column(String(500), nullable=True)


class PlanChange(Base):
    """سابقه نسخه‌دار پلن هر سازمان با سقف‌های همان لحظه."""
    __tablename__ = "plan_changes"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    from_plan = Column(String(16), nullable=False)
    to_plan = Column(String(16), nullable=False)
    version = Column(Integer, nullable=False)
    limits = Column(JSON, nullable=False)
    modules = Column(JSON, nullable=False)
    reason = Column(String(500), nullable=True)
    changed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)


class SupportAccessGrant(Base):
    """دسترسی موقت کارکنان پلتفرم به یک سازمان: با دلیل، مهلت و امکان لغو."""
    __tablename__ = "support_access_grants"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    reason = Column(String(500), nullable=False)
    granted_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class FeatureFlag(Base):
    """روشن و خاموش کردن تدریجی قابلیت. نبود ردیف یعنی روشن؛ allowlist خالی یعنی همه سازمان‌ها."""
    __tablename__ = "feature_flags"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(48), nullable=False, unique=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    kill_switch = Column(Boolean, nullable=False, default=False, server_default="false")
    allowlist = Column(JSON, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    updated_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class TenantExport(Base):
    """
    خروجی کامل داده یک سازمان؛ فایل خصوصی است و فقط ادمین پلتفرم دریافت می‌کند.
    هر اجرا run_token خودش را دارد و فقط با همان توکن پایان می‌یابد، پس اجرای کهنه نتیجه اجرای تازه را بازنویسی نمی‌کند.
    تلاش دوباره ردیف تازه است و retry_of_id آن را به ردیف ناموفق وصل می‌کند.
    """
    __tablename__ = "tenant_exports"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'done', 'failed')", name="ck_tenant_exports_status"),
        UniqueConstraint("retry_of_id", name="uq_tenant_exports_retry_of"),
    )

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="pending")
    path = Column(String(255), nullable=True)
    reason = Column(String(500), nullable=True)
    error = Column(String(200), nullable=True)
    requested_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    finished_at = Column(DateTime, nullable=True)
    run_token = Column(String(32), nullable=True)
    started_at = Column(DateTime, nullable=True)
    lease_until = Column(DateTime, nullable=True)
    retry_of_id = Column(Integer, ForeignKey("tenant_exports.id", ondelete="SET NULL", name="fk_tenant_exports_retry_of"), nullable=True)


class PurchaseRequest(TenantScoped, Base):
    """درخواست خرید. پرداخت و رسید خودکار ندارد (ت۲۲)."""
    __tablename__ = "purchase_requests"
    __table_args__ = (CheckConstraint("status IN ('pending', 'approved', 'rejected', 'canceled')", name="ck_purchase_requests_status"),)

    id = Column(Integer, primary_key=True)
    code = Column(String(16), nullable=False, unique=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    status = Column(String(12), nullable=False, default="pending", index=True)
    note = Column(String(500), nullable=True)
    requested_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)


class PurchaseRequestLine(TenantScoped, Base):
    __tablename__ = "purchase_request_lines"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_purchase_request_lines_quantity"),)

    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("purchase_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    product_name = Column(String(200), nullable=False)
    quantity = Column(Integer, nullable=False)
    estimated_unit_cost = Column(Float, nullable=True)


class PurchaseRequestEvent(TenantScoped, Base):
    """تاریخچه فقط‌افزودنی تصمیم‌ها؛ با تریگر تغییرناپذیر است."""
    __tablename__ = "purchase_request_events"
    __table_args__ = (CheckConstraint("action IN ('created', 'approved', 'rejected', 'canceled')", name="ck_purchase_request_events_action"),)

    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("purchase_requests.id", ondelete="RESTRICT"), nullable=False, index=True)
    action = Column(String(12), nullable=False)
    note = Column(String(500), nullable=True)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    at = Column(DateTime, nullable=False, default=_now)
