"""پیام فارسی خطاهای اعتبارسنجی ورودی (۴۲۲) برای کاربر غیرفنی.

خطاهای Pydantic متن انگلیسی دارند (مثلاً «String should match pattern ...»). اینجا هر خطا به یک جمله فارسی با نام
فیلد تبدیل می‌شود. هر مورد همان loc و type را دارد، msg فارسی می‌شود و field_label اضافه می‌شود؛ مقدار ورودی کاربر برنمی‌گردد.
حدها (حداقل، حداکثر، طول) همیشه از ctx همان خطا خوانده می‌شوند؛ اینجا هیچ قاعده‌ای تعریف یا عوض نمی‌شود.
"""
import re
from decimal import Decimal

from app.core.iran import fa_digits

# نام فیلدها تا جای ممکن همان برچسب فرم‌هاست (بدون ستاره و واحد). فیلد بی‌برچسب «این فیلد» نام می‌گیرد.
FIELD_LABELS = {
    "abc_classes": "کلاس‌های ABC",
    "action": "تصمیم",
    "address": "نشانی",
    "adjustment_approval_units": "سقف اصلاح موجودی بدون تأیید دوم",
    "admin_email": "ایمیل ادمین",
    "admin_password": "رمز عبور ادمین",
    "admin_username": "نام کاربری ادمین",
    "area": "منطقه",
    "assignee_id": "مسئول",
    "barcode": "بارکد",
    "base_fare": "کرایه پایه",
    "base_price": "قیمت پایه",
    "birth_date": "تاریخ تولد",
    "block_reason": "دلیل مسدود کردن",
    "body": "متن",
    "brand": "برند",
    "brand_color": "رنگ سازمان",
    "business_type": "حوزه فعالیت",
    "capacity_kg": "ظرفیت",
    "carrier_service": "نوع خدمت حمل",
    "category": "گروه",
    "city": "شهر",
    "code": "کد",
    "comment": "توضیح",
    "commission_percent": "پورسانت",
    "condition": "وضعیت ظاهری",
    "confirm_slug": "شناسه تأیید",
    "contact_email": "ایمیل",
    "contact_mobile": "شماره همراه",
    "contact_name": "نام مسئول",
    "copies": "تعداد نسخه",
    "cost_price": "بهای تمام‌شده",
    "count_approval_value": "سقف تأیید انبارگردانی",
    "count_type": "نوع شمارش",
    "counted_qty": "تعداد شمارش‌شده",
    "cover_days": "روزهای پوشش",
    "damaged_quantity": "تعداد آسیب‌دیده",
    "date_from": "از تاریخ",
    "date_to": "تا تاریخ",
    "days": "روز",
    "dead_days": "راکد پس از (روز)",
    "delivered_quantity": "تعداد تحویل‌شده",
    "delivery_fee": "کرایه حمل",
    "delivery_method": "روش تحویل",
    "delivery_window_end": "پایان بازه تحویل",
    "delivery_window_start": "شروع بازه تحویل",
    "demand_growth_monthly": "رشد ماهانه فروش",
    "description": "توضیحات",
    "destination_address": "نشانی مقصد",
    "destination_city": "شهر مقصد",
    "destination_postal_code": "کد پستی مقصد",
    "destination_province": "استان مقصد",
    "destination_scan": "اسکن محل مقصد",
    "driver_id": "راننده",
    "economic_code": "کد اقتصادی",
    "effective_from": "از تاریخ",
    "email": "ایمیل",
    "employee_count": "تعداد کارکنان",
    "end_time": "ساعت پایان",
    "ends_at": "پایان",
    "entry_mode": "روش ورود",
    "evidence_ref": "پیوند مدرک",
    "exception_note": "توضیح",
    "expected_date": "تاریخ ورود مورد انتظار",
    "expected_quantity": "تعداد مورد انتظار",
    "expires_in_days": "اعتبار (روز)",
    "expiry_date": "تاریخ انقضا",
    "expiry_warning_days": "هشدار انقضا (روز)",
    "external_ref": "شماره فاکتور / بارنامه",
    "factor": "ضریب",
    "failure_reason": "دلیل ناموفق بودن",
    "fare_per_kg": "کرایه به ازای هر کیلو",
    "file": "فایل",
    "first_name": "نام",
    "fleet_size": "تعداد خودرو / راننده",
    "from_location_id": "محل مبدأ",
    "from_trip": "از سفر چندم روز",
    "from_warehouse_id": "انبار مبدأ",
    "full_name": "نام و نام خانوادگی",
    "height_cm": "ارتفاع",
    "history_days": "دوره سابقه (روز)",
    "holding_rate": "نرخ نگه‌داری",
    "hs_code": "کد تعرفه گمرکی",
    "iban": "شماره شبا",
    "identifier": "نام کاربری یا شماره همراه",
    "ids": "موارد انتخاب‌شده",
    "initial_quantity": "موجودی اولیه",
    "inspection_expiry": "اعتبار معاینه فنی",
    "issue": "کمبود یا آسیب",
    "items": "موارد",
    "kind": "نوع",
    "label": "عنوان",
    "label_type": "نوع برچسب",
    "last_name": "نام خانوادگی",
    "last_price": "آخرین قیمت",
    "lead_time_days": "زمان تأمین (روز)",
    "lead_time_std_days": "نوسان زمان تأمین (روز)",
    "leave_type": "نوع مرخصی",
    "legal_name": "نام ثبتی",
    "length_cm": "طول",
    "level": "سطح",
    "levels": "سطح‌ها",
    "license_plate": "پلاک",
    "limit": "تعداد",
    "line_id": "سطر",
    "line_ids": "سطرها",
    "lines": "سطرها",
    "location": "محل",
    "location_id": "محل",
    "location_ids": "محل‌ها",
    "location_type": "نوع محل",
    "lot_number": "شماره بچ",
    "lot_scan": "اسکن بچ",
    "manual_note": "توضیح دلیل",
    "manual_reason": "دلیل ورود دستی",
    "max_daily_orders": "حداکثر سفارش روزانه",
    "max_pallets": "حداکثر پالت",
    "max_quantity": "حداکثر",
    "max_stock": "حداکثر موجودی",
    "max_uses": "حداکثر تعداد ثبت‌نام",
    "max_volume_m3": "حداکثر حجم (مترمکعب)",
    "max_weight_kg": "حداکثر وزن (کیلوگرم)",
    "merged_into_id": "ادغام در",
    "method": "روش",
    "method_note": "توضیح روش تحویل",
    "min_days": "حداقل روز",
    "min_deliveries": "حداقل تحویل",
    "min_history_days": "حداقل سابقه (روز)",
    "min_order_qty": "حداقل سفارش",
    "min_quantity": "حداقل",
    "min_rating": "حداقل امتیاز",
    "min_stock": "حداقل موجودی",
    "minutes": "دقیقه",
    "mission_deadline_minutes": "مهلت پاسخ مأموریت (دقیقه)",
    "mobile": "شماره همراه",
    "monthly_order_volume": "حجم سفارش ماهانه",
    "months": "افق برنامه",
    "movement_type": "نوع گردش",
    "multiplier_percent": "ضریب",
    "name": "نام",
    "national_code": "کد ملی",
    "national_id": "شناسه ملی",
    "net_weight_kg": "وزن خالص (کیلوگرم)",
    "new_password": "رمز عبور جدید",
    "note": "توضیح",
    "notes": "توضیحات",
    "old_password": "رمز عبور فعلی",
    "order_id": "سفارش",
    "order_ids": "سفارش‌ها",
    "order_status": "وضعیت سفارش",
    "ordering_cost": "هزینه هر سفارش",
    "origin": "مبدأ",
    "origin_country": "کشور مبدأ",
    "otp": "کد ورود دومرحله‌ای",
    "outcome": "نتیجه",
    "over_reason": "دلیل اضافه تحویل",
    "over_tolerance_pct": "تلورانس اضافه تحویل",
    "owner_id": "مالک کالا",
    "packages": "بسته‌ها",
    "parent_id": "محل مادر",
    "partner_id": "طرف حساب",
    "password": "رمز عبور",
    "payment_terms_days": "مهلت پرداخت (روز)",
    "phone": "تلفن ثابت",
    "plan_id": "طرح",
    "postal_code": "کد پستی",
    "price": "قیمت",
    "price_growth_monthly": "تورم ماهانه بها",
    "priority": "اولویت",
    "problem": "شرح مشکل",
    "product_id": "کالا",
    "product_ids": "کالاها",
    "product_scan": "اسکن کالا",
    "province": "استان",
    "q": "عبارت جستجو",
    "quantity": "تعداد",
    "reason": "دلیل",
    "reasons": "دلیل‌ها",
    "receipt_id": "رسید",
    "receipt_type": "نوع رسید",
    "received_quantity": "تعداد دریافتی",
    "receiving_location_id": "محل تخلیه",
    "recipient_mobile": "شماره همراه گیرنده",
    "recipient_name": "نام گیرنده",
    "recipient_role": "نسبت با گیرنده",
    "reference_number": "شماره مرجع",
    "referral_detail": "توضیح آشنایی",
    "referral_source": "نحوه آشنایی",
    "registration_number": "شماره ثبت",
    "reorder_point": "نقطه سفارش",
    "requested_features": "امکانات درخواستی",
    "resolution": "تکلیف کسری",
    "resolution_code": "نتیجه رسیدگی",
    "results": "نتیجه‌ها",
    "role": "نقش",
    "route_sequence": "ترتیب مسیر",
    "scope": "دامنه",
    "score": "امتیاز",
    "serial_numbers": "شماره سریال",
    "service_level": "سطح خدمت",
    "severity": "شدت",
    "shelf_life_days": "ماندگاری (روز)",
    "shifts": "روزهای کاری",
    "short_name": "نام کوتاه",
    "shortage_reason": "دلیل کسری",
    "size": "اندازه",
    "sku": "کد کالا (SKU)",
    "slow_days": "کم‌گردش پس از (روز)",
    "slug": "شناسه انگلیسی (slug)",
    "source_location_id": "محل مبدأ",
    "source_scan": "اسکن محل مبدأ",
    "source_warehouse_id": "انبار مبدأ",
    "staging_location_id": "محل آماده‌سازی",
    "start_time": "ساعت شروع",
    "starts_at": "شروع",
    "state": "وضعیت",
    "status": "وضعیت",
    "stock_status": "وضعیت کیفی",
    "strategy": "روش",
    "subject": "عنوان",
    "subsidy_percent": "درصد یارانه",
    "supplier_sku": "کد کالا نزد تأمین‌کننده",
    "tags": "برچسب‌ها",
    "team": "تیم",
    "ticket_first_response_hours": "مهلت اولین پاسخ تیکت (ساعت)",
    "ticket_resolution_hours": "مهلت حل تیکت (ساعت)",
    "tiers": "پله‌ها",
    "title": "عنوان",
    "to_location_id": "محل مقصد",
    "to_status": "به وضعیت",
    "to_vehicle_id": "خودروی مقصد",
    "to_warehouse_id": "انبار مقصد",
    "total_weight_kg": "وزن کل",
    "tracking_url": "لینک رهگیری",
    "type": "نوع",
    "unit": "واحد",
    "units_per_pallet": "تعداد در پالت",
    "uom": "واحد",
    "user_id": "کاربر",
    "username": "نام کاربری",
    "valuation_method": "روش ارزش‌گذاری",
    "variant_label": "عنوان تنوع",
    "vehicle_color": "رنگ خودرو",
    "vehicle_id": "خودرو",
    "vehicle_model": "مدل خودرو",
    "vehicle_name": "نام خودرو",
    "vehicle_status": "وضعیت خودرو",
    "vehicle_type": "نوع خودرو",
    "visibility": "نوع پیام",
    "warehouse_count": "تعداد انبار",
    "warehouse_id": "انبار",
    "website": "وب‌سایت",
    "weekday": "روز هفته",
    "weight_kg": "وزن",
    "width_cm": "عرض",
    "zone_location_id": "محدوده محل",
}
DEFAULT_LABEL = "این فیلد"

# شرح انسانی هر الگوی regex که در schemaها و مسیرها هست، دقیقاً همان چیزی که الگو می‌سنجد (نه بیشتر).
# آزمون tests/api/test_validation_messages.py همه الگوهای واقعی را پیدا می‌کند و الگوی بی‌شرح را رد می‌کند.
PATTERN_RULES = {
    r"^[0-9A-Za-z._/-]+$": "فقط می‌تواند حرف انگلیسی، عدد و نشانه‌های . _ / - داشته باشد (بدون فاصله).",
    r"^[0-9A-Za-z._/-]*$": "فقط می‌تواند حرف انگلیسی، عدد و نشانه‌های . _ / - داشته باشد (بدون فاصله).",
    r"^[0-9A-Za-z-]+$": "فقط می‌تواند حرف انگلیسی، عدد و خط تیره (-) داشته باشد (بدون فاصله).",
    r"^\S+$": "نباید فاصله داشته باشد.",
    r"^09\d{9}$": "باید ۱۱ رقم باشد و با ۰۹ شروع شود.",
    r"^(09\d{9})?$": "باید خالی بماند یا ۱۱ رقم باشد و با ۰۹ شروع شود.",
    r"^\d{10}$": "باید دقیقاً ۱۰ رقم باشد.",
    r"^\d{11}$": "باید دقیقاً ۱۱ رقم باشد.",
    r"^\d{11,14}$": "باید ۱۱ تا ۱۴ رقم باشد.",
    r"^\d{1,32}$": "فقط باید رقم باشد.",
    r"^0\d{9,10}$": "باید با ۰ شروع شود و همراه کد شهر ۱۰ یا ۱۱ رقم باشد.",
    r"^(\d{2}[آ-ی]\d{3}-\d{2}|\d{3}-\d{5})$": "باید مثل ۱۲ب۳۴۵-۶۷ (خودرو) یا ۱۲۳-۴۵۶۷۸ (موتور) باشد.",
    r"^[a-z0-9][a-z0-9-]*$": "فقط می‌تواند حرف انگلیسی، عدد و خط تیره (-) داشته باشد و باید با حرف یا عدد شروع شود.",
    r"^[A-Z0-9][A-Z0-9-]*$": "فقط می‌تواند حرف انگلیسی، عدد و خط تیره (-) داشته باشد و باید با حرف یا عدد شروع شود.",
    r"^#[0-9A-Fa-f]{6}$": "باید کد رنگ شش‌رقمی مثل #1A73E8 باشد.",
    # مقدارهای فنی که خود برنامه می‌فرستد، نه کاربر
    r"^[A-Za-z0-9._:-]{8,64}$": "معتبر نیست؛ صفحه را تازه کنید و دوباره تلاش کنید.",
    r"^[a-z_.]{3,48}$": "معتبر نیست؛ صفحه را تازه کنید و دوباره تلاش کنید.",
    r"^[a-z_]{3,48}$": "معتبر نیست؛ صفحه را تازه کنید و دوباره تلاش کنید.",
    r"^[a-z0-9_-]{1,40}$": "معتبر نیست؛ صفحه را تازه کنید و دوباره تلاش کنید.",
    r"^password$": "معتبر نیست؛ صفحه را تازه کنید و دوباره تلاش کنید.",
}
# برچسب فیلدهای فنی که در هیچ فرمی دیده نمی‌شوند
FIELD_LABELS.update({"Idempotency-Key": "شناسه درخواست", "key": "شناسه", "tour_id": "شناسه راهنما",
                     "grant_type": "نوع ورود"})

_LOC_ROOTS = {"body", "query", "path", "header", "cookie"}
# نام نوع‌هایی که Pydantic در loc خطای union می‌گذارد (مثلاً ("body", "quantity", "int"))
_TYPE_TOKENS = {"int", "str", "float", "bool", "bytes", "decimal", "none", "list", "dict", "tuple", "set", "literal"}
_PERSIAN = re.compile(r"[؀-ۿ]")
_RETRY = "صفحه را تازه کنید و دوباره تلاش کنید."


def _num(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, Decimal) and value == value.to_integral_value():
        value = int(value)
    if isinstance(value, int):
        return fa_digits(f"{value:,}")
    return fa_digits(str(value)).replace(".", "٫")


def field_of(loc) -> str | None:
    """نام فیلد از loc: آخرین جزء متنی (شماره ردیف فهرست و نام نوع در union کنار گذاشته می‌شود)."""
    parts = list(loc or ())
    if parts and parts[0] in _LOC_ROOTS:
        parts = parts[1:]
    names = [p for p in parts if isinstance(p, str) and p not in _TYPE_TOKENS and "[" not in p]
    return names[-1] if names else None


def _rule(pattern) -> str | None:
    return PATTERN_RULES.get(pattern if isinstance(pattern, str) else getattr(pattern, "pattern", None))


def persian_message(error: dict) -> str:
    kind, ctx = error.get("type", ""), error.get("ctx") or {}
    field = field_of(error.get("loc"))
    label = FIELD_LABELS.get(field, DEFAULT_LABEL) if field else DEFAULT_LABEL
    if kind in ("value_error", "assertion_error"):
        # پیام اعتبارسنج‌های خود برنامه از قبل فارسی است و همان می‌ماند
        msg = re.sub(r"^(Value error|Assertion failed), ", "", str(error.get("msg", "")))
        return msg if _PERSIAN.search(msg) else f"{label} معتبر نیست."
    if kind == "missing":
        return f"{label} را وارد کنید." if field else "اطلاعات فرم کامل نیست؛ " + _RETRY
    if kind == "string_pattern_mismatch":
        rule = _rule(ctx.get("pattern"))
        return f"{label} {rule}" if rule else f"{label} قالب درستی ندارد."
    if kind == "string_too_short":
        n = ctx.get("min_length", 1)
        return f"{label} را وارد کنید." if n <= 1 else f"{label} باید دست‌کم {_num(n)} نویسه باشد."
    if kind == "string_too_long":
        return f"{label} حداکثر {_num(ctx.get('max_length'))} نویسه می‌تواند باشد."
    if kind == "too_short":
        n = ctx.get("min_length", 1)
        return f"دست‌کم یک مورد برای {label} لازم است." if n <= 1 else f"برای {label} دست‌کم {_num(n)} مورد لازم است."
    if kind == "too_long":
        return f"{label} حداکثر {_num(ctx.get('max_length'))} مورد می‌تواند داشته باشد."
    if kind == "greater_than":
        gt = ctx.get("gt")
        return f"{label} باید بیشتر از صفر باشد." if gt == 0 else f"{label} باید بیشتر از {_num(gt)} باشد."
    if kind == "greater_than_equal":
        ge = ctx.get("ge")
        return f"{label} نمی‌تواند منفی باشد." if ge == 0 else f"{label} نباید کمتر از {_num(ge)} باشد."
    if kind == "less_than":
        return f"{label} باید کمتر از {_num(ctx.get('lt'))} باشد."
    if kind == "less_than_equal":
        return f"{label} نباید بیشتر از {_num(ctx.get('le'))} باشد."
    if kind == "multiple_of":
        return f"{label} باید مضربی از {_num(ctx.get('multiple_of'))} باشد."
    if kind in ("decimal_max_places",):
        return f"{label} حداکثر {_num(ctx.get('decimal_places'))} رقم اعشار می‌پذیرد."
    if kind in ("decimal_max_digits", "decimal_whole_digits"):
        return f"{label} رقم‌های بیش از حد دارد."
    if kind in ("int_type", "int_parsing", "int_from_float"):
        return f"{label} باید عدد صحیح باشد."
    if kind == "int_parsing_size":
        return f"{label} بیش از حد بزرگ است."
    if kind in ("float_type", "float_parsing", "decimal_type", "decimal_parsing", "finite_number"):
        return f"{label} باید عدد باشد."
    if kind in ("bool_type", "bool_parsing"):
        return f"{label} باید بله یا خیر باشد."
    if kind in ("string_type", "string_unicode", "string_sub_type"):
        return f"{label} باید متن باشد."
    if kind in ("literal_error", "enum"):
        return f"مقدار {label} از گزینه‌های مجاز نیست؛ یکی از گزینه‌ها را انتخاب کنید."
    if kind.startswith("datetime_") or kind == "timezone_aware" or kind == "timezone_naive":
        return f"{label} باید تاریخ و ساعت درست باشد."
    if kind.startswith("date_"):
        return f"{label} باید تاریخ درست باشد."
    if kind.startswith("time_"):
        return f"{label} باید ساعت درست باشد."
    if kind.startswith("uuid_"):
        return f"{label} شناسه معتبری نیست."
    if kind.startswith("url_"):
        return f"{label} نشانی اینترنتی معتبری نیست."
    if kind in ("json_invalid", "json_type"):
        return "اطلاعات ارسال‌شده خوانا نیست؛ " + _RETRY
    if kind == "extra_forbidden":
        return f"{label} در این درخواست پذیرفته نمی‌شود."
    if kind in ("list_type", "tuple_type", "set_type", "dict_type", "model_type", "model_attributes_type",
                "dataclass_type", "union_tag_invalid", "union_tag_not_found"):
        return f"{label} قالب درستی ندارد؛ " + _RETRY
    return f"{label} معتبر نیست."


# input مقدار خام کاربر است (حتی رمز عبور) و url پیوند مستندات Pydantic؛ هیچ‌کدام به پاسخ نمی‌رود
_HIDDEN_KEYS = {"input", "url"}


def translate(errors: list[dict]) -> list[dict]:
    """فهرست خطای Pydantic با msg فارسی و field_label؛ loc، type و ctx همان می‌مانند."""
    out = []
    for error in errors:
        field = field_of(error.get("loc"))
        item = {k: v for k, v in error.items() if k not in _HIDDEN_KEYS}
        out.append({**item, "msg": persian_message(error),
                    "field_label": FIELD_LABELS.get(field, DEFAULT_LABEL) if field else None})
    return out
