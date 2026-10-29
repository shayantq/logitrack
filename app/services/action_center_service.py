"""
مرکز اقدام: صفحه ورود هر نقش، با کارهایی که الان اقدام می‌خواهند.

هر کارت از **همان تابع فهرستی** شمرده می‌شود که صفحه مقصد پیوندش نشان می‌دهد (source = endpoint و
پارامترهای همان فهرست)، تا عدد کارت و طول فهرست هرگز با هم نخوانند. کارت با شمار صفر برنمی‌گردد.
کارتی که کاربر به فهرستش دسترسی ندارد (مجوز نقش، انبار نامتصل) بی‌صدا کنار گذاشته می‌شود.
"""
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.core.iran import fa_digits
from app.models import PLATFORM_ROLES, User
from app.services import (
    backorder_service, dispatch_service, driver_portal_service, driver_service, order_service, organization_request_service,
    picking_service, putaway_service, receiving_service, replenishment_service, shipping_service, ticket_service,
    transfer_order_service,
)
from app.services.catalog_service import today_local
from app.services.exceptions import DomainError

SAMPLE = 5


@dataclass
class Card:
    key: str
    tone: str                 # danger | warning | info
    weight: int               # ترتیب نمایش (بیشتر = بالاتر)
    title: str                # چه شده
    why: str                  # چرا مهم است
    owner: str                # مسئول
    next_action: str          # اقدام بعدی
    action_label: str
    link: str                 # صفحه مقصد با همان فیلتر
    api: str                  # endpoint فهرست (برای آزمون برابری شمار و فهرست)
    query: dict = field(default_factory=dict)
    count: Callable[[], int] | None = None
    rows: Callable[[], list] | None = None
    item: Callable[[object], dict] | None = None


def _url(path: str, query: dict) -> str:
    return path + ("?" + urlencode(query) if query else "")


def _order_item(link_path: str):
    def item(o) -> dict:
        window = dispatch_service.to_local(o.delivery_window_start)
        return {"id": o.id, "label": o.tracking_code, "sub": f"{o.destination_city} · {fa_digits(window.strftime('%H:%M'))}",
                "link": f"{link_path}?order={o.id}"}
    return item


def _orders(db: Session, user: User, link_path: str = "/app/orders", **filters) -> dict:
    """کارت سفارش: شمار با count_orders و نمونه با list_orders — هر دو یک query."""
    return dict(link=_url(link_path, filters if link_path == "/app/orders" else {}), api="/orders/", query=filters,
                count=lambda: order_service.count_orders(db, user, **filters),
                rows=lambda: order_service.list_orders(db, user, limit=SAMPLE, **filters), item=_order_item(link_path))


def _listed(fn: Callable[[], list], item: Callable[[object], dict]) -> dict:
    """کارت از فهرستی که کامل برمی‌گردد (صف‌های باز کوچک‌اند): شمار = طول همان فهرست."""
    cache: list = []

    def rows():
        if not cache:
            cache.append(fn())
        return cache[0]
    return dict(count=lambda: len(rows()), rows=rows, item=item)


def _org_cards(db: Session, user: User) -> list[Card]:
    role = getattr(user.role, "value", user.role)
    week_ago = today_local() - timedelta(days=7)
    cards = [
        Card("orders_late", "danger", 100, "سفارش‌هایی که از بازه تحویل گذشته‌اند و هنوز تحویل نشده‌اند",
             "مشتری منتظر است؛ هر ساعت تأخیر احتمال لغو و نارضایتی را بیشتر می‌کند.",
             "هماهنگ‌کننده ارسال", "با راننده تماس بگیرید یا زمان تازه را به مشتری خبر دهید.", "پیگیری سفارش‌ها",
             **_orders(db, user, view="late")),
        Card("orders_unassigned", "warning", 90, "سفارش‌های بدون خودرو",
             "تا خودرو تعیین نشود بارگیری شروع نمی‌شود و ظرفیت روز از دست می‌رود.",
             "هماهنگ‌کننده ارسال", "برای هر سفارش خودرو تعیین کنید (پیشنهاد خودکار هم هست).", "تخصیص خودرو",
             **_orders(db, user, order_status="pending")),
        Card("orders_failed", "danger", 85, "تحویل‌های ناموفق هفت روز اخیر",
             "کالا تحویل نشده و مشتری منتظر تصمیم شماست.",
             "ادمین سازمان", "علت را بررسی کنید و با مشتری هماهنگ کنید.", "بررسی ناموفق‌ها",
             **_orders(db, user, order_status="failed", delivery_from=week_ago)),
        Card("tickets_waiting", "info", 80, "تیکت‌هایی که منتظر پاسخ شما هستند",
             "پاسخ دیر یعنی مشتری یا راننده بی‌خبر می‌ماند.", "پشتیبانی سازمان", "به تیکت‌ها پاسخ دهید.", "پاسخ به تیکت‌ها",
             link="/app/tickets", api="/tickets/", query={"waiting": True},
             **_listed(lambda: ticket_service.list_tickets(db, user, waiting=True),
                       lambda t: {"id": t["id"], "label": t["subject"], "sub": t["code"], "link": f"/app/tickets/{t['id']}"})),
        Card("backorders", "warning", 70, "سفارش‌های معوق (کمبود موجودی)",
             "بخشی از سفارش‌ها منتظر رسیدن کالاست؛ هر چه دیرتر تخصیص یابد، تحویل دیرتر است.",
             "مدیر انبار", "پس از رسیدن کالا تخصیص را اجرا کنید یا معوق را تعیین تکلیف کنید.", "سفارش‌های معوق",
             link="/app/backorders", api="/backorders/", query={"status": "active"},
             **_listed(lambda: backorder_service.list_backorders(db, user, status="active"),
                       lambda b: {"id": b["id"], "label": b["product_name"], "sub": b["order_tracking_code"] or "",
                                  "link": "/app/backorders"})),
        Card("reorder", "warning", 60, "کالاهایی که به نقطه سفارش رسیده‌اند",
             "اگر الان سفارش خرید داده نشود، پیش از رسیدن کالا موجودی تمام می‌شود.",
             "مدیر انبار", "برای این کالاها خرید یا انتقال برنامه‌ریزی کنید.", "نقطه سفارش",
             link="/app/reorder?status=attention", api="/replenishment/items", query={"status": "attention"},
             **_listed(lambda: replenishment_service.list_items(db, user, status="attention")["items"],
                       lambda r: {"id": r["inventory_id"], "label": r["name"],
                                  "sub": f"{r['warehouse'] or ''} · {fa_digits(str(r['quantity']))} / {fa_digits(str(r['reorder_point']))}",
                                  "link": "/app/reorder?status=attention"})),
        Card("transfers_in_transit", "info", 55, "انتقال‌های در راه",
             "کالای در راه در هیچ انباری قابل فروش نیست تا دریافت ثبت شود.",
             "مدیر انبار مقصد", "رسیدن کالا را در انبار مقصد ثبت کنید.", "انتقال‌ها",
             link="/app/transfers?status=in_transit", api="/transfer-orders/", query={"status": "in_transit"},
             **_listed(lambda: transfer_order_service.list_transfers(db, user, status="in_transit"),
                       lambda t: {"id": t["id"], "label": t["code"], "sub": f"{t['from_warehouse_name'] or ''} ← {t['to_warehouse_name'] or ''}",
                                  "link": "/app/transfers?status=in_transit"})),
    ]
    if role == "warehouse_manager":
        cards += [
            Card("receipts_open", "warning", 75, "رسیدهای منتظر دریافت",
                 "کالای رسیده تا دریافت نشود در موجودی نمی‌آید.", "مدیر انبار", "کالا را شمارش و دریافت کنید.", "رسیدها",
                 link="/app/receipts?status=open", api="/inbound/receipts", query={"status": "open", "limit": 200},
                 **_listed(lambda: receiving_service.list_receipts(db, user, status="open", limit=200),
                           lambda r: {"id": r["id"], "label": r["code"], "sub": r["partner_name"] or "",
                                      "link": f"/app/receipts?receipt={r['id']}"})),
            Card("putaway_active", "warning", 72, "وظایف جانمایی باز",
                 "کالای جانمایی‌نشده قابل برداشت نیست.", "انباردار", "کالا را در محل پیشنهادی بچینید.", "جانمایی",
                 link="/app/putaway", api="/putaway/tasks", query={"status": "active"},
                 **_listed(lambda: putaway_service.list_tasks(db, user, status="active"),
                           lambda t: {"id": t["id"], "label": t["code"], "sub": t["product_name"], "link": "/app/putaway"})),
            Card("pick_candidates", "warning", 68, "سفارش‌های آماده برداشت",
                 "تا برداشت نشوند بسته‌بندی و ارسال عقب می‌افتد.", "انباردار", "فهرست برداشت بسازید.", "برداشت",
                 link="/app/picking", api="/picking/candidates", query={},
                 **_listed(lambda: picking_service.candidates(db, user, None),
                           lambda o: {"id": o["id"], "label": o["tracking_code"], "sub": o["destination_city"] or "", "link": "/app/picking"})),
            Card("pick_lists_active", "info", 66, "فهرست‌های برداشت در جریان",
                 "برداشت نیمه‌کاره کالا را از دسترس بقیه سفارش‌ها خارج نگه می‌دارد.", "انباردار",
                 "برداشت را تمام یا کمبود را ثبت کنید.", "برداشت",
                 link="/app/picking", api="/picking/lists", query={"status": "active"},
                 **_listed(lambda: picking_service.list_pick_lists(db, user, status="active"),
                           lambda p: {"id": p["id"], "label": p["code"], "sub": "", "link": "/app/picking"})),
            Card("packing_queue", "info", 64, "سفارش‌های آماده بسته‌بندی و ارسال",
                 "سفارش برداشت‌شده تا بسته‌بندی و تحویل راننده نشود حرکت نمی‌کند.", "انباردار",
                 "بسته‌بندی کنید و محموله بسازید.", "بسته‌بندی و ارسال",
                 link="/app/shipping", api="/shipping/queue", query={},
                 **_listed(lambda: shipping_service.packing_queue(db, user, None),
                           lambda o: {"id": o["id"], "label": o["tracking_code"], "sub": o["destination_city"] or "", "link": "/app/shipping"})),
        ]
    if role == "org_admin":
        cards += [
            Card("driver_applications", "info", 50, "پرونده‌های راننده منتظر بررسی",
                 "راننده تا تأیید نشود سفارش نمی‌گیرد.", "ادمین سازمان", "مدارک را بررسی و تأیید یا رد کنید.", "بررسی پرونده‌ها",
                 link="/app/drivers", api="/drivers/applications", query={"status": "submitted"},
                 **_listed(lambda: driver_service.list_applications(db, user, "submitted"),
                           lambda a: {"id": a["user_id"], "label": a["full_name"] or a["username"], "sub": a["mobile"] or "",
                                      "link": "/app/drivers"})),
            Card("driver_requests", "info", 45, "درخواست‌های مرخصی و تغییر خودرو",
                 "پاسخ دیر برنامه رانندگان را نامعلوم می‌گذارد.", "ادمین سازمان", "درخواست‌ها را تأیید یا رد کنید.", "درخواست‌ها",
                 link="/app/driver-requests", api="/driver-requests", query={"status": "pending"},
                 **_listed(lambda: driver_portal_service.list_requests(db, user, "pending"),
                           lambda r: {"id": r["id"], "label": r["driver_name"], "sub": "مرخصی" if r["kind"] == "leave" else "تغییر خودرو",
                                      "link": "/app/driver-requests"})),
        ]
    return cards


def _driver_cards(db: Session, user: User) -> list[Card]:
    return [
        Card("driver_needs_update", "warning", 90, "سفارش‌هایی که زمان شروعشان رسیده و هنوز حرکت ثبت نشده",
             "تا وضعیت را نزنید، مشتری و ادمین از حرکت شما خبر ندارند.", "شما", "وضعیت سفر را به‌روز کنید.", "سفرهای من",
             **_orders(db, user, link_path="/app/driver", view="needs_update")),
        Card("driver_today", "info", 80, "سفارش‌های فعال امروز", "برنامه امروز شما به ترتیب بازه تحویل.",
             "شما", "سفر بعدی را شروع کنید.", "سفرهای من",
             **_orders(db, user, link_path="/app/driver", view="today")),
    ]


def _platform_cards(db: Session, user: User) -> list[Card]:
    return [
        Card("platform_tickets", "warning", 90, "تیکت‌های منتظر پشتیبانی پسینه",
             "سازمان یا مشتری منتظر پاسخ پلتفرم است.", "پشتیبانی پسینه", "به تیکت‌ها پاسخ دهید یا ارجاع را ببندید.", "پاسخ به تیکت‌ها",
             link="/app/platform/tickets", api="/platform/tickets/", query={"waiting": True},
             **_listed(lambda: ticket_service.list_tickets(db, user, waiting=True),
                       lambda t: {"id": t["id"], "label": t["subject"], "sub": t.get("organization_name") or t["code"],
                                  "link": f"/app/platform/tickets/{t['id']}"})),
        Card("organization_requests", "info", 80, "درخواست‌های ثبت سازمان",
             "متقاضی تا بررسی نشود نمی‌تواند از پسینه استفاده کند.", "ادمین پلتفرم", "درخواست را تأیید یا رد کنید.", "درخواست‌ها",
             link="/app/platform/requests", api="/platform/organization-requests", query={"status": "pending"},
             **_listed(lambda: organization_request_service.list_requests(db, "pending"),
                       lambda r: {"id": r.id, "label": r.name, "sub": r.tracking_code, "link": "/app/platform/requests"})),
    ]


def cards_for(db: Session, user: User) -> list[Card]:
    role = getattr(user.role, "value", user.role)
    if role in [getattr(r, "value", r) for r in PLATFORM_ROLES]:
        return _platform_cards(db, user)
    if role == "driver":
        return _driver_cards(db, user)
    return _org_cards(db, user)


def action_center(db: Session, user: User) -> dict:
    out = []
    for card in cards_for(db, user):
        try:
            count = card.count()
            if not count:
                continue
            items = [card.item(row) for row in card.rows()[:SAMPLE]]
        except DomainError:
            continue
        out.append({
            "key": card.key, "tone": card.tone, "weight": card.weight, "count": count, "title": card.title,
            "why": card.why, "owner": card.owner, "next_action": card.next_action, "action_label": card.action_label,
            "link": card.link, "items": items,
        })
    out.sort(key=lambda c: -c["weight"])
    return {"cards": out}
