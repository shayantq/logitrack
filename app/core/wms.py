"""
واژه‌نامه و قواعد پایه انبارداری (WMS) — منبع واحد نام‌ها، وضعیت‌ها و برچسب‌ها

مدل‌ها، اسکیماها، سرویس‌ها و API همه از همین ثابت‌ها استفاده می‌کنند تا یک مفهوم
همه‌جا یک نام داشته باشد (شرح کامل: docs/wms-glossary.md).

چهار محور وضعیت کالا کاملاً از هم جدا هستند و هرکدام فقط از مسیر خودش عوض می‌شود:

  ۱. وضعیت فیزیکی (کجاست؟)      ← انبار و محل (Location) در ردیف ریز موجودی (StockBalance) و گردش‌ها
  ۲. وضعیت کیفی (قابل استفاده است؟) ← STOCK_STATUSES؛ مستقل از محل — تغییر وضعیت کالا را جابه‌جا نمی‌کند
  ۳. وضعیت تخصیص (مال کیست؟)     ← رزرو (StockReservation)؛ موجودی قابل وعده = قابل تخصیص − رزرو
  ۴. وضعیت سند (قطعی است؟)       ← DOCUMENT_STATUSES؛ سند قطعی فقط با سند برگشت اصلاح می‌شود

موجودی در دو سطح نگه داشته می‌شود (هر دو فقط از دفتر گردش کالا تغییر می‌کنند):
  • ردیف موجودی (Inventory): کالا × انبار × وضعیت کیفی — رزرو سفارش و نقطه سفارش روی این سطح است.
  • ردیف ریز (StockBalance): همان ردیف × محل × مالک × بچ × سریال × تاریخ انقضا — جانمایی، برداشت و کاردکس.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# وضعیت کیفی موجودی (Quality / Stock Status)
# ---------------------------------------------------------------------------
AVAILABLE = "available"
PENDING = "pending"
STOCK_STATUSES = (
    AVAILABLE,       # تأییدشده: سالم و قابل فروش/مصرف — تنها وضعیت قابل تخصیص
    PENDING,         # در انتظار بازرسی: کالای تازه‌رسیده یا مرجوعی که هنوز بازرسی نشده
    "quarantine",    # قرنطینه: نگه‌داشته برای بررسی بیشتر
    "blocked",       # توقیف: به دستور مدیریت یا مشکل حقوقی/کیفی؛ فقط ادمین آزادش می‌کند
    "rejected",      # مردود: در بازرسی رد شد (برگشت به تأمین‌کننده یا امحا)
    "defective",     # معیوب: نقص فنی/کارکردی (قابل تعمیر یا مرجوع)
    "damaged",       # آسیب‌دیده: آسیب فیزیکی (شکستگی، خیسی، بسته‌بندی)
    "repair",        # در تعمیر: کالای معیوب/آسیب‌دیده که برای تعمیر کنار رفته؛ پس از تعمیر دوباره بازرسی می‌شود
    "in_transit",    # در راه: کالای سفارش انتقال که از مبدأ خارج شده و هنوز در مقصد دریافت نشده
)
STOCK_STATUS_LABELS = {
    "available": "تأییدشده (سالم)", "pending": "در انتظار بازرسی", "quarantine": "قرنطینه", "blocked": "توقیف",
    "rejected": "مردود", "defective": "معیوب", "damaged": "آسیب‌دیده", "repair": "در تعمیر", "in_transit": "در راه",
}
IN_TRANSIT = "in_transit"
# نگه‌داشته (غیرقابل‌استفاده تا تصمیم کیفی): همه جز تأییدشده، در انتظار بازرسی و در راه
HELD_STATUSES = tuple(s for s in STOCK_STATUSES if s not in (AVAILABLE, PENDING, IN_TRANSIT))

# چه کسی می‌تواند وضعیت کیفی را از کجا به کجا ببرد (بازرسی و تغییر وضعیت دستی هر دو از همین جدول)
_STAFF = ("org_admin", "warehouse_manager")
_ADMIN = ("org_admin",)
QUALITY_TRANSITIONS: dict[str, dict[str, tuple[str, ...]]] = {
    PENDING: {AVAILABLE: _STAFF, "quarantine": _STAFF, "blocked": _STAFF, "rejected": _STAFF, "defective": _STAFF,
              "damaged": _STAFF},
    "quarantine": {AVAILABLE: _STAFF, PENDING: _STAFF, "blocked": _STAFF, "rejected": _STAFF, "defective": _STAFF,
                   "damaged": _STAFF},
    AVAILABLE: {"quarantine": _STAFF, "blocked": _STAFF, "defective": _STAFF, "damaged": _STAFF},
    "blocked": {AVAILABLE: _ADMIN, "quarantine": _ADMIN, "rejected": _ADMIN, "defective": _ADMIN, "damaged": _ADMIN},
    "defective": {"rejected": _STAFF, "damaged": _STAFF, "quarantine": _STAFF, "repair": _STAFF, AVAILABLE: _ADMIN},
    "damaged": {"rejected": _STAFF, "defective": _STAFF, "quarantine": _STAFF, "repair": _STAFF, AVAILABLE: _ADMIN},
    # پس از تعمیر کالا مستقیم قابل فروش نمی‌شود: دوباره «در انتظار بازرسی»
    "repair": {PENDING: _STAFF, "rejected": _STAFF, "defective": _STAFF},
    "rejected": {"quarantine": _ADMIN, AVAILABLE: _ADMIN},
}


def quality_roles(from_status: str, to_status: str) -> tuple[str, ...]:
    """نقش‌های مجاز برای یک تغییر وضعیت کیفی (خالی = این تغییر اصلاً مجاز نیست)."""
    return QUALITY_TRANSITIONS.get(from_status, {}).get(to_status, ())

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
    # فصل‌های ۶ تا ۱۰ — این اسناد از مسیر عملیات خودشان اصلاح می‌شوند (رسید، بازرسی، وظیفه جانمایی)
    DocumentType("inbound_receipt", "GR", "رسید دریافت کالا", False),
    DocumentType("inspection", "QI", "بازرسی کیفی", False),
    DocumentType("putaway", "PA", "جانمایی", False),
    DocumentType("location_move", "MV", "جابه‌جایی بین محل‌ها", True),
    # فصل‌های ۱۱ تا ۱۵ — از مسیر عملیات خودشان (سفارش انتقال، پیکینگ، تأمین مجدد، تعیین تکلیف) اصلاح می‌شوند
    DocumentType("transfer_ship", "TS", "ارسال سفارش انتقال", False),
    DocumentType("transfer_receive", "TV", "دریافت سفارش انتقال", False),
    DocumentType("pick", "PK", "برداشت (پیکینگ)", False),
    DocumentType("replenishment", "RP", "تأمین مجدد محل برداشت", False),
    DocumentType("scrap", "SC", "امحا / ضایعات کیفی", False),
    DocumentType("supplier_return", "SR", "برگشت به تأمین‌کننده", False),
    DocumentType("disposition", "DP", "تعیین تکلیف کیفی", False),
)}

# نوع سند پیش‌فرض برای هر نوع گردش (وقتی فراخواننده سند را صریح نمی‌سازد)
MOVEMENT_DOCUMENT_TYPE = {
    "initial": "opening", "receipt": "receipt", "order_out": "order_issue", "order_return": "order_return",
    "adjustment": "adjustment", "damage": "write_off", "transfer_out": "transfer", "transfer_in": "transfer",
    "status_out": "status_change", "status_in": "status_change", "stocktake": "stocktake",
    "move_out": "location_move", "move_in": "location_move", "supplier_return": "supplier_return",
}
# گردش‌های داخلی که موجودی انبار را عوض نمی‌کنند (در کاردکس انبار خالص صفرند)
INTERNAL_MOVEMENT_TYPES = ("move_out", "move_in", "status_out", "status_in")

# ---------------------------------------------------------------------------
# ساختار فیزیکی انبار: محل‌ها (Locations)
# ---------------------------------------------------------------------------
# سطح‌ها از بزرگ به کوچک؛ زیرمجموعه هر محل باید سطح پایین‌تری داشته باشد (می‌توان سطحی را جا انداخت)
LOCATION_LEVELS = ("zone", "aisle", "rack", "shelf", "bin")
LOCATION_LEVEL_LABELS = {"zone": "منطقه", "aisle": "راهرو", "rack": "قفسه", "shelf": "طبقه", "bin": "خانه / جایگاه"}


@dataclass(frozen=True)
class LocationType:
    code: str
    label: str
    allocatable: bool = False     # موجودی تأییدشده این محل برای سفارش قابل تخصیص است؟
    receives: bool = False        # رسید کالا می‌تواند در این محل ثبت شود؟
    putaway_for: str = ""         # مقصد پیشنهادی جانمایی برای: "approved" (تأییدشده) یا "held" (غیرقابل‌استفاده)


LOCATION_TYPES = {t.code: t for t in (
    LocationType("receiving", "تخلیه و دریافت", receives=True),
    LocationType("storage", "نگهداری", allocatable=True, putaway_for="approved"),
    LocationType("picking", "برداشت", allocatable=True, putaway_for="approved"),
    LocationType("quarantine", "قرنطینه", receives=True, putaway_for="held"),
    LocationType("staging", "آماده‌سازی", receives=True),
    LocationType("shipping", "بارگیری و ارسال"),
)}
ALLOCATABLE_LOCATION_TYPES = tuple(t.code for t in LOCATION_TYPES.values() if t.allocatable)

# ---------------------------------------------------------------------------
# رسید و دریافت کالا (Inbound / Receiving)
# ---------------------------------------------------------------------------
RECEIPT_TYPES = ("purchase", "transfer", "return", "unexpected")
RECEIPT_TYPE_LABELS = {"purchase": "خرید از تأمین‌کننده", "transfer": "انتقال از انبار دیگر",
                       "return": "مرجوعی مشتری", "unexpected": "ورود پیش‌بینی‌نشده"}
RECEIPT_STATUSES = ("open", "receiving", "closed", "canceled")
RECEIPT_STATUS_LABELS = {"open": "در انتظار ورود", "receiving": "در حال دریافت", "closed": "بسته‌شده", "canceled": "لغوشده"}
DISCREPANCY_TYPES = ("shortage", "over", "unexpected_item")
DISCREPANCY_LABELS = {"shortage": "کسری", "over": "اضافه تحویل", "unexpected_item": "کالای خارج از برنامه"}
RECEIPT_CONDITIONS = ("good", "damaged")

# ---------------------------------------------------------------------------
# جانمایی (Putaway)
# ---------------------------------------------------------------------------
PUTAWAY_STATUSES = ("open", "partial", "done", "canceled")
PUTAWAY_STATUS_LABELS = {"open": "باز", "partial": "نیمه‌انجام", "done": "انجام‌شده", "canceled": "لغوشده"}
PUTAWAY_PROBLEMS = ("destination_full", "destination_blocked", "item_damaged", "item_missing")
PUTAWAY_PROBLEM_LABELS = {"destination_full": "محل مقصد پر است", "destination_blocked": "محل مقصد مسدود/خراب است",
                          "item_damaged": "کالا آسیب دیده است", "item_missing": "کالا در محل مبدأ نیست"}
# وظیفه انبار: جانمایی کالای رسیده، یا تأمین مجدد محل برداشت از قفسه نگهداری (همان اجرای اسکنی)
TASK_TYPES = ("putaway", "replenishment")
TASK_TYPE_LABELS = {"putaway": "جانمایی", "replenishment": "تأمین مجدد"}

# ---------------------------------------------------------------------------
# فصل ۱۱ — سفارش معوق (Backorder)
# ---------------------------------------------------------------------------
BACKORDER_STATUSES = ("open", "allocated", "fulfilled", "canceled")
BACKORDER_STATUS_LABELS = {"open": "در انتظار موجودی", "allocated": "تخصیص‌یافته", "fulfilled": "ارسال‌شده",
                           "canceled": "لغوشده"}

# ---------------------------------------------------------------------------
# فصل ۱۲ — سفارش انتقال
# ---------------------------------------------------------------------------
TRANSFER_STATUSES = ("open", "in_transit", "received", "closed", "canceled")
TRANSFER_STATUS_LABELS = {"open": "آماده ارسال", "in_transit": "در راه", "received": "دریافت کامل",
                          "closed": "بسته‌شده", "canceled": "لغوشده"}
TRANSFER_RESOLUTIONS = ("write_off", "return")      # تکلیف کسری در راه هنگام بستن

# ---------------------------------------------------------------------------
# فصل ۱۳ — طبقه‌بندی ABC و دوره شمارش
# ---------------------------------------------------------------------------
ABC_CLASSES = ("A", "B", "C")
ABC_THRESHOLDS = (0.80, 0.95)                        # سهم تجمعی ارزش مصرف: تا ۸۰٪ = A، تا ۹۵٪ = B
ABC_COUNT_DAYS = {"A": 30, "B": 90, "C": 180}        # فاصله شمارش دوره‌ای هر کلاس

# ---------------------------------------------------------------------------
# فصل ۱۴ — پیکینگ، بسته‌بندی و ارسال
# ---------------------------------------------------------------------------
PICK_STRATEGIES = ("single", "batch", "wave", "zone")
PICK_STRATEGY_LABELS = {"single": "تک‌سفارشی", "batch": "دسته‌ای", "wave": "موجی (بازه تحویل)", "zone": "منطقه‌ای"}
PICK_LIST_STATUSES = ("open", "in_progress", "picked", "canceled")
PICK_LIST_STATUS_LABELS = {"open": "باز", "in_progress": "در حال برداشت", "picked": "برداشت‌شده", "canceled": "لغوشده"}
PICK_LINE_STATUSES = ("open", "picked", "short", "canceled")
# وضعیت آماده‌سازی سفارش در انبار (مستقل از وضعیت حمل و وضعیت موجودی)
FULFILLMENT_STATES = ("open", "picking", "picked", "packed", "shipped")
FULFILLMENT_LABELS = {"open": "آماده‌نشده", "picking": "در حال برداشت", "picked": "برداشت‌شده", "packed": "بسته‌بندی‌شده",
                      "shipped": "ارسال‌شده"}
SHIPMENT_STATUSES = ("open", "dispatched", "canceled")
SHIPMENT_STATUS_LABELS = {"open": "در حال بارگیری", "dispatched": "تحویل راننده شد", "canceled": "لغوشده"}

# ---------------------------------------------------------------------------
# فصل ۱۵ — تعیین تکلیف کالای مرجوعی/معیوب
# ---------------------------------------------------------------------------
DISPOSITION_ACTIONS = ("scrap", "repair", "return_to_supplier", "reinspect")
DISPOSITION_LABELS = {"scrap": "امحا (ضایعات)", "repair": "ارسال به تعمیر", "return_to_supplier": "برگشت به تأمین‌کننده",
                      "reinspect": "بازرسی دوباره"}

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
PARTNER_ROLES = ("supplier", "customer", "carrier", "owner")
PARTNER_ROLE_LABELS = {"supplier": "تأمین‌کننده", "customer": "مشتری", "carrier": "شرکت حمل",
                       "owner": "مالک کالا (امانی)"}
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
    "location.created", "location.updated",
    "inbound.receipt.created", "inbound.receipt.received", "inbound.receipt.closed", "inbound.receipt.canceled",
    "quality.inspected",
    "putaway.task.created", "putaway.task.completed", "putaway.task.failed", "putaway.task.canceled",
    "backorder.created", "backorder.allocated", "backorder.fulfilled", "backorder.canceled",
    "transfer.created", "transfer.shipped", "transfer.received", "transfer.closed", "transfer.canceled",
    "pick.list.created", "pick.line.picked", "pick.line.short", "pick.list.completed",
    "order.packed", "shipment.created", "shipment.dispatched",
    "replenishment.triggered", "abc.classified", "disposition.recorded",
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
    ("On hand", "موجودی فیزیکی", "مقداری که الان در انبار است (همه وضعیت‌ها، شامل رزروشده)."),
    ("Allocatable", "قابل تخصیص", "موجودی تأییدشده در محل نگهداری/برداشت، منقضی‌نشده و متعلق به خود سازمان."),
    ("Free / ATP", "موجودی قابل وعده", "قابل تخصیص منهای رزرو — آنچه سفارش جدید می‌تواند بردارد."),
    ("In transit", "در راه", "کالایی که در انبار «در راه» است یا با رسید انتقال به انبار مقصد در راه است."),
    ("Stock status", "وضعیت کیفی", "تأییدشده، در انتظار بازرسی، قرنطینه، توقیف، مردود، معیوب یا آسیب‌دیده؛ مستقل از محل."),
    ("Location", "محل", "جایگاه فیزیکی در انبار: منطقه ← راهرو ← قفسه ← طبقه ← خانه؛ کالا فقط در محل انتهایی می‌نشیند."),
    ("Mixing rule", "قاعده اختلاط", "اجازه یا منع نگهداری چند کالا، چند بچ یا کالای چند مالک در یک محل."),
    ("Owner", "مالک کالا", "طرفی که مالک کالای امانی است (مثلاً مشتری انبار عمومی)؛ خالی = خود سازمان."),
    ("Inbound receipt", "رسید دریافت", "سند ورود برنامه‌ریزی‌شده یا پیش‌بینی‌نشده با مقادیر مورد انتظار، دریافتی، پذیرفته و مردود."),
    ("Discrepancy", "مغایرت", "کسری، اضافه تحویل یا کالای خارج از برنامه در یک رسید."),
    ("Inspection", "بازرسی کیفی", "تعیین وضعیت کالای در انتظار بازرسی یا قرنطینه، با ثبت نتیجه و بازرس."),
    ("FEFO", "اول‌منقضی، اول‌خروج", "برداشت خودکار از بچی که زودتر منقضی می‌شود."),
    ("Kardex / Stock card", "کاردکس", "کارت گردش یک کالا با مانده اول دوره، ورود، خروج و مانده پس از هر سند."),
    ("Backorder", "سفارش معوق", "مقدار سفارش که موجودی نداشت؛ ثبت می‌ماند و به ترتیب اولویت به موجودی جدید تخصیص می‌یابد."),
    ("Transfer order", "سفارش انتقال", "انتقال دومرحله‌ای: ارسال از مبدأ (کالا «در راه») و دریافت در مقصد با ثبت کسری و آسیب."),
    ("Replenishment", "تأمین مجدد", "پر کردن محل برداشت از قفسه نگهداری وقتی موجودی آن به حداقل رسید."),
    ("ABC", "طبقه‌بندی ABC", "دسته‌بندی کالا با سهم ارزش مصرف؛ کلاس A بیشتر کنترل و زودتر شمارش می‌شود."),
    ("Pick list / Wave", "فهرست برداشت / موج", "برداشت کالای یک یا چند سفارش با مسیر محل‌ها؛ موج = سفارش‌های یک بازه تحویل."),
    ("Packing slip", "برگه بسته‌بندی", "فهرست محتوای هر بسته سفارش با ابعاد و وزن."),
    ("Shipment", "محموله", "بسته‌های چند سفارش روی یک خودرو با کنترل ظرفیت وزنی و حجمی و تحویل به راننده."),
    ("Disposition", "تعیین تکلیف", "تصمیم درباره کالای مردود/معیوب: امحا، تعمیر، برگشت به تأمین‌کننده یا بازرسی دوباره."),
    ("Inventory document", "سند انبار", "رسید، حواله، اصلاحیه، انتقال و…؛ تنها راه تغییر موجودی."),
    ("Ledger", "دفتر گردش کالا", "فهرست غیرقابل‌تغییر گردش‌ها؛ موجودی هر ردیف = مجموع گردش‌هایش."),
    ("Reversal", "سند برگشت", "سندی که اثر یک سند قطعی را خنثی می‌کند؛ هیچ سندی حذف یا بازنویسی نمی‌شود."),
    ("Idempotency key", "کلید یکتایی درخواست", "تکرار یک درخواست با همین کلید، سند دوم نمی‌سازد."),
    ("Domain event", "رویداد", "ثبت غیرقابل‌تغییر «چه اتفاقی افتاد» در همان تراکنش عملیات."),
    ("Tenant", "سازمان", "هر مشتری پسینه؛ داده‌های سازمان‌ها در همه لایه‌ها از هم جداست."),
    ("Cycle count", "شمارش دوره‌ای", "شمارش بخشی از کالاها به نوبت کلاس ABC به‌جای توقف کل انبار."),
    ("Blind count", "شمارش کور", "شمارنده عدد سیستم را نمی‌بیند تا عدد واقعی را بنویسد، نه عدد مورد انتظار را."),
    ("Count lock", "قفل محل", "تا تأیید انبارگردانی، محل‌های در حال شمارش ورود و خروج نمی‌پذیرند."),
    ("Valuation", "ارزش‌گذاری", "روش مالی محاسبه بهای موجودی (FIFO، میانگین موزون، استاندارد)؛ مستقل از قاعده برداشت فیزیکی."),
    ("Dead stock", "کالای راکد", "موجودی‌ای که مدت طولانی فروش یا خروج نداشته است."),
    ("Dock-to-stock", "رسید تا قفسه", "فاصله زمانی دریافت کالا در محل تخلیه تا پایان جانمایی در قفسه."),
    ("RBAC", "مجوزهای نقش", "کنترل دسترسی با نقش و مجوزهای ریز هر نقش، بررسی‌شده سمت سرور."),
    ("Audit log", "گزارش فعالیت", "سابقه تغییرناپذیر کی، کِی، چه و چرای عملیات حساس."),
    ("Cutover", "راه‌اندازی/انتقال", "گذر از سیستم قبلی به پسینه: ورود داده، موجودی اول دوره، آموزش و امضای شروع."),
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
        "quality_transitions": [{"from": f, "to": t, "roles": list(roles)}
                                for f, targets in QUALITY_TRANSITIONS.items() for t, roles in targets.items()],
        "location_levels": [{"code": c, "label": LOCATION_LEVEL_LABELS[c]} for c in LOCATION_LEVELS],
        "location_types": [{"code": t.code, "label": t.label, "allocatable": t.allocatable, "receives": t.receives,
                            "putaway_for": t.putaway_for or None} for t in LOCATION_TYPES.values()],
        "receipt_types": [{"code": c, "label": RECEIPT_TYPE_LABELS[c]} for c in RECEIPT_TYPES],
        "receipt_statuses": [{"code": c, "label": RECEIPT_STATUS_LABELS[c]} for c in RECEIPT_STATUSES],
        "discrepancy_types": [{"code": c, "label": DISCREPANCY_LABELS[c]} for c in DISCREPANCY_TYPES],
        "putaway_statuses": [{"code": c, "label": PUTAWAY_STATUS_LABELS[c]} for c in PUTAWAY_STATUSES],
        "putaway_problems": [{"code": c, "label": PUTAWAY_PROBLEM_LABELS[c]} for c in PUTAWAY_PROBLEMS],
        "pick_strategies": [{"code": c, "label": PICK_STRATEGY_LABELS[c]} for c in PICK_STRATEGIES],
        "fulfillment_states": [{"code": c, "label": FULFILLMENT_LABELS[c]} for c in FULFILLMENT_STATES],
        "transfer_statuses": [{"code": c, "label": TRANSFER_STATUS_LABELS[c]} for c in TRANSFER_STATUSES],
        "disposition_actions": [{"code": c, "label": DISPOSITION_LABELS[c]} for c in DISPOSITION_ACTIONS],
        "abc_count_days": ABC_COUNT_DAYS,
        "partner_roles": [{"code": c, "label": PARTNER_ROLE_LABELS[c]} for c in PARTNER_ROLES],
        "carrier_services": [{"code": c, "label": CARRIER_SERVICE_LABELS[c]} for c in CARRIER_SERVICES],
        "event_types": list(EVENT_TYPES),
        "glossary": [{"term": t, "fa": fa, "definition": d} for t, fa, d in GLOSSARY],
    }


def sql_in(values) -> str:
    """فهرست مقادیر برای CHECK constraint."""
    return ", ".join(f"'{v}'" for v in values)
