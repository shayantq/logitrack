"""
واژه‌نامه و قواعد پایه انبارداری (WMS) — منبع واحد نام‌ها، وضعیت‌ها و برچسب‌ها

مدل‌ها، اسکیماها، سرویس‌ها و API همه از همین ثابت‌ها استفاده می‌کنند تا یک مفهوم
همه‌جا یک نام داشته باشد (شرح کامل: docs/wms-glossary.md).

چهار محور وضعیت کالا کاملاً از هم جدا هستند و هرکدام فقط از مسیر خودش عوض می‌شود:

  ۱. وضعیت فیزیکی (کجاست؟)      ← ردیف موجودی (کالا × انبار) و گردش‌های دفتر کالا
  ۲. وضعیت کیفی (قابل استفاده است؟) ← STOCK_STATUSES؛ هر وضعیت یک ردیف موجودی جدا
  ۳. وضعیت تخصیص (مال کیست؟)     ← رزرو (StockReservation)؛ موجودی آزاد = موجود − رزرو
  ۴. وضعیت سند (قطعی است؟)       ← DOCUMENT_STATUSES؛ سند قطعی فقط با سند برگشت اصلاح می‌شود
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# وضعیت کیفی موجودی (Quality / Stock Status)
# ---------------------------------------------------------------------------
AVAILABLE = "available"
STOCK_STATUSES = (
    AVAILABLE,       # سالم و آزاد برای فروش/مصرف
    "quarantine",    # قرنطینه: منتظر بازرسی کیفی (مثلاً کالای تازه‌رسیده یا مرجوعی)
    "blocked",       # توقیف: به دستور مدیریت یا مشکل حقوقی/کیفی، قابل استفاده نیست
    "damaged",       # معیوب: منتظر تصمیم (تعمیر، برگشت به تأمین‌کننده یا ضایعات)
)
STOCK_STATUS_LABELS = {
    "available": "سالم و آزاد", "quarantine": "قرنطینه", "blocked": "توقیف", "damaged": "معیوب",
}

# ---------------------------------------------------------------------------
# وضعیت تخصیص (Allocation / Reservation)
# ---------------------------------------------------------------------------
RESERVATION_STATUSES = (
    "active",      # موجودی برای یک سند (مثلاً سفارش) کنار گذاشته شده
    "consumed",    # کالا خارج شد (حواله صادر شد) — رزرو مصرف شد
    "released",    # رزرو آزاد شد (لغو/انقضای سفارش)
)
RESERVATION_STATUS_LABELS = {"active": "رزرو فعال", "consumed": "مصرف‌شده", "released": "آزادشده"}

# وضعیت کالای یک سفارش در انبار (مستقل از وضعیت حمل سفارش)
ORDER_STOCK_STATES = (
    "reserved",    # رزرو شده، هنوز از انبار خارج نشده
    "issued",      # حواله خروج صادر و از موجودی کم شده
    "released",    # رزرو بدون خروج آزاد شد
    "returned",    # پس از خروج به انبار برگشت
)

# ---------------------------------------------------------------------------
# اسناد انبار (Inventory Documents)
# ---------------------------------------------------------------------------
DOCUMENT_STATUSES = (
    "draft",       # پیش‌نویس: هنوز اثری روی موجودی ندارد (برای فصل‌های بعد: رسید چندمرحله‌ای)
    "posted",      # قطعی: گردش‌ها ثبت شده و غیرقابل ویرایش است
    "reversed",    # برگشت‌خورده: یک سند برگشت اثر آن را خنثی کرده (خود سند و گردش‌هایش می‌مانند)
    "canceled",    # پیش‌نویس لغوشده
)
DOCUMENT_STATUS_LABELS = {"draft": "پیش‌نویس", "posted": "قطعی", "reversed": "برگشت‌خورده", "canceled": "لغوشده"}


@dataclass(frozen=True)
class DocumentType:
    code: str
    prefix: str
    label: str
    reversible: bool      # کاربر می‌تواند سند برگشت بزند؟ (اسناد سفارش و انبارگردانی از مسیر خودشان اصلاح می‌شوند)


DOCUMENT_TYPES = {d.code: d for d in (
    DocumentType("opening", "OB", "موجودی اول دوره", True),
    DocumentType("receipt", "RC", "رسید ورود کالا", True),
    DocumentType("order_issue", "GI", "حواله خروج سفارش", False),
    DocumentType("order_return", "RT", "برگشت از سفارش", False),
    DocumentType("adjustment", "AJ", "اصلاحیه موجودی", True),
    DocumentType("write_off", "WO", "ضایعات و کسری", True),
    DocumentType("transfer", "TR", "انتقال بین انبارها", True),
    DocumentType("status_change", "QS", "تغییر وضعیت کیفی", True),
    DocumentType("stocktake", "IC", "اصلاحیه انبارگردانی", False),
    DocumentType("reversal", "RV", "سند برگشت", False),
)}

# نوع سند پیش‌فرض برای هر نوع گردش (وقتی فراخواننده سند را صریح نمی‌سازد)
MOVEMENT_DOCUMENT_TYPE = {
    "initial": "opening", "receipt": "receipt", "order_out": "order_issue", "order_return": "order_return",
    "adjustment": "adjustment", "damage": "write_off", "transfer_out": "transfer", "transfer_in": "transfer",
    "status_out": "status_change", "status_in": "status_change", "stocktake": "stocktake",
}

# ---------------------------------------------------------------------------
# انواع انبار (Warehouse Types)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WarehouseType:
    code: str
    label: str
    holds_stock: bool = True          # «سایت» فقط گروه‌بندی است و کالا نگه نمی‌دارد
    ships_orders: bool = False        # سفارش مشتری از این انبار ارسال می‌شود؟
    direct_receipt: bool = True       # رسید مستقیم از تأمین‌کننده؟ (انبار در راه فقط با انتقال پر می‌شود)
    receipt_status: str = AVAILABLE   # وضعیت کیفی پیش‌فرض کالای رسیده


WAREHOUSE_TYPES = {t.code: t for t in (
    WarehouseType("general", "انبار عمومی", ships_orders=True),
    WarehouseType("finished_goods", "انبار محصول نهایی", ships_orders=True),
    WarehouseType("distribution", "مرکز توزیع", ships_orders=True),
    WarehouseType("raw_materials", "انبار مواد اولیه"),
    WarehouseType("quarantine", "انبار قرنطینه", receipt_status="quarantine"),
    WarehouseType("returns", "انبار مرجوعی", receipt_status="quarantine"),
    WarehouseType("transit", "انبار در راه", direct_receipt=False),
    WarehouseType("site", "سایت / مجتمع انبار", holds_stock=False, direct_receipt=False),
)}
MAX_WAREHOUSE_DEPTH = 4

# ---------------------------------------------------------------------------
# طرف‌های تجاری (Partners)
# ---------------------------------------------------------------------------
PARTNER_ROLES = ("supplier", "customer", "carrier")
PARTNER_ROLE_LABELS = {"supplier": "تأمین‌کننده", "customer": "مشتری", "carrier": "شرکت حمل"}
PARTNER_KINDS = ("legal", "individual")
CARRIER_SERVICES = ("road", "rail", "air", "sea", "courier", "post")
CARRIER_SERVICE_LABELS = {"road": "جاده‌ای", "rail": "ریلی", "air": "هوایی", "sea": "دریایی",
                          "courier": "پیک", "post": "پست"}

# ---------------------------------------------------------------------------
# رویدادهای دامنه (Domain Events) — نام‌ها به شکل «موجودیت.فعل»
# ---------------------------------------------------------------------------
EVENT_TYPES = (
    "stock.document.posted", "stock.document.reversed",
    "stock.reserved", "stock.reservation.released", "stock.reservation.consumed",
    "product.created", "product.updated",
    "warehouse.created", "warehouse.updated",
    "partner.created", "partner.updated",
)

# ---------------------------------------------------------------------------
# واژه‌نامه (برای API و رابط کاربری)
# ---------------------------------------------------------------------------
GLOSSARY = (
    ("SKU", "کد کالا", "شناسه یکتا و تغییرناپذیر هر کالا در سازمان."),
    ("Base UoM", "واحد پایه", "کوچک‌ترین واحد شمارش کالا؛ همه مقادیر موجودی به این واحد و عدد صحیح‌اند."),
    ("UoM Conversion", "واحد فرعی", "واحدی مثل کارتن که برابر عدد صحیحی از واحد پایه است."),
    ("Lot / Batch", "بچ / سری ساخت", "گروهی از یک کالا با تاریخ تولید/انقضای یکسان."),
    ("Serial", "شماره سریال", "شناسه یکتای تک‌تک واحدهای کالا."),
    ("LPN", "شناسه بسته/پالت", "شناسه یک واحد حمل (پالت، کارتن) که چند کالا را در خود دارد."),
    ("Putaway", "جانمایی", "قرار دادن کالای رسیده در محل نگهداری."),
    ("Picking", "برداشت", "جمع‌آوری کالای سفارش از محل نگهداری."),
    ("Allocation", "تخصیص", "اختصاص موجودی مشخص به یک سفارش."),
    ("Reservation", "رزرو", "بخشی از موجودی که برای یک سند کنار گذاشته شده و برای دیگران آزاد نیست."),
    ("On hand", "موجودی فیزیکی", "مقداری که الان در انبار است (شامل رزروشده)."),
    ("Free / ATP", "موجودی آزاد", "موجودی سالم منهای رزرو — قابل وعده به سفارش جدید."),
    ("Stock status", "وضعیت کیفی", "سالم، قرنطینه، توقیف یا معیوب؛ هر وضعیت ردیف موجودی جدا دارد."),
    ("Inventory document", "سند انبار", "رسید، حواله، اصلاحیه، انتقال و…؛ تنها راه تغییر موجودی."),
    ("Ledger", "دفتر گردش کالا", "فهرست غیرقابل‌تغییر گردش‌ها؛ موجودی هر ردیف = مجموع گردش‌هایش."),
    ("Reversal", "سند برگشت", "سندی که اثر یک سند قطعی را خنثی می‌کند؛ هیچ سندی حذف یا بازنویسی نمی‌شود."),
    ("Idempotency key", "کلید یکتایی درخواست", "تکرار یک درخواست با همین کلید، سند دوم نمی‌سازد."),
    ("Domain event", "رویداد", "ثبت غیرقابل‌تغییر «چه اتفاقی افتاد» در همان تراکنش عملیات."),
    ("Tenant", "سازمان", "هر مشتری پسینه؛ داده‌های سازمان‌ها در همه لایه‌ها از هم جداست."),
)


def vocabulary() -> dict:
    """همه برچسب‌ها برای رابط کاربری و یکپارچه‌سازی‌ها (GET /wms/vocabulary)."""
    return {
        "stock_statuses": [{"code": c, "label": STOCK_STATUS_LABELS[c]} for c in STOCK_STATUSES],
        "reservation_statuses": [{"code": c, "label": RESERVATION_STATUS_LABELS[c]} for c in RESERVATION_STATUSES],
        "document_statuses": [{"code": c, "label": DOCUMENT_STATUS_LABELS[c]} for c in DOCUMENT_STATUSES],
        "document_types": [{"code": d.code, "prefix": d.prefix, "label": d.label, "reversible": d.reversible}
                           for d in DOCUMENT_TYPES.values()],
        "warehouse_types": [{"code": t.code, "label": t.label, "holds_stock": t.holds_stock, "ships_orders": t.ships_orders,
                             "direct_receipt": t.direct_receipt, "receipt_status": t.receipt_status}
                            for t in WAREHOUSE_TYPES.values()],
        "partner_roles": [{"code": c, "label": PARTNER_ROLE_LABELS[c]} for c in PARTNER_ROLES],
        "carrier_services": [{"code": c, "label": CARRIER_SERVICE_LABELS[c]} for c in CARRIER_SERVICES],
        "event_types": list(EVENT_TYPES),
        "glossary": [{"term": t, "fa": fa, "definition": d} for t, fa, d in GLOSSARY],
    }


def sql_in(values) -> str:
    """فهرست مقادیر برای CHECK constraint."""
    return ", ".join(f"'{v}'" for v in values)
