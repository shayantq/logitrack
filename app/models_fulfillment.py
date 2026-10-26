"""
مدل‌های اجرای سفارش و جابه‌جایی (فصل‌های ۱۱ تا ۱۵): سفارش معوق، سفارش انتقال، فهرست برداشت، بسته،
محموله، قاعده تأمین مجدد محل برداشت و تعیین تکلیف کیفی. واژه‌ها و وضعیت‌ها از app/core/wms.py می‌آیند.
هیچ‌کدام مستقیم موجودی را عوض نمی‌کنند؛ هر جابه‌جایی کالا از دفتر گردش (stock_ledger) و با سند ثبت می‌شود.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.tenancy import TenantScoped
from app.core.wms import (
    BACKORDER_STATUSES, DISPOSITION_ACTIONS, PICK_LINE_STATUSES, PICK_LIST_STATUSES, PICK_STRATEGIES,
    SHIPMENT_STATUSES, STOCK_STATUSES, TRANSFER_STATUSES, sql_in,
)
from app.database import Base


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# فصل ۱۱ — سفارش معوق
# ---------------------------------------------------------------------------
class Backorder(TenantScoped, Base):
    """
    مقداری از یک قلم سفارش که هنگام ثبت موجودی قابل وعده نداشت. حذف نمی‌شود: «در انتظار موجودی» می‌ماند
    تا تخصیص (به ترتیب اولویت سفارش، تاریخ تحویل و زمان ثبت) آن را رزرو کند؛ سپس با یک سفارش تکمیلی ارسال
    می‌شود. رزرو آن با مرجع ("backorder", id) در stock_reservations است.
    """
    __tablename__ = "backorders"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_backorders_quantity"),
        CheckConstraint(f"status IN ({sql_in(BACKORDER_STATUSES)})", name="ck_backorders_status"),
        Index("ix_backorders_queue", "status", "warehouse_id", "product_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False, default=0)
    status = Column(String(16), nullable=False, default="open")
    priority = Column(Boolean, nullable=False, default=False)
    due_at = Column(DateTime, nullable=False)                 # تاریخ تحویل درخواستی سفارش اصلی
    fulfilled_order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    note = Column(String(300), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now, index=True)
    allocated_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    order = relationship("Order", foreign_keys=[order_id])
    product = relationship("Product")


# ---------------------------------------------------------------------------
# فصل ۱۲ — سفارش انتقال
# ---------------------------------------------------------------------------
class TransferOrder(TenantScoped, Base):
    """
    انتقال دومرحله‌ای بین دو انبار (یا دو محل یک انبار): «ارسال» کالا را از مبدأ کم و با وضعیت «در راه» در
    انبار مقصد ثبت می‌کند (قابل ردیابی و غیرقابل تخصیص)؛ «دریافت» آن را در محل مقصد تأییدشده یا آسیب‌دیده
    می‌کند. باقی‌مانده در راه هنگام بستن یا ضایعات می‌شود یا به مبدأ برمی‌گردد.
    """
    __tablename__ = "transfer_orders"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_transfer_orders_idempotency"),
        CheckConstraint(f"status IN ({sql_in(TRANSFER_STATUSES)})", name="ck_transfer_orders_status"),
        CheckConstraint("from_warehouse_id <> to_warehouse_id OR from_location_id IS DISTINCT FROM to_location_id",
                        name="ck_transfer_orders_route"),
    )

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(16), nullable=False, unique=True, index=True)       # TO-...
    status = Column(String(16), nullable=False, default="open", index=True)
    from_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    to_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    from_location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    to_location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    note = Column(String(500), nullable=True)
    idempotency_key = Column(String(64), nullable=True)
    request_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    shipped_at = Column(DateTime, nullable=True)
    received_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    close_note = Column(String(500), nullable=True)
    resolution = Column(String(16), nullable=True)            # تکلیف کسری: write_off | return

    lines = relationship("TransferOrderLine", back_populates="transfer", order_by="TransferOrderLine.id")
    from_warehouse = relationship("Warehouse", foreign_keys=[from_warehouse_id])
    to_warehouse = relationship("Warehouse", foreign_keys=[to_warehouse_id])
    from_location = relationship("Location", foreign_keys=[from_location_id])
    to_location = relationship("Location", foreign_keys=[to_location_id])
    created_by = relationship("User", foreign_keys=[created_by_id])


class TransferOrderLine(TenantScoped, Base):
    """در راه = ارسال‌شده − دریافت‌شده − آسیب‌دیده − تعیین‌تکلیف‌شده هنگام بستن."""
    __tablename__ = "transfer_order_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0 AND shipped_quantity >= 0 AND received_quantity >= 0 AND damaged_quantity >= 0 "
                        "AND resolved_quantity >= 0", name="ck_transfer_lines_quantities"),
        CheckConstraint("received_quantity + damaged_quantity + resolved_quantity <= shipped_quantity",
                        name="ck_transfer_lines_balance"),
    )

    id = Column(Integer, primary_key=True, index=True)
    transfer_id = Column(Integer, ForeignKey("transfer_orders.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    lot_number = Column(String(64), nullable=True)
    quantity = Column(Integer, nullable=False)
    shipped_quantity = Column(Integer, nullable=False, default=0)
    received_quantity = Column(Integer, nullable=False, default=0)
    damaged_quantity = Column(Integer, nullable=False, default=0)
    resolved_quantity = Column(Integer, nullable=False, default=0)     # کسری بسته‌شده (ضایعات یا برگشت)
    discrepancy_reason = Column(String(300), nullable=True)

    transfer = relationship("TransferOrder", back_populates="lines")
    product = relationship("Product")

    @property
    def in_transit(self) -> int:
        return (self.shipped_quantity or 0) - (self.received_quantity or 0) - (self.damaged_quantity or 0) - (self.resolved_quantity or 0)


# ---------------------------------------------------------------------------
# فصل ۱۳ — تأمین مجدد محل برداشت
# ---------------------------------------------------------------------------
class ReplenishmentRule(TenantScoped, Base):
    """حداقل/حداکثر یک کالا در یک محل برداشت: موجودی ≤ حداقل ← وظیفه تأمین مجدد تا حداکثر از قفسه نگهداری."""
    __tablename__ = "replenishment_rules"
    __table_args__ = (
        UniqueConstraint("location_id", "product_id", name="uq_replenishment_rules_location_product"),
        CheckConstraint("min_quantity >= 0 AND max_quantity > min_quantity", name="ck_replenishment_rules_range"),
    )

    id = Column(Integer, primary_key=True, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    min_quantity = Column(Integer, nullable=False)
    max_quantity = Column(Integer, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime, nullable=False, default=_now)

    location = relationship("Location")
    product = relationship("Product")


# ---------------------------------------------------------------------------
# فصل ۱۴ — پیکینگ، بسته‌بندی، ارسال
# ---------------------------------------------------------------------------
class PickList(TenantScoped, Base):
    """
    فهرست برداشت یک یا چند سفارش (تک‌سفارشی، دسته‌ای، موجی، منطقه‌ای). سطرها به ترتیب مسیر محل‌ها و FEFO از
    موجودی قابل تخصیص برنامه‌ریزی می‌شوند؛ برداشت هر سطر با اسکن محل، کالا و مقدار تأیید و کالا به محل
    آماده‌سازی (اگر تعیین شده) منتقل می‌شود. رزرو سفارش‌ها دست نمی‌خورد تا حواله خروج هنگام تحویل به راننده.
    """
    __tablename__ = "pick_lists"
    __table_args__ = (
        CheckConstraint(f"strategy IN ({sql_in(PICK_STRATEGIES)})", name="ck_pick_lists_strategy"),
        CheckConstraint(f"status IN ({sql_in(PICK_LIST_STATUSES)})", name="ck_pick_lists_status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(16), nullable=False, unique=True, index=True)       # PL-...
    strategy = Column(String(8), nullable=False, default="single")
    status = Column(String(16), nullable=False, default="open", index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    zone_location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    staging_location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    wave_date = Column(Date, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    lines = relationship("PickLine", back_populates="pick_list", order_by="(PickLine.sequence, PickLine.id)")
    warehouse = relationship("Warehouse")
    zone = relationship("Location", foreign_keys=[zone_location_id])
    staging = relationship("Location", foreign_keys=[staging_location_id])


class PickLine(TenantScoped, Base):
    """یک برداشت: این مقدار از این کالا (بچ/انقضا) از این محل برای این سفارش."""
    __tablename__ = "pick_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0 AND picked_quantity >= 0 AND picked_quantity <= quantity", name="ck_pick_lines_quantity"),
        CheckConstraint(f"status IN ({sql_in(PICK_LINE_STATUSES)})", name="ck_pick_lines_status"),
        Index("ix_pick_lines_order_status", "order_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    pick_list_id = Column(Integer, ForeignKey("pick_lists.id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)       # محل برداشت (خالی = بدون محل)
    lot_number = Column(String(64), nullable=True)
    expiry_date = Column(Date, nullable=True)
    staged_location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)  # کالای برداشت‌شده اکنون اینجاست
    quantity = Column(Integer, nullable=False)
    picked_quantity = Column(Integer, nullable=False, default=0)
    status = Column(String(8), nullable=False, default="open")
    sequence = Column(Integer, nullable=False, default=0)
    short_reason = Column(String(300), nullable=True)
    issued = Column(Boolean, nullable=False, default=False, server_default="false")   # حواله خروج سفارش صادر شد
    picked_at = Column(DateTime, nullable=True)
    picked_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    pick_list = relationship("PickList", back_populates="lines")
    product = relationship("Product")
    location = relationship("Location", foreign_keys=[location_id])
    staged_location = relationship("Location", foreign_keys=[staged_location_id])


class Shipment(TenantScoped, Base):
    """محموله: سفارش‌های بسته‌بندی‌شده روی یک خودرو؛ ظرفیت وزنی و حجمی کنترل و با «تحویل به راننده» ارسال می‌شود."""
    __tablename__ = "shipments"
    __table_args__ = (CheckConstraint(f"status IN ({sql_in(SHIPMENT_STATUSES)})", name="ck_shipments_status"),)

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(16), nullable=False, unique=True, index=True)       # SH-...
    status = Column(String(16), nullable=False, default="open", index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, index=True)
    driver_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    dispatched_at = Column(DateTime, nullable=True)
    dispatched_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    vehicle = relationship("Vehicle")
    warehouse = relationship("Warehouse")
    driver = relationship("User", foreign_keys=[driver_id])


class Package(TenantScoped, Base):
    """بسته یک سفارش با ابعاد و وزن واقعی؛ مبنای برگه بسته‌بندی و ظرفیت محموله."""
    __tablename__ = "packages"
    __table_args__ = (
        CheckConstraint("weight_kg > 0 AND length_cm > 0 AND width_cm > 0 AND height_cm > 0", name="ck_packages_size"),
        UniqueConstraint("order_id", "sequence", name="uq_packages_order_sequence"),
    )

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), nullable=False, unique=True, index=True)       # کد رهگیری سفارش + شماره بسته
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    length_cm = Column(Float, nullable=False)
    width_cm = Column(Float, nullable=False)
    height_cm = Column(Float, nullable=False)
    weight_kg = Column(Float, nullable=False)
    created_at = Column(DateTime, nullable=False, default=_now)
    packed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    items = relationship("PackageItem", back_populates="package", cascade="all, delete-orphan", order_by="PackageItem.id")

    @property
    def volume_m3(self) -> float:
        return self.length_cm * self.width_cm * self.height_cm / 1_000_000


class PackageItem(TenantScoped, Base):
    __tablename__ = "package_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_package_items_quantity"),)

    id = Column(Integer, primary_key=True, index=True)
    package_id = Column(Integer, ForeignKey("packages.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)

    package = relationship("Package", back_populates="items")
    product = relationship("Product")


# ---------------------------------------------------------------------------
# فصل ۱۵ — تعیین تکلیف
# ---------------------------------------------------------------------------
class Disposition(TenantScoped, Base):
    """
    تصمیم ثبت‌شده درباره کالای نگه‌داشته (مردود، معیوب، آسیب‌دیده، قرنطینه، در تعمیر): امحا، تعمیر، برگشت به
    تأمین‌کننده یا بازرسی دوباره — همراه با سند انبار، دلیل و انجام‌دهنده (سابقه کامل و غیرقابل‌حذف).
    """
    __tablename__ = "dispositions"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_dispositions_quantity"),
        CheckConstraint(f"action IN ({sql_in(DISPOSITION_ACTIONS)})", name="ck_dispositions_action"),
        CheckConstraint(f"from_status IN ({sql_in(STOCK_STATUSES)})", name="ck_dispositions_from_status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(16), nullable=False, unique=True, index=True)       # DS-...
    action = Column(String(24), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    lot_number = Column(String(64), nullable=True)
    from_status = Column(String(16), nullable=False)
    quantity = Column(Integer, nullable=False)
    partner_id = Column(Integer, ForeignKey("partners.id"), nullable=True)          # تأمین‌کننده (برگشت)
    receipt_id = Column(Integer, ForeignKey("inbound_receipts.id"), nullable=True, index=True)  # رسید اصلی
    reason = Column(String(500), nullable=False)
    document_id = Column(Integer, ForeignKey("stock_documents.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    product = relationship("Product")
    warehouse = relationship("Warehouse")
    location = relationship("Location")
    partner = relationship("Partner")
    document = relationship("StockDocument")
    created_by = relationship("User")
