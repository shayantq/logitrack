"""
مدل‌های پایه انبارداری (WMS): سند انبار، رزرو موجودی، رویداد دامنه، طرف تجاری، واحد فرعی و تأمین‌کننده کالا.
واژه‌ها و وضعیت‌ها از app/core/wms.py می‌آیند.

محافظت از سوابق در دو لایه انجام می‌شود:
  • ORM (before_flush در app/services/stock_ledger.py): ویرایش/حذف گردش، رویداد و سند قطعی متوقف می‌شود.
  • PostgreSQL (تریگرهای پایین همین فایل و مایگریشن ۰۰۲۴): حتی SQL مستقیم هم نمی‌تواند سوابق را بازنویسی کند.
    فقط اسکریپت‌های نگهداری با `set_config('pasineh.ledger_maintenance', 'on', true)` مجازند.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, event,
)
from sqlalchemy.orm import relationship

from app.core.tenancy import TenantScoped
from app.core.wms import (
    CARRIER_SERVICES, DOCUMENT_STATUSES, DOCUMENT_TYPES, PARTNER_KINDS, RESERVATION_STATUSES, sql_in,
)
from app.database import Base


def _now():
    return datetime.now(timezone.utc)


class StockDocument(TenantScoped, Base):
    """
    سند انبار: تنها راه تغییر موجودی. هر سند قطعی (posted) یک یا چند گردش دارد و دیگر ویرایش یا حذف نمی‌شود؛
    تنها تغییر مجاز «قطعی ← برگشت‌خورده» است، وقتی سند برگشت (reversal_of_id) اثرش را خنثی کند.
    """
    __tablename__ = "stock_documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_stock_documents_idempotency"),
        UniqueConstraint("reversal_of_id", name="uq_stock_documents_reversal"),
        CheckConstraint(f"doc_type IN ({sql_in(DOCUMENT_TYPES)})", name="ck_stock_documents_type"),
        CheckConstraint(f"status IN ({sql_in(DOCUMENT_STATUSES)})", name="ck_stock_documents_status"),
        Index("ix_stock_documents_reference", "reference_type", "reference_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(16), nullable=False, unique=True, index=True)        # مثلاً RC-7K2M9QXA
    doc_type = Column(String(24), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="posted", index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True, index=True)
    partner_id = Column(Integer, ForeignKey("partners.id"), nullable=True, index=True)
    # مرجع: ("order", شناسه سفارش)، ("stocktake", شناسه انبارگردانی) و ...
    reference_type = Column(String(32), nullable=True)
    reference_id = Column(Integer, nullable=True)
    external_ref = Column(String(64), nullable=True)     # شماره فاکتور/بارنامه طرف مقابل
    note = Column(String(500), nullable=True)
    idempotency_key = Column(String(64), nullable=True)
    request_hash = Column(String(64), nullable=True)
    reversal_of_id = Column(Integer, ForeignKey("stock_documents.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    posted_at = Column(DateTime, nullable=True)
    posted_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    movements = relationship("StockMovement", back_populates="document", order_by="StockMovement.id")
    warehouse = relationship("Warehouse")
    partner = relationship("Partner")
    created_by = relationship("User", foreign_keys=[created_by_id])
    reversal_of = relationship("StockDocument", remote_side=[id], foreign_keys=[reversal_of_id])


class StockReservation(TenantScoped, Base):
    """
    رزرو (تخصیص) بخشی از موجودی سالم برای یک سند — مثلاً سفارش. موجودی فیزیکی تغییر نمی‌کند؛ فقط
    Inventory.reserved_quantity بالا می‌رود و آن مقدار برای سفارش‌های دیگر آزاد نیست.
    پایان رزرو: «مصرف» (خروج کالا با حواله) یا «آزادسازی» (لغو/انقضا).
    """
    __tablename__ = "stock_reservations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_stock_reservations_quantity"),
        CheckConstraint(f"status IN ({sql_in(RESERVATION_STATUSES)})", name="ck_stock_reservations_status"),
        Index("ix_stock_reservations_reference", "reference_type", "reference_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    inventory_id = Column(Integer, ForeignKey("inventories.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="active", index=True)
    reference_type = Column(String(32), nullable=False)
    reference_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=_now)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    closed_at = Column(DateTime, nullable=True)
    closed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    close_reason = Column(String(200), nullable=True)
    # گردش خروجی که این رزرو را مصرف کرد
    movement_id = Column(Integer, ForeignKey("stock_movements.id"), nullable=True)

    inventory = relationship("Inventory")
    product = relationship("Product")
    movement = relationship("StockMovement")


class DomainEvent(TenantScoped, Base):
    """
    رویداد دامنه (Transactional Outbox): «چه اتفاقی افتاد» در همان تراکنش عملیات ثبت می‌شود، پس یا هر دو
    ذخیره می‌شوند یا هیچ‌کدام. غیرقابل‌ویرایش؛ مصرف‌کننده‌ها (گزارش، وب‌هوک، یکپارچه‌سازی) با شناسه
    افزایشی (after_id) دنبالش می‌کنند. شناسه انجام‌دهنده عمداً کلید خارجی نیست تا حذف کاربر سابقه را عوض نکند.
    """
    __tablename__ = "domain_events"
    __table_args__ = (Index("ix_domain_events_aggregate", "aggregate_type", "aggregate_id"),)

    id = Column(Integer, primary_key=True, index=True)
    occurred_at = Column(DateTime, nullable=False, default=_now, index=True)
    event_type = Column(String(48), nullable=False, index=True)
    aggregate_type = Column(String(32), nullable=False)
    aggregate_id = Column(Integer, nullable=False)
    actor_id = Column(Integer, nullable=True)
    actor_name = Column(String(150), nullable=True)
    payload = Column(JSON, nullable=False, default=dict)


class Partner(TenantScoped, Base):
    """
    طرف تجاری سازمان: تأمین‌کننده، مشتری (عمده/حقوقی)، شرکت حمل یا مالک کالای امانی — یک طرف می‌تواند چند نقش داشته باشد.
    مشتریان نهایی سفارش‌ها (اشخاص با شماره همراه) جدا در جدول customers هستند.
    شناسه ملی و شماره شبا فقط برای ادمین سازمان کامل نمایش داده می‌شود.
    """
    __tablename__ = "partners"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_partners_org_code"),
        UniqueConstraint("organization_id", "national_id", name="uq_partners_org_national_id"),
        CheckConstraint("is_supplier OR is_customer OR is_carrier OR is_owner", name="ck_partners_role"),
        CheckConstraint(f"kind IN ({sql_in(PARTNER_KINDS)})", name="ck_partners_kind"),
        CheckConstraint(f"carrier_service IS NULL OR carrier_service IN ({sql_in(CARRIER_SERVICES)})", name="ck_partners_carrier_service"),
        CheckConstraint("payment_terms_days IS NULL OR (payment_terms_days >= 0 AND payment_terms_days <= 365)", name="ck_partners_payment_terms"),
        CheckConstraint("lead_time_days IS NULL OR (lead_time_days >= 0 AND lead_time_days <= 365)", name="ck_partners_lead_time"),
    )

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    updated_at = Column(DateTime, nullable=True, onupdate=_now)
    code = Column(String(16), nullable=False)                    # کد یکتا در سازمان، مثل SUP-001
    name = Column(String(200), nullable=False)
    kind = Column(String(16), nullable=False, default="legal")   # legal = حقوقی، individual = حقیقی
    is_supplier = Column(Boolean, nullable=False, default=False, server_default="false")
    is_customer = Column(Boolean, nullable=False, default=False, server_default="false")
    is_carrier = Column(Boolean, nullable=False, default=False, server_default="false")
    # مالک کالای امانی (مشتری انبار عمومی/۳PL): موجودی‌اش جدا ردیابی می‌شود و به سفارش‌های سازمان تخصیص نمی‌یابد
    is_owner = Column(Boolean, nullable=False, default=False, server_default="false")
    legal_name = Column(String(200), nullable=True)
    national_id = Column(String(11), nullable=True)              # شناسه ملی (حقوقی، ۱۱ رقم) یا کد ملی (حقیقی، ۱۰ رقم)
    economic_code = Column(String(14), nullable=True)
    registration_number = Column(String(32), nullable=True)
    phone = Column(String(20), nullable=True)
    mobile = Column(String(11), nullable=True)
    email = Column(String(254), nullable=True)
    website = Column(String(200), nullable=True)
    province = Column(String(64), nullable=True)
    city = Column(String(64), nullable=True)
    address = Column(String(500), nullable=True)
    postal_code = Column(String(10), nullable=True)
    contact_name = Column(String(100), nullable=True)
    contact_mobile = Column(String(11), nullable=True)
    iban = Column(String(26), nullable=True)                     # شماره شبا: IR + ۲۴ رقم
    payment_terms_days = Column(Integer, nullable=True)          # مهلت پرداخت/تسویه
    lead_time_days = Column(Integer, nullable=True)              # تأمین‌کننده: زمان تأمین پیش‌فرض
    carrier_service = Column(String(16), nullable=True)          # شرکت حمل: نوع خدمت
    tracking_url = Column(String(300), nullable=True)            # شرکت حمل: الگوی لینک رهگیری با {code}
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ProductUom(TenantScoped, Base):
    """واحد فرعی کالا (مثلاً «کارتن» = ۱۲ «عدد»). factor عدد صحیح ≥ ۲ از واحد پایه است تا تبدیل همیشه دقیق باشد."""
    __tablename__ = "product_uoms"
    __table_args__ = (
        UniqueConstraint("product_id", "name", name="uq_product_uoms_name"),
        UniqueConstraint("organization_id", "barcode", name="uq_product_uoms_org_barcode"),
        CheckConstraint("factor >= 2", name="ck_product_uoms_factor"),
    )

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(32), nullable=False)
    factor = Column(Integer, nullable=False)
    barcode = Column(String(64), nullable=True)
    is_purchase_default = Column(Boolean, nullable=False, default=False, server_default="false")
    is_sales_default = Column(Boolean, nullable=False, default=False, server_default="false")

    product = relationship("Product", back_populates="uoms")


class ProductSupplier(TenantScoped, Base):
    """تأمین‌کننده‌های یک کالا با کد کالا نزد تأمین‌کننده، زمان تأمین، حداقل سفارش و آخرین قیمت."""
    __tablename__ = "product_suppliers"
    __table_args__ = (
        UniqueConstraint("product_id", "partner_id", name="uq_product_suppliers_pair"),
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="ck_product_suppliers_lead_time"),
        CheckConstraint("min_order_qty IS NULL OR min_order_qty > 0", name="ck_product_suppliers_moq"),
        CheckConstraint("last_price IS NULL OR last_price >= 0", name="ck_product_suppliers_price"),
    )

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    partner_id = Column(Integer, ForeignKey("partners.id"), nullable=False, index=True)
    supplier_sku = Column(String(64), nullable=True)
    lead_time_days = Column(Integer, nullable=True)
    min_order_qty = Column(Integer, nullable=True)
    last_price = Column(Float, nullable=True)
    is_preferred = Column(Boolean, nullable=False, default=False, server_default="false")

    product = relationship("Product", back_populates="suppliers")
    partner = relationship("Partner")


# ---------------------------------------------------------------------------
# تریگرهای PostgreSQL (برای create_all در تست‌های یکپارچگی؛ مایگریشن ۰۰۲۴ همین‌ها را می‌سازد)
# ---------------------------------------------------------------------------
LEDGER_TRIGGERS_SQL = (
    """
    CREATE OR REPLACE FUNCTION pasineh_immutable_row() RETURNS trigger AS $$
    BEGIN
        IF current_setting('pasineh.ledger_maintenance', true) = 'on' THEN
            RETURN COALESCE(NEW, OLD);
        END IF;
        RAISE EXCEPTION USING MESSAGE = 'rows of ' || TG_TABLE_NAME || ' are immutable (use a reversal document)', ERRCODE = 'check_violation';
    END $$ LANGUAGE plpgsql
    """,
    """
    CREATE OR REPLACE FUNCTION pasineh_guard_stock_document() RETURNS trigger AS $$
    BEGIN
        IF current_setting('pasineh.ledger_maintenance', true) = 'on' THEN
            RETURN COALESCE(NEW, OLD);
        END IF;
        IF TG_OP = 'DELETE' THEN
            IF OLD.status IN ('draft', 'canceled') THEN RETURN OLD; END IF;
            RAISE EXCEPTION 'posted stock documents cannot be deleted' USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.status = 'draft' THEN RETURN NEW; END IF;
        IF (to_jsonb(NEW) - 'status') IS DISTINCT FROM (to_jsonb(OLD) - 'status')
           OR NOT (NEW.status = OLD.status OR (OLD.status = 'posted' AND NEW.status = 'reversed')) THEN
            RAISE EXCEPTION 'posted stock documents are immutable' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END $$ LANGUAGE plpgsql
    """,
    "CREATE TRIGGER trg_stock_movements_immutable BEFORE UPDATE OR DELETE ON stock_movements "
    "FOR EACH ROW EXECUTE FUNCTION pasineh_immutable_row()",
    "CREATE TRIGGER trg_domain_events_immutable BEFORE UPDATE OR DELETE ON domain_events "
    "FOR EACH ROW EXECUTE FUNCTION pasineh_immutable_row()",
    # مایگریشن ۰۰۲۵: ردیف‌های ریز گردش (محل، بچ، سریال) هم مثل خود گردش غیرقابل‌تغییرند
    "CREATE TRIGGER trg_stock_movement_lines_immutable BEFORE UPDATE OR DELETE ON stock_movement_lines "
    "FOR EACH ROW EXECUTE FUNCTION pasineh_immutable_row()",
    "CREATE TRIGGER trg_stock_documents_guard BEFORE UPDATE OR DELETE ON stock_documents "
    "FOR EACH ROW EXECUTE FUNCTION pasineh_guard_stock_document()",
)


@event.listens_for(Base.metadata, "after_create")
def _create_ledger_triggers(target, connection, **kw):
    if connection.dialect.name != "postgresql":
        return
    for statement in LEDGER_TRIGGERS_SQL:
        connection.exec_driver_sql(statement)
