"""نام فارسی فایل در مرورگر، همراه نام جایگزین ASCII برای کلاینت‌های قدیمی."""
from urllib.parse import quote


def branded_attachment(filename: str) -> str:
    # نتیجهٔ گزارش‌هایی که با worker قبلی ساخته شده‌اند هم قابل دانلود است.
    basename = filename.removeprefix("Pasineh_")
    fallback = quote(basename, safe="")
    branded = quote(f"پسینه_{basename}", safe="")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{branded}"
