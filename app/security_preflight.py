"""
بررسی امنیتی پیش از اجرای نسخه جدید روی سرور اصلی — فقط «قبول/رد» هر بررسی چاپ می‌شود، هرگز مقدارها.

    docker compose run --rm --no-deps web python -m app.security_preflight

اگر حتی یک بررسی رد شد، کد خروج ۱ است و نباید APP_ENV=production را فعال کرد.
"""
import sys

from app.core.security import insecure_settings, is_production


def main() -> int:
    checks = insecure_settings()
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"INFO  APP_ENV=production {'فعال است' if is_production() else 'هنوز فعال نیست'}")
    failed = sum(not ok for _, ok in checks)
    print("نتیجه: همه بررسی‌ها قبول شد." if not failed else f"نتیجه: {failed} بررسی رد شد.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
