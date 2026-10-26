"""
مجوزهای ریز (فصل ۲۲) — منبع واحد برای سرور، رابط کاربری و مستندات.

هر مجوز «حداکثر نقش‌ها» (چه کسی اصلاً می‌تواند داشته باشد) و «پیش‌فرض» دارد. ادمین سازمان در صفحه مجوزها
فقط در محدوده حداکثر نقش‌ها مجوز می‌دهد یا می‌گیرد؛ تفاوت‌ها در جدول role_permissions ذخیره می‌شود و
بررسی همیشه سمت سرور است (permission_service.ensure). مجوز «مدیریت مجوزها» از ادمین گرفته نمی‌شود
تا سازمان هرگز خودش را قفل نکند.
"""
from __future__ import annotations

from dataclasses import dataclass

ADMIN = ("org_admin",)
STAFF = ("org_admin", "warehouse_manager")


@dataclass(frozen=True)
class Permission:
    key: str
    label: str
    group: str
    max_roles: tuple[str, ...]
    default_roles: tuple[str, ...]
    sensitive: bool = False       # عملیات حساس: دلیل لازم دارد و در گزارش فعالیت ثبت می‌شود


PERMISSIONS = {p.key: p for p in (
    # موجودی و اسناد
    Permission("stock.adjust", "اصلاح موجودی و ثبت ضایعات دستی", "موجودی و اسناد", STAFF, STAFF, True),
    Permission("stock.reverse", "برگشت زدن سند انبار", "موجودی و اسناد", STAFF, STAFF, True),
    Permission("stock.status_change", "تغییر وضعیت کیفی کالا", "موجودی و اسناد", STAFF, STAFF, True),
    Permission("stock.scrap", "امحا و برگشت به تأمین‌کننده", "موجودی و اسناد", STAFF, STAFF, True),
    # انبارگردانی
    Permission("stocktake.create", "شروع انبارگردانی", "انبارگردانی", STAFF, STAFF),
    Permission("stocktake.approve", "تأیید انبارگردانی با مغایرت بالای سقف", "انبارگردانی", STAFF, ADMIN, True),
    Permission("stocktake.approve_minor", "تأیید انبارگردانی با مغایرت زیر سقف", "انبارگردانی", STAFF, ADMIN, True),
    # اطلاعات پایه
    Permission("masterdata.products", "تعریف و ویرایش کالا و قیمت", "اطلاعات پایه", STAFF, STAFF),
    Permission("masterdata.locations", "تعریف و ویرایش محل‌های انبار", "اطلاعات پایه", STAFF, STAFF),
    Permission("masterdata.partners", "تعریف و ویرایش طرف‌های تجاری", "اطلاعات پایه", STAFF, ADMIN),
    Permission("data.import", "ورود داده از اکسل (موجودی اول دوره، محل‌ها)", "اطلاعات پایه", STAFF, ADMIN, True),
    # برچسب و اسکن
    Permission("labels.print", "چاپ برچسب کالا، محل و بسته", "برچسب و بارکد", STAFF, STAFF),
    Permission("labels.reprint", "چاپ دوباره برچسب (با دلیل)", "برچسب و بارکد", STAFF, ADMIN, True),
    # گزارش و تحلیل
    Permission("analytics.view", "داشبورد شاخص‌های عملکرد", "گزارش و تحلیل", STAFF, STAFF),
    Permission("valuation.view", "ارزش‌گذاری موجودی و کالای راکد", "گزارش و تحلیل", STAFF, ADMIN),
    Permission("valuation.manage", "تغییر روش ارزش‌گذاری", "گزارش و تحلیل", ADMIN, ADMIN, True),
    # سیستم
    Permission("audit.view", "مشاهده و جست‌وجوی گزارش فعالیت", "سیستم", STAFF, ADMIN),
    Permission("permissions.manage", "مدیریت مجوزهای نقش‌ها", "سیستم", ADMIN, ADMIN, True),
    Permission("cutover.manage", "چک‌لیست راه‌اندازی و آمادگی", "سیستم", STAFF, ADMIN),
)}

# مجوزی که هرگز از ادمین سازمان گرفته نمی‌شود
LOCKED = {("org_admin", "permissions.manage")}
ROLES = ("org_admin", "warehouse_manager")
ROLE_LABELS = {"org_admin": "ادمین سازمان", "warehouse_manager": "مدیر انبار"}


def default(role: str, key: str) -> bool:
    perm = PERMISSIONS[key]
    return role in perm.default_roles


def catalog() -> list[dict]:
    return [{"key": p.key, "label": p.label, "group": p.group, "max_roles": list(p.max_roles),
             "default_roles": list(p.default_roles), "sensitive": p.sensitive} for p in PERMISSIONS.values()]
