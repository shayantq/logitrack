"""
پیامک و ایمیل خودکار (اطلاع‌رسانی به متقاضی سازمان، مشتری سفارش، کد بازیابی رمز)

تنظیمات فقط از .env خوانده می‌شود؛ تا وقتی سرویسی تنظیم نشده، پیام فقط در لاگ ثبت می‌شود و هیچ
عملیاتی به‌خاطر نبودِ پیامک یا ایمیل خطا نمی‌دهد.

  پیامک (کاوه‌نگار):  SMS_PROVIDER=kavenegar  SMS_API_KEY=...  SMS_SENDER=شماره خط ارسال
  ایمیل (SMTP):       SMTP_HOST  SMTP_PORT(587)  SMTP_USER  SMTP_PASSWORD  SMTP_FROM  SMTP_SECURITY(starttls|ssl|none)
  پیامک سفارش به مشتری (ثبت سفارش و نظرسنجی پس از تحویل): ORDER_SMS_ENABLED=1
  آدرس سایت در لینک‌ها: PUBLIC_BASE_URL (پیش‌فرض https://passineh.ir)

ارسال واقعی در پس‌زمینه (Celery) انجام می‌شود تا درخواست کاربر منتظر سرویس بیرونی نماند.
"""
import json
import logging
import os
import smtplib
import ssl
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr

logger = logging.getLogger(__name__)

BRAND_FA = "پسینه"


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


# ---------------------------------------------------------------------------
# ارسال واقعی (داخل worker)
# ---------------------------------------------------------------------------
def deliver_sms(mobile: str, text: str) -> bool:
    if not sms_enabled():
        logger.info("SMS (not configured) to %s: %s", mobile, text)
        return False
    url = f"https://api.kavenegar.com/v1/{_env('SMS_API_KEY')}/sms/send.json"
    data = {"receptor": mobile, "message": text}
    if _env("SMS_SENDER"):
        data["sender"] = _env("SMS_SENDER")
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read().decode() or "{}")
    status = (body.get("return") or {}).get("status")
    if status != 200:
        raise RuntimeError(f"SMS provider error: {body.get('return')}")
    return True


def deliver_email(to: str, subject: str, text: str) -> bool:
    if not email_enabled():
        logger.info("Email (not configured) to %s: %s — %s", to, subject, text)
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
# صف ارسال (از سرویس‌ها صدا زده می‌شود)
# ---------------------------------------------------------------------------
def queue_sms(mobile: str | None, text: str) -> bool:
    if not mobile:
        return False
    if not sms_enabled():
        logger.info("SMS (not configured) to %s: %s", mobile, text)
        return False
    from app.tasks import send_sms_task          # جلوگیری از import چرخه‌ای
    send_sms_task.delay(mobile, text)
    return True


def queue_email(to: str | None, subject: str, text: str) -> bool:
    if not to:
        return False
    if not email_enabled():
        logger.info("Email (not configured) to %s: %s — %s", to, subject, text)
        return False
    from app.tasks import send_email_task
    send_email_task.delay(to, subject, f"{text}\n\n—\n{BRAND_FA} | {base_url()}")
    return True


# ---------------------------------------------------------------------------
# پیام‌های آماده
# ---------------------------------------------------------------------------
def organization_request_received(request) -> None:
    link = f"{base_url()}/request#status"
    queue_sms(request.contact_mobile,
              f"{BRAND_FA}: درخواست «{request.name}» ثبت شد. کد پیگیری: {request.tracking_code}\n{link}")
    queue_email(request.contact_email, f"درخواست شما در {BRAND_FA} ثبت شد — {request.tracking_code}",
                f"سلام {request.contact_name or ''}،\n\nدرخواست استفاده از {BRAND_FA} برای «{request.name}» ثبت شد و "
                f"کارشناسان ما بررسی می‌کنند.\nکد پیگیری: {request.tracking_code}\nپیگیری وضعیت: {link}")


def organization_request_approved(request, username: str, temporary_password: str | None) -> None:
    login = f"{base_url()}/app/login"
    password_line = f"\nرمز موقت: {temporary_password}" if temporary_password else ""
    queue_sms(request.contact_mobile,
              f"{BRAND_FA}: سازمان «{request.name}» فعال شد.\nنام کاربری: {username}{password_line}\n{login}")
    queue_email(request.contact_email, f"سازمان شما در {BRAND_FA} فعال شد",
                f"سلام {request.contact_name or ''}،\n\nدرخواست «{request.name}» تأیید شد و سازمان شما فعال است.\n"
                f"ورود: {login}\nنام کاربری: {username}{password_line}\n\n"
                "پس از اولین ورود، رمز عبور را از منوی کاربر تغییر دهید.")


def organization_request_rejected(request) -> None:
    reason = f"\nدلیل: {request.rejection_reason}" if request.rejection_reason else ""
    queue_sms(request.contact_mobile, f"{BRAND_FA}: درخواست «{request.name}» ({request.tracking_code}) تأیید نشد.{reason}")
    queue_email(request.contact_email, f"نتیجه بررسی درخواست {request.tracking_code}",
                f"سلام {request.contact_name or ''}،\n\nدرخواست «{request.name}» بررسی شد و تأیید نشد.{reason}\n"
                f"برای پرسش‌ها با پشتیبانی {BRAND_FA} تماس بگیرید.")


def _demo(order) -> bool:
    """سفارش‌های نسخه نمایشی هیچ پیامکی نمی‌فرستند."""
    from sqlalchemy.orm import object_session
    return bool((session := object_session(order)) is not None and session.info.get("demo"))


def order_created(order, organization_name: str) -> None:
    if not order_sms_enabled() or _demo(order):
        return
    queue_sms(order.recipient_mobile,
              f"{organization_name}: سفارش شما ثبت شد. کد پیگیری {order.tracking_code}\n{base_url()}/track/{order.tracking_code}")


def order_delivered(order, organization_name: str) -> None:
    if not order_sms_enabled() or not order.rating_token or _demo(order):
        return
    queue_sms(order.recipient_mobile,
              f"{organization_name}: سفارش {order.tracking_code} تحویل داده شد. نظرتان درباره ارسال:\n{base_url()}/rate/{order.rating_token}")


def password_reset_code(user, code: str, channel: str) -> None:
    text = f"{BRAND_FA}: کد بازیابی رمز عبور شما: {code}\nاین کد ۱۰ دقیقه معتبر است. اگر شما درخواست نداده‌اید، این پیام را نادیده بگیرید."
    if channel == "sms":
        queue_sms(user.mobile, text)
    else:
        queue_email(user.email, f"کد بازیابی رمز عبور {BRAND_FA}", text)
