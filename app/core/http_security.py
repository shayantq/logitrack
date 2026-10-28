"""
سخت‌سازی HTTP در خود برنامه (Caddyfile سرور تغییرات محلی دارد و دست نمی‌خورد):

- هدرهای امنیتی روی همه پاسخ‌ها: جلوگیری از حدس نوع فایل، قاب‌گرفتن سایت در سایت دیگر و ارجاع کامل آدرس
- Cache-Control: no-store روی ورود، بازیابی رمز و پاسخ‌های لینک‌های توکن‌دار (هیچ کشی نگهشان ندارد)
- سیاست CSP فقط در حالت گزارش (Report-Only): چیزی را مسدود نمی‌کند، فقط تخطی‌ها در کنسول مرورگر دیده می‌شوند
- لاگ دسترسی uvicorn: توکن لینک‌های مخفی (دمو، پشتیبانی، دعوت راننده، نظرسنجی) در لاگ سرور نمی‌آید
"""
import base64
import hashlib
import logging
import re
from pathlib import Path

# رمزها، کدها و توکن لینک‌ها نباید در هیچ کشی بمانند
NO_STORE_PREFIXES = ("/auth", "/demo", "/public/tickets", "/driver-signup", "/users/me/password")

# دوربین برای عکس مدارک و اسکن بارکد، میکروفون برای ویدیوی احراز هویت، موقعیت برای راننده
PERMISSIONS_POLICY = "camera=(self), microphone=(self), geolocation=(self), payment=(), usb=(), interest-cohort=()"

_SCRIPT = re.compile(r"<script>(.*?)</script>", re.S)


def build_csp(index_html: Path) -> str:
    """اسکریپت درون‌خطی index.html (اعمال تم پیش از رندر) با هش مجاز می‌شود، نه با unsafe-inline."""
    hashes = []
    if index_html.exists():
        for body in _SCRIPT.findall(index_html.read_text(encoding="utf-8")):
            digest = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode()
            hashes.append(f"'sha256-{digest}'")
    return "; ".join([
        "default-src 'self'",
        "script-src 'self' " + " ".join(hashes),
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "media-src 'self' blob:",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


class SecurityHeadersMiddleware:
    def __init__(self, app, csp: str):
        self.app = app
        self.static = [
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"x-frame-options", b"DENY"),
            (b"permissions-policy", PERMISSIONS_POLICY.encode()),
            (b"content-security-policy-report-only", csp.encode()),
        ]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        no_store = path.startswith(NO_STORE_PREFIXES)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", [])
                           if not (no_store and k.lower() == b"cache-control")]
                headers += self.static
                if no_store:
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


# بخش توکن این مسیرها در لاگ دسترسی با *** جایگزین می‌شود
_TOKEN_PATH = re.compile(r"(/(?:app/d|support|public/tickets|join|driver-signup|rate)/)[^/\s?\"]+")


class RedactTokenPaths(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(_TOKEN_PATH.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args)
        return True


def install_access_log_redaction() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactTokenPaths) for f in access.filters):
        access.addFilter(RedactTokenPaths())
