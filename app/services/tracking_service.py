"""
پیگیری عمومی سفارش با کد (مرحله ۹) — بدون ورود.

حریم خصوصی: با کد پیگیری فقط اطلاعات عمومی نمایش داده می‌شود (وضعیت، مراحل، بازه تحویل، شهر مقصد،
نام کوچک راننده و نوع وسیله). نشانی کامل، نام تحویل‌گیرنده، اقلام و لینک نظرسنجی فقط پس از
وارد کردن ۴ رقم آخر موبایل گیرنده/مشتری نمایش داده می‌شود. تلاش اشتباه برای هر کد محدود است.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.iran import latin_digits
from app.core.rate_limit import RateLimiter
from app.core.tenancy import SKIP_TENANT_FILTER, set_tenant
from app.models import Customer, DriverRating, Order, OrderStatusHistory, Organization, User, Vehicle
from app.services import commission_service, route_service
from app.services.exceptions import ConflictError, NotFoundError

# ۵ تلاش اشتباه ۴ رقم موبایل برای هر کد در ساعت — حدس زدن ۱۰٬۰۰۰ حالت عملاً ممکن نیست
phone_attempts = RateLimiter(max_requests=5, window_seconds=3600)
RATING_LINK_DAYS = 14

STEPS = [
    ("registered", "ثبت سفارش"),
    ("assigned", "تخصیص راننده"),
    ("picked_up", "بارگیری از انبار"),
    ("in_transit", "در مسیر"),
    ("delivered", "تحویل"),
]
# هر وضعیت تا کدام مرحله رسیده است
REACHED = {"pending": 0, "assigned": 1, "picking_up": 1, "picked_up": 2, "in_transit": 3, "delivered": 4}
STATUS_TEXT = {
    "pending": "سفارش ثبت شده و منتظر تخصیص راننده است.",
    "assigned": "راننده تعیین شده و به‌زودی بار را از انبار تحویل می‌گیرد.",
    "picking_up": "راننده در راه انبار برای تحویل گرفتن سفارش شماست.",
    "picked_up": "سفارش از انبار بارگیری شد.",
    "in_transit": "سفارش در مسیر رسیدن به شماست.",
    "delivered": "سفارش تحویل داده شد.",
    "failed": "تحویل سفارش ناموفق بود؛ فروشنده با شما تماس می‌گیرد.",
    "canceled": "این سفارش لغو شده است.",
    "expired": "بازه تحویل این سفارش گذشت و سفارش ارسال نشد.",
}
FINAL = ("delivered", "failed", "canceled", "expired")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _mask(name: str | None) -> str | None:
    """«محمد رضایی» ← «م*** ر***»"""
    if not name:
        return None
    return " ".join(part[0] + "***" for part in name.split() if part)


def _phone_matches(order: Order, customer: Customer | None, last4: str) -> bool:
    phones = [p for p in (order.recipient_mobile, customer.mobile if customer else None) if p]
    return any(p.endswith(last4) for p in phones)


def verify_phone(order: Order, customer: Customer | None, last4: str) -> bool:
    """
    ۴ رقم آخر موبایل را با قفل هر کد بررسی می‌کند (پیگیری و ثبت تیکت عمومی مشترک‌اند).
    قفل قبل از مقایسه بررسی می‌شود؛ وگرنه پس از قفل شدن هم حدس درست جواب می‌داد و همه ۱۰٬۰۰۰ حالت قابل امتحان بود.
    """
    if phone_attempts.blocked(order.tracking_code):
        raise ConflictError("تعداد تلاش‌های نادرست زیاد است؛ یک ساعت دیگر دوباره امتحان کنید.")
    if _phone_matches(order, customer, last4):
        return True
    phone_attempts.allow(order.tracking_code)   # ثبت تلاش ناموفق
    return False


def _public_route(db: Session, order: Order) -> dict | None:
    """مسیر شهربه‌شهر و پیشرفت روی نقشه (مرحله ۱۰) — فقط نام شهرها، بدون نام گزارش‌دهنده."""
    if order.status in ("canceled", "expired"):
        return None
    info = route_service.describe(db, order, with_reporters=False)
    if not info["available"]:
        return None
    return {key: info[key] for key in ("available", "total_km", "points", "progress", "checkpoints")}


def track(db: Session, code: str, phone_last4: str | None = None) -> dict:
    code = latin_digits(code.strip()).upper()
    order = db.query(Order).filter(Order.tracking_code == code).execution_options(**SKIP_TENANT_FILTER).first()
    if order is None:
        raise NotFoundError("سفارشی با این کد پیگیری یافت نشد. کد را دوباره بررسی کنید.")
    set_tenant(db, order.organization_id)
    org = db.get(Organization, order.organization_id)
    customer = db.get(Customer, order.customer_id) if order.customer_id else None

    verified = False
    if phone_last4:
        last4 = latin_digits(phone_last4.strip())
        if len(last4) != 4 or not last4.isdigit():
            raise ConflictError("۴ رقم آخر شماره موبایل را وارد کنید.")
        if not verify_phone(order, customer, last4):
            raise ConflictError("۴ رقم آخر موبایل با اطلاعات این سفارش مطابقت ندارد.")
        verified = True

    history = db.query(OrderStatusHistory).filter(OrderStatusHistory.order_id == order.id) \
        .order_by(OrderStatusHistory.id).all()
    first_at = {}
    for h in history:
        first_at.setdefault(h.to_status, h.changed_at)
    reached = REACHED.get(order.status, -1)
    times = {
        "registered": order.created_at, "assigned": first_at.get("assigned") or (order.created_at if reached >= 1 else None),
        "picked_up": first_at.get("picked_up"), "in_transit": first_at.get("in_transit"), "delivered": order.delivered_at or first_at.get("delivered"),
    }
    if order.status in FINAL and order.status != "delivered":
        # مراحل لغو/ناموفق: تا جایی که پیش رفت + خود رویداد پایانی
        reached = max([i for i, (key, _) in enumerate(STEPS) if times.get(key)], default=0)
    steps = [{"key": key, "label": label, "done": i <= reached, "at": times.get(key) if i <= reached else None}
             for i, (key, label) in enumerate(STEPS)]

    driver_info = None
    driver_id = commission_service.driver_of(db, order)
    if driver_id and order.status in ("assigned", "picking_up", "picked_up", "in_transit", "delivered"):
        driver = db.get(User, driver_id)
        vehicle = db.get(Vehicle, order.vehicle_id) if order.vehicle_id else None
        first_name = ((driver.full_name or "").split(" ")[0] or None) if driver else None
        driver_info = {"first_name": first_name,
                       "vehicle_type": vehicle.type if vehicle else None, "vehicle_model": vehicle.model if vehicle else None}

    result = {
        "tracking_code": order.tracking_code, "status": order.status, "status_text": STATUS_TEXT.get(order.status, ""),
        "is_final": order.status in FINAL, "organization_name": org.name if org else "",
        "created_at": order.created_at, "updated_at": order.updated_at,
        "delivery_window_start": order.delivery_window_start, "delivery_window_end": order.delivery_window_end,
        "destination_province": order.destination_province, "destination_city": order.destination_city,
        "recipient_masked": _mask(order.recipient_name or (customer.name if customer else None)),
        "priority": order.priority, "steps": steps, "driver": driver_info,
        "ended_at": first_at.get(order.status) if order.status in FINAL else None,
        "verified": verified, "details": None,
        "route": _public_route(db, order),
    }
    if verified:
        rated = db.query(DriverRating).filter(DriverRating.order_id == order.id, DriverRating.source == "customer").first()
        can_rate = (order.status == "delivered" and order.rating_token and rated is None
                    and (order.delivered_at is None or order.delivered_at >= _now() - timedelta(days=RATING_LINK_DAYS)))
        result["details"] = {
            "recipient_name": order.recipient_name or (customer.name if customer else None),
            "destination_address": order.destination_address,
            "items": [{"name": i.product_name, "quantity": i.quantity} for i in order.items],
            "total_weight_kg": order.total_weight_kg,
            "rating_token": order.rating_token if can_rate else None,
        }
    return result
