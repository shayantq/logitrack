"""داده‌ها و ابزارهای مربوط به ایران: استان‌ها و نرمال‌سازی ارقام فارسی/عربی."""

# ۳۱ استان کشور (به ترتیب الفبا) — منبع واحد برای فرم‌ها، اعتبارسنجی و (بعداً) نقشه
PROVINCES = (
    "آذربایجان شرقی", "آذربایجان غربی", "اردبیل", "اصفهان", "البرز", "ایلام", "بوشهر",
    "تهران", "چهارمحال و بختیاری", "خراسان جنوبی", "خراسان رضوی", "خراسان شمالی",
    "خوزستان", "زنجان", "سمنان", "سیستان و بلوچستان", "فارس", "قزوین", "قم", "کردستان",
    "کرمان", "کرمانشاه", "کهگیلویه و بویراحمد", "گلستان", "گیلان", "لرستان", "مازندران",
    "مرکزی", "هرمزگان", "همدان", "یزد",
)

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def latin_digits(value: str) -> str:
    """فقط ارقام فارسی/عربی ← لاتین (خط تیره و فاصله حفظ می‌شوند؛ برای کدهایی مثل LT-XXXX)."""
    return value.translate(_DIGIT_MAP) if isinstance(value, str) else value


def normalize_digits(value):
    """ارقام فارسی/عربی را به لاتین تبدیل و فاصله/خط تیره را حذف می‌کند (برای کدها و شماره‌ها)."""
    if not isinstance(value, str):
        return value
    return value.translate(_DIGIT_MAP).replace(" ", "").replace("-", "").strip()


def normalize_persian_text(value):
    """یکسان‌سازی «ي/ك» عربی به «ی/ک» فارسی و حذف فاصله‌های اضافه."""
    if not isinstance(value, str):
        return value
    return " ".join(value.replace("ي", "ی").replace("ك", "ک").split())


_TO_PERSIAN = str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬")


def fa_digits(value: str) -> str:
    """ارقام لاتین ← فارسی (برای پیام‌هایی که مستقیم به کاربر نمایش داده می‌شوند)."""
    return value.translate(_TO_PERSIAN)


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """تبدیل تاریخ میلادی به شمسی (الگوریتم استاندارد؛ برای پیام‌های کاربر)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + (days // 31), 1 + (days % 31)
    else:
        jm, jd = 7 + ((days - 186) // 30), 1 + ((days - 186) % 30)
    return jy, jm, jd


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """تبدیل تاریخ شمسی به میلادی (الگوریتم استاندارد؛ برای ورود تاریخ از فایل اکسل)."""
    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    days += (jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    month_days = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 1
    while gm <= 12 and gd > month_days[gm]:
        gd -= month_days[gm]
        gm += 1
    return gy, gm, gd


def fa_date(value) -> str:
    """تاریخ (date/datetime) ← «۱۴۰۵/۰۷/۲۲»"""
    jy, jm, jd = gregorian_to_jalali(value.year, value.month, value.day)
    return fa_digits(f"{jy}/{jm:02d}/{jd:02d}")
