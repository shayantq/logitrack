import enum
from datetime import datetime, timezone
import secrets
from sqlalchemy import Column, Integer, String, Float, ForeignKey, Enum, Boolean, Date, DateTime, Time, UniqueConstraint, CheckConstraint, Text, JSON, and_
from sqlalchemy.orm import relationship
from app.database import Base
from app.core.tenancy import TenantScoped
from app.core.wms import AVAILABLE, ORDER_STOCK_STATES, STOCK_STATUSES, WAREHOUSE_TYPES, sql_in


class RoleEnum(str, enum.Enum):
    # کارکنان پلتفرم پسینه — به هیچ سازمانی تعلق ندارند
    PLATFORM_ADMIN = "platform_admin"
    PLATFORM_SUPPORT = "platform_support"
    # کاربران یک سازمان (مشتری‌ای که پسینه را خریده)
    ORG_ADMIN = "org_admin"
    WAREHOUSE_MANAGER = "warehouse_manager"
    DRIVER = "driver"


PLATFORM_ROLES = (RoleEnum.PLATFORM_ADMIN, RoleEnum.PLATFORM_SUPPORT)
TENANT_ROLES = (RoleEnum.ORG_ADMIN, RoleEnum.WAREHOUSE_MANAGER, RoleEnum.DRIVER)


# مقادیر مجاز ستون‌های Enum (منبع واحد برای مدل، اسکیماها و سرویس‌ها)
VEHICLE_TYPES = ("motorcycle", "sedan", "pickup", "van", "truck")
# «busy» از مرحله ۷ دیگر تنظیم نمی‌شود (در دسترس بودن از روی بازه زمانی سفارش‌ها حساب می‌شود)؛
# فقط برای سازگاری با داده‌های قدیمی در enum مانده است.
VEHICLE_STATUSES = ("available", "on_route", "maintenance", "inactive", "busy")
EMPLOYMENT_TYPES = ("full_time", "part_time")
PACKAGE_SIZES = ("xs", "s", "m", "l", "xl")
ORDER_STATUSES = (
    "pending",       # ثبت‌شده، در انتظار تخصیص خودرو
    "assigned",      # خودرو/راننده تعیین شد
    "picking_up",    # راننده در راه انبار برای تحویل گرفتن بار
    "picked_up",     # بار از انبار تحویل گرفته شد
    "in_transit",    # در مسیر مقصد
    "delivered",     # تحویل مشتری شد
    "failed",        # تحویل ناموفق (بار به انبار برمی‌گردد)
    "canceled",      # لغو شد
    "expired",       # بازه تحویل گذشت و انجام نشد
)
FINAL_ORDER_STATUSES = ("delivered", "failed", "canceled", "expired")
# سفارش‌هایی که هنوز تمام نشده‌اند (موجودی از انبار کم شده و خودرو درگیر است)
ACTIVE_ORDER_STATUSES = ("pending", "assigned", "picking_up", "picked_up", "in_transit")


# مقادیر مجاز پروفایل سازمان (منبع واحد برای اسکیماها و فرم‌ها)
BUSINESS_TYPES = ("retail", "ecommerce", "wholesale", "warehouse_3pl", "manufacturing", "healthcare", "food", "other")
EMPLOYEE_RANGES = ("1-10", "11-50", "51-200", "201-1000", "1000+")
ORDER_VOLUMES = ("<100", "100-1000", "1000-10000", "10000+")
PLATFORM_FEATURES = ("transport", "warehouse", "stocktaking", "accounting", "reports", "api")
REQUEST_STATUSES = ("pending", "approved", "rejected")

# احراز هویت راننده (فقط برای نقش driver معنا دارد)
DRIVER_STATUSES = (
    "incomplete",   # با لینک دعوت ثبت‌نام کرده و در حال تکمیل اطلاعات و مدارک است
    "submitted",    # مدارک ارسال شده و منتظر بررسی ادمین سازمان است
    "approved",     # تأییدشده — فقط این رانندگان سفارش می‌گیرند
    "rejected",     # رد شده (با دلیل)؛ می‌تواند اصلاح و دوباره ارسال کند
)
DRIVER_DOCUMENT_KINDS = (
    "national_card",          # کارت ملی
    "selfie",                 # عکس سلفی
    "video",                  # ویدیوی احراز هویت
    "driving_license",        # گواهینامه
    "vehicle_photo",          # عکس خودرو
    "vehicle_card",           # کارت خودرو
    "technical_inspection",   # برگه معاینه فنی
)


class OrganizationProfileMixin:
    """
    اطلاعات هویتی و تجاری یک کسب‌وکار — هم در درخواست ثبت سازمان و هم در
    خود سازمان؛ هنگام تأیید درخواست، همین فیلدها به سازمان منتقل می‌شوند.
    """
    legal_name = Column(String(200), nullable=True)            # نام ثبتی/حقوقی
    business_type = Column(String(32), nullable=True)
    national_id = Column(String(11), nullable=True)             # شناسه ملی اشخاص حقوقی
    economic_code = Column(String(14), nullable=True)           # کد اقتصادی
    registration_number = Column(String(32), nullable=True)     # شماره ثبت
    province = Column(String(64), nullable=True)
    city = Column(String(64), nullable=True)
    address = Column(String(500), nullable=True)
    postal_code = Column(String(10), nullable=True)
    phone = Column(String(20), nullable=True)
    website = Column(String(200), nullable=True)
    employee_count = Column(String(16), nullable=True)          # بازه تعداد کارکنان
    monthly_order_volume = Column(String(16), nullable=True)    # بازه تعداد سفارش ماهانه
    warehouse_count = Column(Integer, nullable=True)
    fleet_size = Column(Integer, nullable=True)
    contact_name = Column(String(100), nullable=True)
    contact_mobile = Column(String(11), nullable=True)
    contact_email = Column(String(254), nullable=True)


PROFILE_FIELDS = tuple(
    name for name, value in vars(OrganizationProfileMixin).items() if isinstance(value, Column)
)


class Organization(OrganizationProfileMixin, Base):
    """سازمان/کسب‌وکاری که از پسینه استفاده می‌کند — همه داده‌ها زیر یک سازمان‌اند."""
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=True, onupdate=lambda: datetime.now(timezone.utc))
    name = Column(String, nullable=False)
    # شناسه کوتاه و یکتا (انگلیسی) برای آدرس‌ها و API
    slug = Column(String(64), nullable=False, unique=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    # مسیر نسبی لوگو در MEDIA_ROOT (برای سربرگ گزارش‌های اختصاصی سازمان)
    logo_path = Column(String(255), nullable=True)
    # رنگ سازمان در سربرگ و جدول گزارش‌های اکسل/PDF (مثل #0D9488)
    brand_color = Column(String(9), nullable=True)
    # سیاست انبار: پیش‌فرض‌های فرمول نقطه سفارش و برآورد سرمایه خرید (replenishment_service.DEFAULT_POLICY)
    inventory_policy = Column(JSON, nullable=True)


class OrganizationRequest(OrganizationProfileMixin, Base):
    """درخواست استفاده از پسینه که از لندینگ پیج (بدون لاگین) ثبت و توسط ادمین پلتفرم بررسی می‌شود."""
    __tablename__ = "organization_requests"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # کدی که متقاضی با آن وضعیت درخواستش را پیگیری می‌کند
    tracking_code = Column(String(16), nullable=False, unique=True, index=True)
    name = Column(String(200), nullable=False)                  # نام تجاری/نمایشی
    requested_features = Column(JSON, nullable=False, default=list)
    notes = Column(Text, nullable=True)
    # «چطور با ما آشنا شدید؟» — اختیاری؛ برای «سایر» توضیح متقاضی در referral_detail
    referral_source = Column(String(24), nullable=True, index=True)
    referral_detail = Column(String(200), nullable=True)
    status = Column(String(16), nullable=False, default="pending", index=True)
    requester_ip = Column(String(45), nullable=True)

    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    # سازمانی که پس از تأیید از روی این درخواست ساخته شد
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)

    organization = relationship("Organization")


class User(TenantScoped, Base):
    __tablename__ = "users"
    # کارکنان پلتفرم organization_id ندارند
    __tenant_nullable__ = True
    __table_args__ = (
        CheckConstraint("role IN (" + ", ".join(f"'{r.value}'" for r in RoleEnum) + ")", name="ck_users_role"),
        # کاربر سازمانی حتماً سازمان دارد و کارکنان پلتفرم هرگز
        CheckConstraint(
            "(role IN ('platform_admin', 'platform_support')) = (organization_id IS NULL)",
            name="ck_users_role_organization",
        ),
        CheckConstraint("driver_status IN (" + ", ".join(f"'{s}'" for s in DRIVER_STATUSES) + ")",
                        name="ck_users_driver_status"),
    )

    id = Column(Integer, primary_key=True, index=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    username = Column(String, nullable=False, unique=True, index=True)
    email = Column(String, nullable=True, unique=True)
    full_name = Column(String, nullable=True)
    driver_code = Column(String, unique=True, nullable=True)
    # به‌صورت رشته ذخیره می‌شود (نه enum دیتابیس) تا افزودن نقش جدید نیازی به ALTER TYPE نداشته باشد
    role = Column(
        Enum(RoleEnum, native_enum=False, length=32, validate_strings=True,
             values_callable=lambda roles: [r.value for r in roles]),
        default=RoleEnum.DRIVER, nullable=False,
    )
    hashed_password = Column(String, nullable=False)

    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", use_alter=True, name="fk_users_vehicle_id"), nullable=True)
    city = Column(String, nullable=True)
    # وضعیت احراز هویت راننده. رانندگانی که ادمین مستقیماً می‌سازد «تأییدشده»اند (ادمین ضامن است)؛
    # رانندگانی که خودشان با لینک دعوت ثبت‌نام می‌کنند از «incomplete» شروع می‌کنند.
    driver_status = Column(String(16), nullable=False, default="approved", server_default="approved")
    # مدیریت حساب (مرحله ۱۵): غیرفعال‌سازی به‌جای حذف، رمز موقت، قفل موقت پس از تلاش‌های ناموفق
    mobile = Column(String(11), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    must_change_password = Column(Boolean, nullable=False, default=False, server_default="false")
    # با هر بازنشانی/تغییر رمز یا غیرفعال‌سازی یکی زیاد می‌شود تا توکن‌های قبلی باطل شوند
    token_version = Column(Integer, nullable=False, default=0, server_default="0")
    failed_logins = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    # راهنمای تعاملی: {"<شناسه راهنما>": "done" | "skipped"} — فقط بار اول خودکار باز می‌شود
    tour_state = Column(JSON, nullable=True)

    # ⚠️ عمداً cascade حذف ندارد: حذف یک راننده نباید خودروها و (به‌تبع آن)
    # تاریخچه سفارش‌ها را پاک کند. قوانین حذف در user_service اعمال می‌شود.
    vehicles = relationship("Vehicle", back_populates="user", foreign_keys="[Vehicle.driver_id]")
    organization = relationship("Organization")


class Vehicle(TenantScoped, Base):
    __tablename__ = "vehicles"
    __table_args__ = (UniqueConstraint("organization_id", "license_plate", name="uq_vehicles_org_plate"),)

    id = Column(Integer, primary_key=True, index=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    license_plate = Column(String(15), nullable=True)
    plate_number = Column(String, unique=True, nullable=True)
    model = Column(String, nullable=True)
    type = Column(Enum(*VEHICLE_TYPES, name="vehicle_type"), nullable=True)
    capacity_kg = Column(Integer, nullable=True)
    max_weight_kg = Column(Float, nullable=True)
    max_volume_m3 = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    status = Column(Enum(*VEHICLE_STATUSES, name="vehicle_status"), default="available")
    city = Column(String, nullable=True)
    
    driver_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)

    user = relationship("User", back_populates="vehicles", foreign_keys=[driver_id])
    # بدون cascade حذف: با حذف خودرو، سفارش‌های قدیمی باقی می‌مانند و فقط vehicle_id آن‌ها NULL می‌شود
    orders = relationship("Order", back_populates="vehicle")

class Warehouse(TenantScoped, Base):
    """
    انبار یا سایت انبار. نوع (app/core/wms.WAREHOUSE_TYPES) رفتار را تعیین می‌کند: ارسال سفارش، رسید مستقیم،
    وضعیت کیفی پیش‌فرض کالای رسیده. parent_id سلسله‌مراتب (مثلاً سایت ← انبارها) را می‌سازد.
    """
    __tablename__ = "warehouses"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_warehouses_org_code"),
        CheckConstraint(f"type IN ({sql_in(WAREHOUSE_TYPES)})", name="ck_warehouses_type"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_warehouses_parent_self"),
    )

    id = Column(Integer, primary_key=True, index=True)
    # کد کوتاه یکتا در سازمان (برای برچسب، اسناد و یکپارچه‌سازی)؛ اگر داده نشود ساخته می‌شود
    code = Column(String(16), nullable=False, default=lambda: "WH-" + secrets.token_hex(3).upper())
    name = Column(String)
    type = Column(String(24), nullable=False, default="general", server_default="general")
    parent_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    location = Column(String)                       # نشانی
    # مبدأ مسیر سفارش‌ها روی نقشه (مرحله ۱۰)
    province = Column(String(64), nullable=True)
    city = Column(String(64), nullable=True)
    # انبارگردانی دوره‌ای: هر چند روز یک‌بار (خالی = بدون برنامه)
    stocktake_interval_days = Column(Integer, nullable=True)

    inventories = relationship("Inventory", viewonly=True)
    parent = relationship("Warehouse", remote_side=[id])


class Product(TenantScoped, Base):
    __tablename__ = "products"
    # کد کالا و بارکد فقط در هر سازمان یکتاست (دو سازمان می‌توانند SKU یکسان داشته باشند).
    # SKU پس از ثبت تغییرناپذیر است (محافظ در app/services/stock_ledger.py).
    __table_args__ = (
        UniqueConstraint("organization_id", "sku", name="uq_products_org_sku"),
        UniqueConstraint("organization_id", "barcode", name="uq_products_org_barcode"),
        CheckConstraint("net_weight_kg IS NULL OR weight_kg IS NULL OR net_weight_kg <= weight_kg", name="ck_products_net_weight"),
        CheckConstraint("(length_cm IS NULL OR length_cm > 0) AND (width_cm IS NULL OR width_cm > 0) AND (height_cm IS NULL OR height_cm > 0)",
                        name="ck_products_dimensions"),
        CheckConstraint("NOT expiry_tracked OR lot_tracked", name="ck_products_expiry_needs_lot"),
        CheckConstraint("shelf_life_days IS NULL OR shelf_life_days > 0", name="ck_products_shelf_life"),
        CheckConstraint("(min_stock IS NULL OR min_stock >= 0) AND (reorder_point IS NULL OR reorder_point >= 0) "
                        "AND (max_stock IS NULL OR min_stock IS NULL OR max_stock >= min_stock)", name="ck_products_thresholds"),
    )

    id = Column(Integer, primary_key=True, index=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    name = Column(String, nullable=False)                   # نام کامل
    short_name = Column(String(60), nullable=True)          # نام کوتاه برای برچسب و اسناد
    sku = Column(String, index=True, nullable=False)
    weight_kg = Column(Float, default=1.0)                  # وزن ناخالص هر واحد پایه (مبنای ظرفیت خودرو)
    net_weight_kg = Column(Float, nullable=True)
    length_cm = Column(Float, nullable=True)
    width_cm = Column(Float, nullable=True)
    height_cm = Column(Float, nullable=True)
    # ردیابی: بچ/سری ساخت، شماره سریال، تاریخ انقضا (انقضا بدون بچ معنا ندارد)
    lot_tracked = Column(Boolean, nullable=False, default=False, server_default="false")
    serial_tracked = Column(Boolean, nullable=False, default=False, server_default="false")
    expiry_tracked = Column(Boolean, nullable=False, default=False, server_default="false")
    shelf_life_days = Column(Integer, nullable=True)
    # آستانه‌ها (پیش‌فرض ردیف‌های موجودی جدید؛ هر انبار می‌تواند نقطه سفارش خودش را داشته باشد)
    min_stock = Column(Integer, nullable=True)
    max_stock = Column(Integer, nullable=True)
    reorder_point = Column(Integer, nullable=True)
    # قیمت نهایی «امروز» (کش) — منبع اصلی تاریخچه product_prices است (مرحله ۱۳)
    price = Column(Float, default=0.0, nullable=False)
    # مشخصات تکمیلی کاتالوگ (مرحله ۱۳)
    updated_at = Column(DateTime, nullable=True)
    category = Column(String(100), nullable=True, index=True)
    brand = Column(String(100), nullable=True)
    unit = Column(String(32), nullable=False, default="عدد")                 # واحد پایه — مقادیر موجودی عدد صحیحِ این واحدند
    barcode = Column(String(64), nullable=True)
    description = Column(Text, nullable=True)
    origin = Column(String(16), nullable=False, default="domestic")          # domestic | imported
    origin_country = Column(String(64), nullable=True)
    export_eligible = Column(Boolean, nullable=False, default=False)
    hs_code = Column(String(16), nullable=True)                              # کد تعرفه گمرکی
    specs = Column(JSON, nullable=True)                                      # [[«ویژگی»، «مقدار»], ...]
    # تنوع: همان کالا با مبدأ/سری متفاوت، کد و قیمت جدا (مثلاً «PS5 — امارات» و «PS5 — چین»)
    parent_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    variant_label = Column(String(100), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    # همه ردیف‌های موجودی (همه وضعیت‌های کیفی). بدون cascade: کالای دارای سابقه حذف نمی‌شود، بایگانی می‌شود.
    stock_rows = relationship("Inventory", back_populates="product")
    # فقط ردیف‌های «سالم و آزاد» — موجودی قابل فروش، نقطه سفارش و برنامه خرید
    inventories = relationship(
        "Inventory", viewonly=True,
        primaryjoin=lambda: and_(Product.id == Inventory.product_id, Inventory.stock_status == AVAILABLE),
    )
    order_items = relationship("OrderItem", back_populates="product")
    prices = relationship("ProductPrice", back_populates="product", cascade="all, delete-orphan",
                          order_by="ProductPrice.effective_from")
    uoms = relationship("ProductUom", back_populates="product", cascade="all, delete-orphan", order_by="ProductUom.factor")
    suppliers = relationship("ProductSupplier", back_populates="product", cascade="all, delete-orphan",
                             order_by="ProductSupplier.id")


class Inventory(TenantScoped, Base):
    """
    موجودی یک کالا در یک انبار با یک وضعیت کیفی (هر ترکیب کالا × انبار × وضعیت یک ردیف).
    quantity = موجودی فیزیکی و فقط از app/services/stock_ledger.py (همراه با سند و گردش) تغییر می‌کند.
    reserved_quantity = جمع رزروهای فعال و فقط از app/services/allocation_service.py تغییر می‌کند.
    موجودی آزاد = quantity − reserved_quantity. رزرو فقط روی ردیف «سالم و آزاد» ممکن است و
    پارامترهای نقطه سفارش هم فقط روی همین ردیف معنا دارند.
    """
    __tablename__ = "inventories"
    __table_args__ = (
        UniqueConstraint("organization_id", "product_id", "warehouse_id", "stock_status", name="uq_inventories_bucket"),
        CheckConstraint(f"stock_status IN ({sql_in(STOCK_STATUSES)})", name="ck_inventories_stock_status"),
        CheckConstraint("reserved_quantity >= 0 AND reserved_quantity <= quantity", name="ck_inventories_reserved"),
        CheckConstraint(f"stock_status = '{AVAILABLE}' OR reserved_quantity = 0", name="ck_inventories_reserve_available_only"),
        CheckConstraint("quantity >= 0", name="ck_inventories_quantity_non_negative"),
        CheckConstraint("rop_mode IN ('manual', 'auto')", name="ck_inventories_rop_mode"),
        CheckConstraint("service_level IS NULL OR (service_level >= 0.5 AND service_level < 1)", name="ck_inventories_service_level"),
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="ck_inventories_lead_time"),
    )

    id = Column(Integer, primary_key=True, index=True, nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    stock_status = Column(String(16), nullable=False, default=AVAILABLE, server_default=AVAILABLE)
    quantity = Column(Integer, default=0, nullable=False)
    reserved_quantity = Column(Integer, nullable=False, default=0, server_default="0")
    reorder_point = Column(Integer, default=10)
    ever_exceeded_reorder = Column(Boolean, default=False)
    # هشدار «رسیدن به نقطه سفارش» برای این دور داده شده؛ با پر شدن دوباره (بالای نقطه سفارش) صفر می‌شود
    low_alerted = Column(Boolean, nullable=False, default=False, server_default="false")
    warehouse_name = Column(String, default="Central Warehouse")
    # نقطه سفارش با فرمول (app/services/replenishment_service.py): manual = عدد دستی، auto = محاسبه روزانه از تقاضا.
    # پارامترهای خالی از سیاست انبار سازمان (organizations.inventory_policy) گرفته می‌شوند.
    rop_mode = Column(String(8), nullable=False, default="manual", server_default="manual")
    lead_time_days = Column(Float, nullable=True)          # زمان تأمین (روز)
    lead_time_std_days = Column(Float, nullable=True)      # انحراف معیار زمان تأمین (روز)
    service_level = Column(Float, nullable=True)           # سطح خدمت هدف، مثلاً ۰٫۹۵
    avg_daily_demand = Column(Float, nullable=True)        # آخرین محاسبه
    demand_std = Column(Float, nullable=True)
    safety_stock = Column(Integer, nullable=True)
    suggested_order_qty = Column(Integer, nullable=True)
    rop_calculated_at = Column(DateTime, nullable=True)

    product = relationship("Product", back_populates="stock_rows")
    warehouse = relationship("Warehouse")
    movements = relationship("StockMovement", back_populates="inventory", order_by="StockMovement.id")

    @property
    def free_quantity(self) -> int:
        """موجودی آزاد (قابل وعده به سفارش جدید)."""
        return (self.quantity or 0) - (self.reserved_quantity or 0)


# انواع گردش کالا — منبع واحد برای مدل، اسکیماها و فرانت
MOVEMENT_TYPES = (
    "initial",        # موجودی اولیه / اول دوره
    "receipt",        # ورود کالا (خرید، تحویل از تأمین‌کننده)
    "order_out",      # خروج بابت سفارش
    "order_return",   # برگشت به انبار (سفارش ناموفق/حذف‌شده)
    "adjustment",     # اصلاح دستی موجودی
    "damage",         # ضایعات / کسری / مفقودی
    "transfer_out",   # انتقال به انبار دیگر (خروج)
    "transfer_in",    # انتقال از انبار دیگر (ورود)
    "stocktake",      # اصلاح ناشی از انبارگردانی (مرحله انبارگردانی)
    "status_out",     # تغییر وضعیت کیفی: خروج از وضعیت قبلی (مثلاً قرنطینه)
    "status_in",      # تغییر وضعیت کیفی: ورود به وضعیت جدید (مثلاً سالم و آزاد)
)


class StockMovement(TenantScoped, Base):
    """
    دفتر گردش کالا: هر تغییر موجودی یک ردیف غیرقابل‌ویرایش و غیرقابل‌حذف که به یک سند انبار
    (StockDocument) تعلق دارد. همیشه برقرار است:
    Inventory.quantity == مجموع quantity_change گردش‌های همان ردیف موجودی
    اصلاح فقط با سند برگشت: گردش قرینه با reversal_of_id (هر گردش حداکثر یک‌بار برگشت می‌خورد).
    """
    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("quantity_change <> 0", name="ck_stock_movements_nonzero"),
        UniqueConstraint("reversal_of_id", name="uq_stock_movements_reversal"),
    )

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    document_id = Column(Integer, ForeignKey("stock_documents.id"), index=True, nullable=False)
    inventory_id = Column(Integer, ForeignKey("inventories.id"), index=True, nullable=False)
    # برای فیلتر و گزارش سریع (تکرار از روی inventory)
    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), index=True, nullable=True)
    stock_status = Column(String(16), nullable=False, default=AVAILABLE, server_default=AVAILABLE)
    movement_type = Column(String(32), nullable=False, index=True)
    quantity_change = Column(Integer, nullable=False)     # مثبت = ورود، منفی = خروج
    balance_after = Column(Integer, nullable=False)       # مانده همان انبار پس از این گردش
    reason = Column(String(500), nullable=True)
    # مرجع گردش: مثلاً ("order", شناسه سفارش) یا ("transfer", شناسه گردش خروجی)
    reference_type = Column(String(32), nullable=True)
    reference_id = Column(Integer, nullable=True)
    reversal_of_id = Column(Integer, ForeignKey("stock_movements.id"), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    document = relationship("StockDocument", back_populates="movements")
    inventory = relationship("Inventory", back_populates="movements")
    product = relationship("Product")
    warehouse = relationship("Warehouse")
    created_by = relationship("User")


class Customer(TenantScoped, Base):
    """مشتری نهایی یک سازمان — با شماره همراه شناخته می‌شود (هر سازمان مشتریان خودش را دارد)."""
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("organization_id", "mobile", name="uq_customers_org_mobile"),)

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    name = Column(String(150), nullable=False)
    mobile = Column(String(11), nullable=False, index=True)
    email = Column(String(254), nullable=True)

    orders = relationship("Order", back_populates="customer")


class Order(TenantScoped, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("status IN (" + ", ".join(f"'{s}'" for s in ORDER_STATUSES) + ")", name="ck_orders_status"),
        CheckConstraint(f"stock_state IN ({sql_in(ORDER_STOCK_STATES)})", name="ck_orders_stock_state"),
        UniqueConstraint("organization_id", "idempotency_key", name="uq_orders_idempotency"),
    )

    id = Column(Integer, primary_key=True, index=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    # کد پیگیری یکتا در کل پلتفرم (برای پیگیری عمومی توسط مشتری نهایی)
    tracking_code = Column(String(16), nullable=False, unique=True, index=True)
    # رشته (نه enum دیتابیس) تا افزودن وضعیت جدید نیازی به ALTER TYPE نداشته باشد
    status = Column(String(32), nullable=False, index=True)
    size = Column(Enum(*PACKAGE_SIZES, name="package_size"), nullable=False)
    priority = Column(Boolean, nullable=False)
    delivery_window_start = Column(DateTime, nullable=False)
    delivery_window_end = Column(DateTime, nullable=False, index=True)
    notes = Column(String(1000), nullable=True)

    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), index=True, nullable=True)
    recipient_name = Column(String(150), nullable=True)
    recipient_mobile = Column(String(11), nullable=True)
    destination_province = Column(String(64), nullable=True, index=True)
    destination_city = Column(String(64), nullable=False, index=True)
    destination_address = Column(String(500), nullable=True)
    destination_postal_code = Column(String(10), nullable=True)

    # انبار مبدأ — موجودی همه اقلام از همین انبار رزرو/کم و در صورت برگشت به همین انبار برمی‌گردد
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True)
    # وضعیت کالای سفارش در انبار، جدا از وضعیت حمل: رزرو ← خروج (بارگیری) ← برگشت؛ یا رزرو ← آزادسازی
    stock_state = Column(String(16), nullable=False, default="reserved")
    # تکرار همین درخواست با همین کلید، سفارش دوم نمی‌سازد
    idempotency_key = Column(String(64), nullable=True)
    request_hash = Column(String(64), nullable=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="SET NULL"), index=True, nullable=True)

    # جمع‌ها هنگام ثبت محاسبه و ذخیره می‌شوند (برای گزارش سریع)
    total_quantity = Column(Integer, nullable=False, default=0)
    total_weight_kg = Column(Float, nullable=False, default=0)
    total_price = Column(Float, nullable=False, default=0)

    # مرحله ۸: راننده‌ای که سفارش به او سپرده شد (مستقل از اینکه خودرو بعداً به چه کسی برسد)
    driver_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    delivery_fee = Column(Float, nullable=True)            # کرایه حمل (ریال)
    delivered_at = Column(DateTime, nullable=True, index=True)
    # تسویه در لحظه تحویل محاسبه و «منجمد» می‌شود؛ تغییر بعدی قوانین سفارش‌های گذشته را عوض نمی‌کند
    commission_level = Column(String(32), nullable=True)   # کد سطح راننده در لحظه تحویل
    day_trip_number = Column(Integer, nullable=True)        # چندمین سفر تحویل‌شده راننده در آن روز
    commission_percent = Column(Float, nullable=True)       # درصد مؤثر (سطح × پله روزانه)
    commission_amount = Column(Float, nullable=True)        # سهم سازمان از کرایه
    driver_earning = Column(Float, nullable=True)           # سهم راننده از کرایه
    rating_token = Column(String(32), nullable=True, unique=True, index=True)   # لینک نظرسنجی مشتری
    # مسیر شهربه‌شهر (مرحله ۱۰): با شروع حرکت ثابت می‌شود تا تغییرات بعدی انبار/گراف، مسیر در حال اجرا را عوض نکند
    route = Column(JSON, nullable=True)

    vehicle = relationship("Vehicle", back_populates="orders")
    customer = relationship("Customer", back_populates="orders")
    warehouse = relationship("Warehouse")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id")
    history = relationship("OrderStatusHistory", back_populates="order", cascade="all, delete-orphan",
                           order_by="OrderStatusHistory.id")


class OrderItem(TenantScoped, Base):
    """
    یک قلم کالا در سفارش. نام، کد، قیمت و وزن کالا «در لحظه ثبت سفارش»
    ذخیره می‌شوند؛ تغییر بعدی قیمت/مشخصات کالا سفارش‌های قبلی را عوض نمی‌کند.
    """
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),)

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), index=True, nullable=True)
    product_name = Column(String(200), nullable=False)
    product_sku = Column(String(64), nullable=True)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False, default=0)
    unit_weight_kg = Column(Float, nullable=False, default=0)

    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")


class OrderStatusHistory(TenantScoped, Base):
    """هر تغییر وضعیت سفارش: از چه وضعیتی، به چه وضعیتی، توسط چه کسی، کی، با چه توضیحی."""
    __tablename__ = "order_status_history"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False)
    from_status = Column(String(32), nullable=True)
    to_status = Column(String(32), nullable=False)
    changed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    changed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note = Column(String(500), nullable=True)

    order = relationship("Order", back_populates="history")
    changed_by = relationship("User")


class OrderCheckpoint(TenantScoped, Base):
    """گزارش راننده «رسیدم به شهر X» روی مسیر سفارش (seq = شماره شهر در مسیر، مبدأ = ۰)."""
    __tablename__ = "order_checkpoints"
    __table_args__ = (UniqueConstraint("order_id", "seq", name="uq_order_checkpoints_order_seq"),)

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False)
    seq = Column(Integer, nullable=False)
    city = Column(String(64), nullable=False)
    province = Column(String(64), nullable=True)
    reached_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    reported_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class DriverInvite(TenantScoped, Base):
    """لینک/کد دعوت سازمان برای ثبت‌نام رانندگان (/join/<code>)."""
    __tablename__ = "driver_invites"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # یکتا در کل پلتفرم — سازمان از روی همین کد پیدا می‌شود
    code = Column(String(16), nullable=False, unique=True, index=True)
    label = Column(String(100), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at = Column(DateTime, nullable=True)          # خالی = بدون تاریخ انقضا
    max_uses = Column(Integer, nullable=True)             # خالی = نامحدود
    uses = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)


class DriverProfile(TenantScoped, Base):
    """پرونده احراز هویت راننده: مشخصات فردی، محل سکونت، مشخصات وسیله و نتیجه بررسی."""
    __tablename__ = "driver_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    invite_id = Column(Integer, ForeignKey("driver_invites.id", ondelete="SET NULL"), nullable=True)

    # مشخصات فردی
    first_name = Column(String(64), nullable=True)
    last_name = Column(String(64), nullable=True)
    national_code = Column(String(10), nullable=True)     # کد ملی ۱۰ رقمی
    birth_date = Column(Date, nullable=True)
    mobile = Column(String(11), nullable=True)
    # محل سکونت
    province = Column(String(64), nullable=True)
    city = Column(String(64), nullable=True)
    address = Column(String(500), nullable=True)
    postal_code = Column(String(10), nullable=True)
    # وسیله نقلیه
    vehicle_type = Column(String(16), nullable=True)
    vehicle_model = Column(String(64), nullable=True)
    vehicle_color = Column(String(32), nullable=True)
    license_plate = Column(String(15), nullable=True)
    max_weight_kg = Column(Integer, nullable=True)        # سقف وزن بار
    intercity = Column(Boolean, nullable=False, default=False)   # امکان بار بین‌شهری
    inspection_expiry = Column(Date, nullable=True)       # اعتبار معاینه فنی

    # برنامه کاری (مرحله ۷) — شیفت‌ها در DriverShift
    employment_type = Column(String(16), nullable=False, default="full_time", server_default="full_time")
    max_daily_orders = Column(Integer, nullable=True)     # سقف سفارش در روز؛ خالی = بدون سقف

    submitted_at = Column(DateTime, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rejection_reason = Column(String(500), nullable=True)
    # خودرویی که پس از تأیید از روی همین پرونده ساخته شد
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    documents = relationship("DriverDocument", primaryjoin="DriverProfile.user_id == foreign(DriverDocument.user_id)",
                             viewonly=True, order_by="DriverDocument.id")


class DriverDocument(TenantScoped, Base):
    """فایل یک مدرک راننده (هر نوع مدرک حداکثر یک فایل؛ آپلود دوباره جایگزین می‌کند)."""
    __tablename__ = "driver_documents"
    __table_args__ = (UniqueConstraint("user_id", "kind", name="uq_driver_documents_user_kind"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(32), nullable=False)
    file_path = Column(String(255), nullable=False)       # مسیر نسبی در MEDIA_ROOT — هرگز عمومی سرو نمی‌شود
    content_type = Column(String(64), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DriverShift(TenantScoped, Base):
    """
    یک بازه کاری هفتگی راننده (به وقت ایران). weekday مثل پایتون: دوشنبه=۰ ... یکشنبه=۶
    (شنبه=۵). شیفت شبانه‌ای که از نیمه‌شب رد می‌شود را دو ردیف ثبت کنید.
    """
    __tablename__ = "driver_shifts"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_driver_shifts_weekday"),
        CheckConstraint("start_time < end_time", name="ck_driver_shifts_order"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    weekday = Column(Integer, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)


class DriverTimeOff(TenantScoped, Base):
    """مرخصی/عدم حضور راننده (UTC) — در این بازه به او سفارش پیشنهاد نمی‌شود."""
    __tablename__ = "driver_time_off"
    __table_args__ = (CheckConstraint("starts_at < ends_at", name="ck_driver_time_off_order"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    starts_at = Column(DateTime, nullable=False, index=True)
    ends_at = Column(DateTime, nullable=False, index=True)
    reason = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


RATING_SOURCES = ("organization", "customer", "platform")


class DriverRating(TenantScoped, Base):
    """امتیاز ۱ تا ۵ به راننده — از سازمان (برای هر سفارش)، مشتری (لینک سفارش) یا پلتفرم (ارزیابی کلی)."""
    __tablename__ = "driver_ratings"
    __table_args__ = (
        CheckConstraint("score BETWEEN 1 AND 5", name="ck_driver_ratings_score"),
        UniqueConstraint("order_id", "source", name="uq_driver_ratings_order_source"),
    )

    id = Column(Integer, primary_key=True, index=True)
    driver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    source = Column(String(16), nullable=False, index=True)
    score = Column(Integer, nullable=False)
    comment = Column(String(500), nullable=True)
    # برچسب‌های آماده (مثلاً «به‌موقع رسید») — جدا از متن نظر؛ متناسب با تعداد ستاره
    tags = Column(JSON, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class CommissionPlan(TenantScoped, Base):
    """
    قوانین کرایه، سطح‌بندی و پورسانت پلکانی هر سازمان (یک ردیف برای هر سازمان).
    levels: [{code, name, min_deliveries, min_days, min_rating, commission_percent}] از پایین به بالا
    tiers:  [{from_trip, multiplier_percent}] — پله‌های روزانه: از سفر Nام به بعد، درصد سطح × multiplier
    """
    __tablename__ = "commission_plans"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_commission_plans_org"),)

    id = Column(Integer, primary_key=True, index=True)
    base_fare = Column(Float, nullable=False, default=0)
    fare_per_kg = Column(Float, nullable=False, default=0)
    levels = Column(JSON, nullable=False)
    tiers = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    updated_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


# درخواست‌های راننده از پنل خودش
DRIVER_REQUEST_KINDS = ("leave", "vehicle_change")
DRIVER_REQUEST_STATUSES = ("draft", "pending", "approved", "rejected", "canceled")
LEAVE_TYPES = ("urgent", "normal")
LEAVE_CATEGORIES = ("sickness", "family", "personal", "vehicle_repair", "other")


class DriverRequest(TenantScoped, Base):
    """
    درخواست راننده برای ادمین سازمان: مرخصی (فوری/عادی) یا تغییر خودرو.
    درخواست تغییر خودرو تا آپلود مدارک «draft» است و با ارسال «pending» می‌شود.
    """
    __tablename__ = "driver_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(16), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="pending", index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    submitted_at = Column(DateTime, nullable=True)
    # مرخصی (UTC)
    leave_type = Column(String(16), nullable=True)
    category = Column(String(32), nullable=True)
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    reason = Column(String(500), nullable=True)
    time_off_id = Column(Integer, ForeignKey("driver_time_off.id", ondelete="SET NULL"), nullable=True)
    # تغییر خودرو: مشخصات خودروی جدید
    vehicle_data = Column(JSON, nullable=True)
    # بررسی
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    review_note = Column(String(500), nullable=True)


class DriverRequestDocument(TenantScoped, Base):
    """مدارک خودروی جدید در درخواست تغییر خودرو (پس از تأیید به مدارک راننده منتقل می‌شوند)."""
    __tablename__ = "driver_request_documents"
    __table_args__ = (UniqueConstraint("request_id", "kind", name="uq_driver_request_documents_kind"),)

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("driver_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(32), nullable=False)
    file_path = Column(String(255), nullable=False)
    content_type = Column(String(64), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# تیکت پشتیبانی (مرحله ۱۱): مشتری ← سازمان ← پشتیبانی پلتفرم
# ---------------------------------------------------------------------------
TICKET_SOURCES = ("customer", "driver", "org")          # چه کسی تیکت را باز کرده
TICKET_HANDLERS = ("org", "platform")                   # چه کسی الان مسئول پاسخ است
TICKET_STATUSES = ("open", "resolved", "closed")
TICKET_WAITING = ("requester", "org", "platform", "none")   # نوبت پاسخ با کیست
TICKET_PRIORITIES = ("normal", "high", "urgent")
TICKET_VISIBILITY = ("all", "staff", "side")           # همه / سازمان و پلتفرم / فقط سمت نویسنده


class Ticket(TenantScoped, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint("source IN ('customer', 'driver', 'org')", name="ck_tickets_source"),
        CheckConstraint("handler IN ('org', 'platform')", name="ck_tickets_handler"),
        CheckConstraint("status IN ('open', 'resolved', 'closed')", name="ck_tickets_status"),
        CheckConstraint("waiting_on IN ('requester', 'org', 'platform', 'none')", name="ck_tickets_waiting_on"),
        CheckConstraint("priority IN ('normal', 'high', 'urgent')", name="ck_tickets_priority"),
    )

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(16), nullable=False, unique=True, index=True)          # TK-XXXXXXX
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    last_activity_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    subject = Column(String(200), nullable=False)
    category = Column(String(32), nullable=False)
    priority = Column(String(16), nullable=False, default="normal")
    source = Column(String(16), nullable=False, index=True)
    handler = Column(String(16), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="open", index=True)
    waiting_on = Column(String(16), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    # درخواست‌کننده: کاربر (راننده/کارکنان سازمان) یا مشتری بدون حساب (نام + موبایل + لینک محرمانه)
    requester_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    requester_name = Column(String(150), nullable=True)
    requester_mobile = Column(String(11), nullable=True)
    access_token = Column(String(48), nullable=True, unique=True, index=True)
    assignee_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    escalated_at = Column(DateTime, nullable=True)
    escalation_reason = Column(String(1000), nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    messages = relationship("TicketMessage", back_populates="ticket", cascade="all, delete-orphan",
                            order_by="TicketMessage.id")


class TicketMessage(TenantScoped, Base):
    __tablename__ = "ticket_messages"
    __table_args__ = (
        CheckConstraint("visibility IN ('all', 'staff', 'side')", name="ck_ticket_messages_visibility"),
        CheckConstraint("author_side IN ('requester', 'org', 'platform', 'system')", name="ck_ticket_messages_side"),
    )

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    author_side = Column(String(16), nullable=False)
    author_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_name = Column(String(150), nullable=True)
    body = Column(Text, nullable=False)
    visibility = Column(String(16), nullable=False, default="all")
    attachment_path = Column(String(255), nullable=True)
    attachment_type = Column(String(64), nullable=True)

    ticket = relationship("Ticket", back_populates="messages")


# ---------------------------------------------------------------------------
# انبارگردانی (مرحله ۱۲): شمارش کور توسط مدیر انبار، تأیید و اصلاح موجودی توسط ادمین
# ---------------------------------------------------------------------------
STOCKTAKE_STATUSES = ("counting", "review", "approved", "canceled")
VARIANCE_REASONS = ("damage", "loss", "entry_error", "unrecorded", "unknown")


class Stocktake(TenantScoped, Base):
    __tablename__ = "stocktakes"
    __table_args__ = (
        CheckConstraint("status IN ('counting', 'review', 'approved', 'canceled')", name="ck_stocktakes_status"),
        CheckConstraint("scope IN ('full', 'partial')", name="ck_stocktakes_scope"),
    )

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(16), nullable=False, unique=True, index=True)           # ST-XXXXXX
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=True)
    scope = Column(String(16), nullable=False, default="full")
    status = Column(String(16), nullable=False, default="counting", index=True)
    note = Column(String(1000), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    submitted_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approved_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    canceled_at = Column(DateTime, nullable=True)

    lines = relationship("StocktakeLine", back_populates="stocktake", cascade="all, delete-orphan", order_by="StocktakeLine.id")


class StocktakeLine(TenantScoped, Base):
    """
    یک کالا در یک انبارگردانی. expected_qty موجودی سیستم «در لحظه شمارش» است (نه لحظه شروع)، پس عملیات
    انبار در طول انبارگردانی متوقف نمی‌شود: اصلاح نهایی = شمرده‌شده − موجودی سیستم در لحظه شمارش.
    """
    __tablename__ = "stocktake_lines"
    __table_args__ = (UniqueConstraint("stocktake_id", "product_id", name="uq_stocktake_lines_product"),
                      CheckConstraint("counted_qty IS NULL OR counted_qty >= 0", name="ck_stocktake_lines_counted"))

    id = Column(Integer, primary_key=True, index=True)
    stocktake_id = Column(Integer, ForeignKey("stocktakes.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    inventory_id = Column(Integer, ForeignKey("inventories.id", ondelete="SET NULL"), nullable=True)
    product_name = Column(String(200), nullable=False)
    product_sku = Column(String(64), nullable=True)
    unit_price = Column(Float, nullable=False, default=0)
    added_during_count = Column(Boolean, nullable=False, default=False)     # کالایی که در فهرست نبود و پیدا شد
    counted_qty = Column(Integer, nullable=True)
    expected_qty = Column(Integer, nullable=True)                           # برای شمارنده نمایش داده نمی‌شود
    counted_at = Column(DateTime, nullable=True)
    counted_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    previous_count = Column(Integer, nullable=True)                         # شمارش قبلی پیش از درخواست شمارش مجدد
    recount_note = Column(String(300), nullable=True)
    variance_reason = Column(String(32), nullable=True)
    adjustment = Column(Integer, nullable=True)                              # مقدار اصلاح‌شده هنگام تأیید

    stocktake = relationship("Stocktake", back_populates="lines")


class ProductPrice(TenantScoped, Base):
    """
    قیمت تاریخ‌دار کالا (مرحله ۱۳): از effective_from به بعد معتبر است تا قیمت بعدی.
    final_price = base_price × (۱ − subsidy_percent/۱۰۰). قیمت سفارش‌های قبلی روی خودشان ثبت شده و تغییر نمی‌کند.
    """
    __tablename__ = "product_prices"
    __table_args__ = (
        UniqueConstraint("product_id", "effective_from", name="uq_product_prices_day"),
        CheckConstraint("subsidy_percent >= 0 AND subsidy_percent < 100", name="ck_product_prices_subsidy"),
        CheckConstraint("base_price >= 0", name="ck_product_prices_base"),
    )

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    effective_from = Column(Date, nullable=False)                 # روز محلی ایران
    base_price = Column(Float, nullable=False)                    # قیمت پایه (ریال)
    subsidy_percent = Column(Float, nullable=False, default=0)
    final_price = Column(Float, nullable=False)                   # قیمت فروش پس از یارانه
    cost_price = Column(Float, nullable=True)                     # بهای تمام‌شده (اختیاری)
    note = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    product = relationship("Product", back_populates="prices")


class PasswordReset(Base):
    """کد یک‌بارمصرف بازیابی رمز (پیامک یا ایمیل). خود کد ذخیره نمی‌شود، فقط HMAC آن."""
    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash = Column(String(64), nullable=False)
    channel = Column(String(8), nullable=False)                 # sms | email
    created_at = Column(DateTime, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    used_at = Column(DateTime, nullable=True)


class AuditLog(TenantScoped, Base):
    """
    گزارش فعالیت (مرحله ۱۵): ورودها، مدیریت کاربران، تنظیمات سازمان، کاتالوگ و گزارش‌گیری.
    نام انجام‌دهنده و هدف هم ذخیره می‌شود تا با حذف بعدی، سابقه خوانا بماند.
    """
    __tablename__ = "audit_logs"
    # ورود ناموفق کارکنان پلتفرم سازمان ندارد
    __tenant_nullable__ = True

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_name = Column(String(150), nullable=True)
    action = Column(String(48), nullable=False, index=True)
    category = Column(String(16), nullable=False, index=True)
    target_type = Column(String(32), nullable=True)
    target_id = Column(Integer, nullable=True, index=True)
    target_label = Column(String(200), nullable=True)
    summary = Column(String(500), nullable=False)
    details = Column(JSON, nullable=True)
    ip = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)


# مدل‌های پایه انبارداری (سند انبار، رزرو، رویداد، طرف تجاری، واحد فرعی، تأمین‌کننده کالا)
from app.models_wms import (  # noqa: E402,F401
    DomainEvent, Partner, ProductSupplier, ProductUom, StockDocument, StockReservation,
)
# ثبت محافظ دفتر گردش کالا (before_flush) — باید بعد از تعریف همه مدل‌ها import شود
from app.services import stock_ledger  # noqa: E402,F401
# رویدادهای دامنه (after_flush)
from app.services import event_bus  # noqa: E402,F401
