"""
مدل‌های عملیات انبار (فصل‌های ۶ تا ۱۰): محل‌ها، موجودی چندبعدی، رسید دریافت، بازرسی کیفی و جانمایی.
واژه‌ها و وضعیت‌ها از app/core/wms.py می‌آیند.

موجودی در دو سطح، هر دو فقط از دفتر گردش کالا (app/services/stock_ledger.py):
  Inventory     کالا × انبار × وضعیت کیفی — رزرو و نقطه سفارش
  StockBalance  همان ردیف × محل × مالک × بچ × سریال × انقضا — همیشه: مجموع ردیف‌های ریز = Inventory.quantity
هر گردش (StockMovement) یک یا چند ردیف ریز (StockMovementLine) دارد که مجموعشان = quantity_change است.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String,
    UniqueConstraint, text,
)
from sqlalchemy.orm import relationship

from app.core.tenancy import TenantScoped
from app.core.wms import (
    DISCREPANCY_TYPES, LOCATION_LEVELS, LOCATION_TYPES, PUTAWAY_PROBLEMS, PUTAWAY_STATUSES, RECEIPT_STATUSES,
    RECEIPT_TYPES, STOCK_STATUSES, TASK_TYPES, sql_in,
)
from app.database import Base


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# فصل ۶ — ساختار فیزیکی: محل‌ها
# ---------------------------------------------------------------------------
class Location(TenantScoped, Base):
    """
    محل فیزیکی در یک انبار: منطقه ← راهرو ← قفسه ← طبقه ← خانه. زیرمجموعه هر محل سطح پایین‌تری دارد
    (پس حلقه ممکن نیست) و کالا فقط در محل انتهایی (بدون زیرمجموعه) نگهداری می‌شود.
    نوع محل کاربرد را تعیین می‌کند (app/core/wms.LOCATION_TYPES): فقط موجودی تأییدشده‌ی محل‌های
    نگهداری/برداشت قابل تخصیص به سفارش است. ظرفیت و قاعده اختلاط هنگام ورود کالا در دفتر گردش کنترل می‌شود.
    """
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "code", name="uq_locations_warehouse_code"),
        UniqueConstraint("organization_id", "barcode", name="uq_locations_org_barcode"),
        CheckConstraint(f"level IN ({sql_in(LOCATION_LEVELS)})", name="ck_locations_level"),
        CheckConstraint(f"location_type IN ({sql_in(LOCATION_TYPES)})", name="ck_locations_type"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_locations_parent_self"),
        CheckConstraint("(max_weight_kg IS NULL OR max_weight_kg > 0) AND (max_volume_m3 IS NULL OR max_volume_m3 > 0) "
                        "AND (max_pallets IS NULL OR max_pallets > 0)", name="ck_locations_capacity"),
    )

    id = Column(Integer, primary_key=True, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    parent_id = Column(Integer, ForeignKey("locations.id"), nullable=True, index=True)
    level = Column(String(8), nullable=False, default="bin")
    code = Column(String(32), nullable=False)                  # یکتا در انبار، مثل A-01-03-2
    barcode = Column(String(64), nullable=False)               # یکتا در سازمان؛ پیش‌فرض «کد انبار-کد محل»
    name = Column(String(100), nullable=True)
    location_type = Column(String(16), nullable=False, default="storage")
    # ظرفیت (خالی = بدون محدودیت). حجم از ابعاد کالا و پالت از «تعداد در پالت» کالا حساب می‌شود.
    max_weight_kg = Column(Float, nullable=True)
    max_volume_m3 = Column(Float, nullable=True)
    max_pallets = Column(Integer, nullable=True)
    # قواعد اختلاط
    allow_mixed_products = Column(Boolean, nullable=False, default=True, server_default="true")
    allow_mixed_lots = Column(Boolean, nullable=False, default=True, server_default="true")
    allow_mixed_owners = Column(Boolean, nullable=False, default=True, server_default="true")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    # مسدود (مثلاً قفسه آسیب‌دیده): کالای جدید نمی‌گیرد و موجودی‌اش قابل تخصیص نیست
    is_blocked = Column(Boolean, nullable=False, default=False, server_default="false")
    block_reason = Column(String(200), nullable=True)
    # در حال انبارگردانی با قفل (فصل ۱۶): هیچ گردشی جز اصلاحیه همان انبارگردانی از این محل/به این محل ثبت نمی‌شود
    count_lock_id = Column(Integer, ForeignKey("stocktakes.id", ondelete="SET NULL"), nullable=True, index=True)
    # ترتیب مسیر برداشت (فصل ۳۰)؛ خالی = مسیر مارپیچ خودکار از روی کد محل
    route_sequence = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    updated_at = Column(DateTime, nullable=True, onupdate=_now)

    warehouse = relationship("Warehouse")
    parent = relationship("Location", remote_side=[id])


# ---------------------------------------------------------------------------
# فصل ۱۰ — موجودی چندبعدی و ردیف ریز دفتر گردش
# ---------------------------------------------------------------------------
class StockBalance(TenantScoped, Base):
    """
    مانده ریز موجودی: یک ردیف Inventory (کالا × انبار × وضعیت) × محل × مالک × بچ × سریال × انقضا.
    location_id خالی = «بدون محل» (انبار بدون محل‌بندی یا موجودی قبل از محل‌بندی)؛ owner_id خالی = خود سازمان.
    quantity فقط از دفتر گردش کالا تغییر می‌کند (محافظ در app/services/stock_ledger.py).
    """
    __tablename__ = "stock_balances"
    __table_args__ = (
        UniqueConstraint("inventory_id", "location_id", "owner_id", "lot_number", "serial_number", "expiry_date",
                         name="uq_stock_balances_key", postgresql_nulls_not_distinct=True),
        CheckConstraint("quantity >= 0", name="ck_stock_balances_quantity"),
        CheckConstraint("serial_number IS NULL OR quantity <= 1", name="ck_stock_balances_serial_quantity"),
        CheckConstraint(f"stock_status IN ({sql_in(STOCK_STATUSES)})", name="ck_stock_balances_status"),
        # هر شماره سریال در هر لحظه حداکثر یک‌جا در موجودی است
        Index("uq_stock_balances_serial", "organization_id", "product_id", "serial_number", unique=True,
              postgresql_where=text("serial_number IS NOT NULL AND quantity > 0"),
              sqlite_where=text("serial_number IS NOT NULL AND quantity > 0")),
        Index("ix_stock_balances_product_lot", "product_id", "lot_number"),
    )

    id = Column(Integer, primary_key=True, index=True)
    inventory_id = Column(Integer, ForeignKey("inventories.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    stock_status = Column(String(16), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True, index=True)
    owner_id = Column(Integer, ForeignKey("partners.id"), nullable=True, index=True)
    lot_number = Column(String(64), nullable=True)
    serial_number = Column(String(64), nullable=True)
    expiry_date = Column(Date, nullable=True)
    quantity = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=True, onupdate=_now)

    inventory = relationship("Inventory", back_populates="balances")
    product = relationship("Product")
    location = relationship("Location")
    owner = relationship("Partner")


class StockMovementLine(TenantScoped, Base):
    """
    ردیف ریز یک گردش: «چه مقدار از کدام محل/بچ/سریال/مالک». غیرقابل‌ویرایش و غیرقابل‌حذف (مثل خود گردش).
    مجموع quantity_change ردیف‌های یک گردش = quantity_change همان گردش.
    """
    __tablename__ = "stock_movement_lines"
    __table_args__ = (
        CheckConstraint("quantity_change <> 0", name="ck_stock_movement_lines_nonzero"),
        Index("ix_stock_movement_lines_product_warehouse", "product_id", "warehouse_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    movement_id = Column(Integer, ForeignKey("stock_movements.id"), nullable=False, index=True)
    balance_id = Column(Integer, ForeignKey("stock_balances.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    stock_status = Column(String(16), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True, index=True)
    owner_id = Column(Integer, ForeignKey("partners.id"), nullable=True)
    lot_number = Column(String(64), nullable=True)
    serial_number = Column(String(64), nullable=True)
    expiry_date = Column(Date, nullable=True)
    quantity_change = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)      # مانده همان ردیف ریز پس از این گردش

    movement = relationship("StockMovement", back_populates="lines")
    balance = relationship("StockBalance")
    location = relationship("Location")
    owner = relationship("Partner")


# ---------------------------------------------------------------------------
# فصل ۷ — رسید دریافت کالا
# ---------------------------------------------------------------------------
class InboundReceipt(TenantScoped, Base):
    """
    رسید دریافت: ورود برنامه‌ریزی‌شده (خرید، انتقال از انبار در راه، مرجوعی) یا پیش‌بینی‌نشده.
    هر دریافت فیزیکی یک سند «رسید دریافت کالا» (GR) با گردش‌های ریز (محل، بچ، سریال) می‌سازد.
    باز ← در حال دریافت ← بسته (با ثبت مغایرت‌ها)؛ لغو فقط پیش از اولین دریافت.
    تکرار: کلید یکتایی درخواست + یکتایی شماره بارنامه/حواله هر تأمین‌کننده.
    """
    __tablename__ = "inbound_receipts"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_inbound_receipts_idempotency"),
        CheckConstraint(f"receipt_type IN ({sql_in(RECEIPT_TYPES)})", name="ck_inbound_receipts_type"),
        CheckConstraint(f"status IN ({sql_in(RECEIPT_STATUSES)})", name="ck_inbound_receipts_status"),
        CheckConstraint("over_tolerance_pct >= 0 AND over_tolerance_pct <= 100", name="ck_inbound_receipts_tolerance"),
        CheckConstraint("receipt_type <> 'transfer' OR source_warehouse_id IS NOT NULL", name="ck_inbound_receipts_transfer_source"),
        Index("uq_inbound_receipts_partner_ref", "organization_id", "partner_id", "external_ref", unique=True,
              postgresql_where=text("external_ref IS NOT NULL AND status <> 'canceled'"),
              sqlite_where=text("external_ref IS NOT NULL AND status <> 'canceled'")),
    )

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(16), nullable=False, unique=True, index=True)       # مثل IR-7K2M9QXA
    receipt_type = Column(String(16), nullable=False, default="purchase")
    status = Column(String(16), nullable=False, default="open", index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    partner_id = Column(Integer, ForeignKey("partners.id"), nullable=True, index=True)       # تأمین‌کننده/مشتری
    owner_id = Column(Integer, ForeignKey("partners.id"), nullable=True)                     # مالک کالای امانی
    source_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)        # انتقال: انبار در راه
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)                       # مرجوعی: سفارش مرجع
    reference_number = Column(String(64), nullable=True)      # شماره سفارش خرید / اعلام ارسال
    external_ref = Column(String(64), nullable=True)          # شماره بارنامه / حواله تأمین‌کننده
    expected_date = Column(Date, nullable=True)
    receiving_location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    over_tolerance_pct = Column(Float, nullable=False, default=0, server_default="0")
    note = Column(String(500), nullable=True)
    idempotency_key = Column(String(64), nullable=True)
    request_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    received_at = Column(DateTime, nullable=True)            # اولین دریافت
    closed_at = Column(DateTime, nullable=True)
    closed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    close_note = Column(String(500), nullable=True)

    lines = relationship("InboundReceiptLine", back_populates="receipt", order_by="InboundReceiptLine.line_no")
    warehouse = relationship("Warehouse", foreign_keys=[warehouse_id])
    source_warehouse = relationship("Warehouse", foreign_keys=[source_warehouse_id])
    partner = relationship("Partner", foreign_keys=[partner_id])
    owner = relationship("Partner", foreign_keys=[owner_id])
    receiving_location = relationship("Location")
    created_by = relationship("User", foreign_keys=[created_by_id])


class InboundReceiptLine(TenantScoped, Base):
    """
    سطر رسید (به واحد پایه): مورد انتظار، دریافت‌شده (فیزیکی)، پذیرفته (تأییدشده)، مردود (مردود/معیوب/آسیب‌دیده).
    در انتظار بازرسی = دریافت‌شده − پذیرفته − مردود؛ باقی‌مانده ورود = مورد انتظار − دریافت‌شده.
    شمارنده‌ها فقط از app/services/receiving_service.py و quality_service.py عوض می‌شوند.
    """
    __tablename__ = "inbound_receipt_lines"
    __table_args__ = (
        UniqueConstraint("receipt_id", "line_no", name="uq_inbound_receipt_lines_no"),
        CheckConstraint("expected_quantity >= 0 AND received_quantity >= 0 AND accepted_quantity >= 0 "
                        "AND rejected_quantity >= 0", name="ck_inbound_receipt_lines_non_negative"),
        CheckConstraint("accepted_quantity + rejected_quantity <= received_quantity", name="ck_inbound_receipt_lines_inspected"),
        CheckConstraint(f"discrepancy_type IS NULL OR discrepancy_type IN ({sql_in(DISCREPANCY_TYPES)})",
                        name="ck_inbound_receipt_lines_discrepancy"),
    )

    id = Column(Integer, primary_key=True, index=True)
    receipt_id = Column(Integer, ForeignKey("inbound_receipts.id"), nullable=False, index=True)
    line_no = Column(Integer, nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    expected_quantity = Column(Integer, nullable=False, default=0)
    received_quantity = Column(Integer, nullable=False, default=0)
    accepted_quantity = Column(Integer, nullable=False, default=0)
    rejected_quantity = Column(Integer, nullable=False, default=0)
    lot_number = Column(String(64), nullable=True)            # بچ اعلام‌شده تأمین‌کننده (اختیاری)
    note = Column(String(300), nullable=True)
    over_reason = Column(String(300), nullable=True)          # دلیل پذیرش اضافه تحویل / کالای خارج از برنامه
    discrepancy_type = Column(String(16), nullable=True)      # هنگام بستن رسید
    discrepancy_quantity = Column(Integer, nullable=True)
    discrepancy_reason = Column(String(300), nullable=True)

    receipt = relationship("InboundReceipt", back_populates="lines")
    product = relationship("Product")

    @property
    def pending_inspection(self) -> int:
        return (self.received_quantity or 0) - (self.accepted_quantity or 0) - (self.rejected_quantity or 0)

    @property
    def outstanding(self) -> int:
        return max((self.expected_quantity or 0) - (self.received_quantity or 0), 0)


# ---------------------------------------------------------------------------
# فصل ۸ — بازرسی کیفی
# ---------------------------------------------------------------------------
class QualityInspection(TenantScoped, Base):
    """
    بازرسی کیفی بخشی از موجودی (معمولاً «در انتظار بازرسی» یا «قرنطینه») با یک یا چند نتیجه؛
    هر نتیجه همان مقدار را در همان محل به وضعیت جدید می‌برد (سند QI). وضعیت کیفی مستقل از محل است.
    """
    __tablename__ = "quality_inspections"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_quality_inspections_quantity"),
        CheckConstraint(f"from_status IN ({sql_in(STOCK_STATUSES)})", name="ck_quality_inspections_from_status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(16), nullable=False, unique=True, index=True)       # مثل QC-7K2M9QXA
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    lot_number = Column(String(64), nullable=True)
    from_status = Column(String(16), nullable=False)
    quantity = Column(Integer, nullable=False)
    receipt_id = Column(Integer, ForeignKey("inbound_receipts.id"), nullable=True, index=True)
    document_id = Column(Integer, ForeignKey("stock_documents.id"), nullable=True)
    note = Column(String(500), nullable=True)
    inspector_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now, index=True)

    results = relationship("QualityInspectionResult", back_populates="inspection", order_by="QualityInspectionResult.id")
    product = relationship("Product")
    warehouse = relationship("Warehouse")
    location = relationship("Location")
    document = relationship("StockDocument")
    inspector = relationship("User")


class QualityInspectionResult(TenantScoped, Base):
    __tablename__ = "quality_inspection_results"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_quality_inspection_results_quantity"),
        CheckConstraint(f"to_status IN ({sql_in(STOCK_STATUSES)})", name="ck_quality_inspection_results_status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    inspection_id = Column(Integer, ForeignKey("quality_inspections.id"), nullable=False, index=True)
    to_status = Column(String(16), nullable=False)
    quantity = Column(Integer, nullable=False)
    reason = Column(String(300), nullable=True)

    inspection = relationship("QualityInspection", back_populates="results")


# ---------------------------------------------------------------------------
# فصل ۹ — جانمایی
# ---------------------------------------------------------------------------
class PutawayTask(TenantScoped, Base):
    """
    وظیفه جانمایی: بردن مقداری کالا از محل مبدأ (معمولاً تخلیه) به محل نگهداری. مقصد پیشنهادی سیستم از
    ظرفیت و قواعد اختلاط می‌آید؛ اجرا با اسکن کالا، محل مبدأ و محل مقصد تأیید می‌شود. اجرای ناقص مجاز است
    (باقی‌مانده روی همین وظیفه می‌ماند) و هر خطا یا مشکل در شمارنده خطا و رویداد putaway.task.failed ثبت می‌شود.
    """
    __tablename__ = "putaway_tasks"
    __table_args__ = (
        CheckConstraint("quantity > 0 AND quantity_done >= 0 AND quantity_done <= quantity", name="ck_putaway_tasks_quantity"),
        CheckConstraint(f"status IN ({sql_in(PUTAWAY_STATUSES)})", name="ck_putaway_tasks_status"),
        CheckConstraint(f"task_type IN ({sql_in(TASK_TYPES)})", name="ck_putaway_tasks_type"),
        CheckConstraint(f"stock_status IN ({sql_in(STOCK_STATUSES)})", name="ck_putaway_tasks_stock_status"),
        CheckConstraint(f"last_problem IS NULL OR last_problem IN ({sql_in(PUTAWAY_PROBLEMS + ('scan_mismatch', 'rule_violation'))})",
                        name="ck_putaway_tasks_problem"),
    )

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(16), nullable=False, unique=True, index=True)       # مثل PT-7K2M9QXA
    status = Column(String(16), nullable=False, default="open", index=True)
    # جانمایی کالای رسیده، یا تأمین مجدد محل برداشت از قفسه نگهداری (فصل ۱۳) — اجرای اسکنی یکسان
    task_type = Column(String(16), nullable=False, default="putaway", server_default="putaway")
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    stock_status = Column(String(16), nullable=False)
    quantity = Column(Integer, nullable=False)
    quantity_done = Column(Integer, nullable=False, default=0)
    source_location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("partners.id"), nullable=True)
    lot_number = Column(String(64), nullable=True)
    expiry_date = Column(Date, nullable=True)
    suggested_location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    destination_location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)   # آخرین مقصد اجراشده
    receipt_id = Column(Integer, ForeignKey("inbound_receipts.id"), nullable=True, index=True)
    inspection_id = Column(Integer, ForeignKey("quality_inspections.id"), nullable=True)
    excluded_location_ids = Column(JSON, nullable=False, default=list)       # مقصدهایی که مشکل داشتند
    failure_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_problem = Column(String(24), nullable=True)
    last_error = Column(String(300), nullable=True)
    note = Column(String(300), nullable=True)
    assigned_to_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    completed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    cancel_reason = Column(String(300), nullable=True)

    product = relationship("Product")
    warehouse = relationship("Warehouse")
    source_location = relationship("Location", foreign_keys=[source_location_id])
    suggested_location = relationship("Location", foreign_keys=[suggested_location_id])
    destination_location = relationship("Location", foreign_keys=[destination_location_id])
    owner = relationship("Partner")

    @property
    def remaining(self) -> int:
        return (self.quantity or 0) - (self.quantity_done or 0)
