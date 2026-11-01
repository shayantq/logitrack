"""
پیامک و ایمیل خودکار (اطلاع‌رسانی به متقاضی سازمان، مشتری سفارش، کد بازیابی رمز)

تنظیمات فقط از .env خوانده می‌شود؛ تا وقتی سرویسی تنظیم نشده، پیام ارسال نمی‌شود (فقط گیرنده نیمه‌پنهان و طول پیام در لاگ می‌آید، نه متن) و هیچ
عملیاتی به‌خاطر نبودِ پیامک یا ایمیل خطا نمی‌دهد.

  پیامک (کاوه‌نگار):  SMS_PROVIDER=kavenegar  SMS_API_KEY=...  SMS_SENDER=شماره خط ارسال
  ایمیل (SMTP):       SMTP_HOST  SMTP_PORT(587)  SMTP_USER  SMTP_PASSWORD  SMTP_FROM  SMTP_SECURITY(starttls|ssl|none)
  پیامک سفارش به مشتری (ثبت سفارش و نظرسنجی پس از تحویل): ORDER_SMS_ENABLED=1
  آدرس سایت در لینک‌ها: PUBLIC_BASE_URL (پیش‌فرض https://passineh.ir)

پیام در همان تراکنش عملیات در صف پایدار ثبت می‌شود و ناشر پس‌زمینه آن را می‌فرستد (app/services/outbox_service.py).
پس صدا زدن این توابع باید پیش از commit باشد. متن‌های رمز موقت و کد بازیابی «حساس» علامت می‌خورند.
"""
import json
import logging
import os
import smtplib
import ssl
import urllib.parse
import urllib.request
from email.message import EmailMessage
from datetime import timedelta
from email.utils import formataddr

logger = logging.getLogger(__name__)

BRAND_FA = "پسینه"
RESET_CODE_TTL = timedelta(minutes=10)
TEMP_PASSWORD_TTL = timedelta(hours=24)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def base_url() -> str:
    return _env("PUBLIC_BASE_URL", "https://passineh.ir").rstrip("/")


def sms_enabled() -> bool:
    return _env("SMS_PROVIDER").lower() == "kavenegar" and bool(_env("SMS_API_KEY"))


def email_enabled() -> bool:
    return bool(_env("SMTP_HOST"))


def order_sms_enabled() -> bool:
    return sms_enabled() and _env("ORDER_SMS_ENABLED").lower() in ("1", "true", "yes")


def mask(recipient: str) -> str:
    """گیرنده در لاگ نیمه‌پنهان: 0912***1087 یا a***@example.com"""
    if "@" in recipient:
        name, _, domain = recipient.partition("@")
        return f"{name[:1]}***@{domain}"
    return f"{recipient[:4]}***{recipient[-4:]}" if len(recipient) > 8 else "***"


def _skipped(channel: str, recipient: str, text: str) -> None:
    # متن پیام هرگز در لاگ نمی‌آید: ممکن است رمز موقت یا کد بازیابی داشته باشد
    logger.info("%s not configured; message to %s skipped (%d chars)", channel, mask(recipient), len(text))


# ---------------------------------------------------------------------------
# ارسال واقعی (داخل worker)
# ---------------------------------------------------------------------------
def deliver_sms(mobile: str, text: str, local_id: int | None = None) -> bool:
    if not sms_enabled():
        _skipped("SMS", mobile, text)
        return False
    url = f"https://api.kavenegar.com/v1/{_env('SMS_API_KEY')}/sms/send.json"
    data = {"receptor": mobile, "message": text}
    if _env("SMS_SENDER"):
        data["sender"] = _env("SMS_SENDER")
    if local_id is not None:
        data["localid"] = str(local_id)   # ارسال دوباره همان پیام پس از مرگ worker
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read().decode() or "{}")
    status = (body.get("return") or {}).get("status")
    if status != 200:
        raise RuntimeError(f"SMS provider error: {body.get('return')}")
    return True


def deliver_email(to: str, subject: str, text: str) -> bool:
    if not email_enabled():
        _skipped("Email", to, text)
        return False
    msg = EmailMessage()
    sender = _env("SMTP_FROM") or _env("SMTP_USER")
    msg["From"] = formataddr((BRAND_FA, sender)) if "<" not in sender else sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    host, port = _env("SMTP_HOST"), int(_env("SMTP_PORT", "587") or 587)
    security = _env("SMTP_SECURITY", "starttls").lower()
    context = ssl.create_default_context()
    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        if security == "starttls":
            server.starttls(context=context)
    with server:
        if _env("SMTP_USER"):
            server.login(_env("SMTP_USER"), _env("SMTP_PASSWORD"))
        server.send_message(msg)
    return True


# ---------------------------------------------------------------------------
# صف ارسال (از سرویس‌ها و پیش از commit صدا زده می‌شود)
# ---------------------------------------------------------------------------
def queue_sms(db, mobile: str | None, text: str, **options) -> bool:
    if not mobile:
        return False
    if not sms_enabled():
        _skipped("SMS", mobile, text)
        return False
    from app.services import outbox_service     # جلوگیری از import چرخه‌ای
    outbox_service.enqueue(db, "sms", mobile, text, **options)
    return True


def queue_email(db, to: str | None, subject: str, text: str, **options) -> bool:
    if not to:
        return False
    if not email_enabled():
        _skipped("Email", to, text)
        return False
    from app.services import outbox_service
    outbox_service.enqueue(db, "email", to, f"{text}\n\n—\n{BRAND_FA} | {base_url()}", subject=subject, **options)
    return True


# ---------------------------------------------------------------------------
# پیام‌های آماده
# ---------------------------------------------------------------------------
def organization_request_received(db, request) -> None:
    link = f"{base_url()}/request#status"
    queue_sms(db, request.contact_mobile,
              f"{BRAND_FA}: درخواست «{request.name}» ثبت شد. کد پیگیری: {request.tracking_code}\n{link}",
              dedupe_key=f"request:{request.tracking_code}:received:sms")
    queue_email(db, request.contact_email, f"درخواست شما در {BRAND_FA} ثبت شد — {request.tracking_code}",
                f"سلام {request.contact_name or ''}،\n\nدرخواست استفاده از {BRAND_FA} برای «{request.name}» ثبت شد و "
                f"کارشناسان ما بررسی می‌کنند.\nکد پیگیری: {request.tracking_code}\nپیگیری وضعیت: {link}",
                dedupe_key=f"request:{request.tracking_code}:received:email")


def organization_request_approved(db, request, username: str, temporary_password: str | None) -> None:
    login = f"{base_url()}/app/login"
    password_line = f"\nرمز موقت: {temporary_password}" if temporary_password else ""
    options = {"sensitive": bool(temporary_password), "expires_in": TEMP_PASSWORD_TTL if temporary_password else None}
    queue_sms(db, request.contact_mobile,
              f"{BRAND_FA}: سازمان «{request.name}» فعال شد.\nنام کاربری: {username}{password_line}\n{login}",
              dedupe_key=f"request:{request.tracking_code}:approved:sms", **options)
    queue_email(db, request.contact_email, f"سازمان شما در {BRAND_FA} فعال شد",
                f"سلام {request.contact_name or ''}،\n\nدرخواست «{request.name}» تأیید شد و سازمان شما فعال است.\n"
                f"ورود: {login}\nنام کاربری: {username}{password_line}\n\n"
                "پس از اولین ورود، رمز عبور را از منوی کاربر تغییر دهید.",
                dedupe_key=f"request:{request.tracking_code}:approved:email", **options)


def organization_request_rejected(db, request) -> None:
    reason = f"\nدلیل: {request.rejection_reason}" if request.rejection_reason else ""
    queue_sms(db, request.contact_mobile, f"{BRAND_FA}: درخواست «{request.name}» ({request.tracking_code}) تأیید نشد.{reason}",
              dedupe_key=f"request:{request.tracking_code}:rejected:sms")
    queue_email(db, request.contact_email, f"نتیجه بررسی درخواست {request.tracking_code}",
                f"سلام {request.contact_name or ''}،\n\nدرخواست «{request.name}» بررسی شد و تأیید نشد.{reason}\n"
                f"برای پرسش‌ها با پشتیبانی {BRAND_FA} تماس بگیرید.",
                dedupe_key=f"request:{request.tracking_code}:rejected:email")


def _demo(order) -> bool:
    """سفارش‌های نسخه نمایشی هیچ پیامکی نمی‌فرستند."""
    from sqlalchemy.orm import object_session
    return bool((session := object_session(order)) is not None and session.info.get("demo"))


def order_created(db, order, organization_name: str) -> None:
    if not order_sms_enabled() or _demo(order):
        return
    queue_sms(db, order.recipient_mobile,
              f"{organization_name}: سفارش شما ثبت شد. کد پیگیری {order.tracking_code}\n{base_url()}/track/{order.tracking_code}",
              organization_id=order.organization_id, dedupe_key=f"order:{order.id}:created")


def order_delivered(db, order, organization_name: str) -> None:
    if not order_sms_enabled() or not order.rating_token or _demo(order):
        return
    queue_sms(db, order.recipient_mobile,
              f"{organization_name}: سفارش {order.tracking_code} تحویل داده شد. نظرتان درباره ارسال:\n{base_url()}/rate/{order.rating_token}",
              organization_id=order.organization_id, dedupe_key=f"order:{order.id}:delivered")


def password_reset_code(db, user, code: str, channel: str) -> None:
    text = f"{BRAND_FA}: کد بازیابی رمز عبور شما: {code}\nاین کد ۱۰ دقیقه معتبر است. اگر شما درخواست نداده‌اید، این پیام را نادیده بگیرید."
    if channel == "sms":
        queue_sms(db, user.mobile, text, sensitive=True, expires_in=RESET_CODE_TTL)
    else:
        queue_email(db, user.email, f"کد بازیابی رمز عبور {BRAND_FA}", text, sensitive=True, expires_in=RESET_CODE_TTL)
