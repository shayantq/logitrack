"""
تست‌های مرحله ۹:
  - هر فیلتر جستجوی پیشرفته نتیجه درست برگرداند (کد، کالا، راننده، پلاک، تاریخ تحویل، استان، فوری و ترکیب‌ها)
  - مشتری با پیگیری عمومی فقط سفارش خودش را ببیند؛ جزئیات فقط با ۴ رقم آخر موبایل
"""
from datetime import datetime, time, timedelta, timezone

import pytest

from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import (
    Customer, Order, OrderItem, OrderStatusHistory, Organization, Product, RoleEnum, User, Vehicle,
)
from app.routers.tracking import track_limiter
from app.services.dispatch_service import local_to_utc
from app.services.tracking_service import phone_attempts

TODAY = (datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)).date()


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


@pytest.fixture(autouse=True)
def _limits():
    phone_attempts.reset()
    track_limiter.reset()
    yield
    phone_attempts.reset()
    track_limiter.reset()


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    world = {}
    n = [0]
    for slug in ("alpha", "beta"):
        org = Organization(name=f"فروشگاه {slug}", slug=slug)
        db.add(org)
        db.commit()
        set_tenant(db, org.id)
        admin = User(username=f"{slug}_admin", email=f"{slug}@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
        ali = User(username=f"{slug}_ali", email=f"{slug}ali@x.io", role=RoleEnum.DRIVER, hashed_password="x",
                   full_name="علی رضایی", driver_code=f"DRV-{slug}-1")
        sara = User(username=f"{slug}_sara", email=f"{slug}sara@x.io", role=RoleEnum.DRIVER, hashed_password="x",
                    full_name="سارا محمدی", driver_code=f"DRV-{slug}-2")
        db.add_all([admin, ali, sara])
        db.commit()
        v_ali = Vehicle(license_plate="۲۲ایران۹۸۷ج۱۲", type="van", capacity_kg=1000, driver_id=ali.id, status="available")  # قالب قدیمی
        v_sara = Vehicle(license_plate="12ب345-67", type="pickup", capacity_kg=1000, driver_id=sara.id, status="available")  # قالب جدید
        rice = Product(name="برنج ایرانی ۱۰ کیلویی", sku=f"RICE-{slug}", price=1, weight_kg=10)
        oil = Product(name="روغن مایع", sku=f"OIL-{slug}", price=1, weight_kg=4)
        customer = Customer(name="مریم احمدی", mobile="09121112233")
        db.add_all([v_ali, v_sara, rice, oil, customer])
        db.commit()

        def order(day, product, vehicle=None, driver=None, province="تهران", city="تهران", status="assigned", priority=False):
            n[0] += 1
            o = Order(tracking_code=f"LT-{slug[:2].upper()}{n[0]:06d}", status=status, size="m", priority=priority,
                      delivery_window_start=local_to_utc(datetime.combine(day, time(10))),
                      delivery_window_end=local_to_utc(datetime.combine(day, time(12))),
                      destination_province=province, destination_city=city, destination_address="خیابان آزادی، پلاک ۷",
                      recipient_name="مریم احمدی", recipient_mobile="09121112233", customer_id=customer.id,
                      total_weight_kg=10, vehicle_id=vehicle.id if vehicle else None, driver_id=driver.id if driver else None)
            o.items.append(OrderItem(product_id=product.id, product_name=product.name, product_sku=product.sku, quantity=1))
            db.add(o)
            db.flush()
            db.add(OrderStatusHistory(order_id=o.id, from_status=None, to_status="pending"))
            if status != "pending":
                db.add(OrderStatusHistory(order_id=o.id, from_status="pending", to_status="assigned"))
            db.commit()
            return o

        orders = {
            "today_rice_ali": order(TODAY, rice, v_ali, ali),
            "tomorrow_oil_sara": order(TODAY + timedelta(days=1), oil, v_sara, sara, province="قزوین", city="قزوین", priority=True),
            "tomorrow_rice_pending": order(TODAY + timedelta(days=1), rice, status="pending", province="قزوین", city="آبیک"),
            "week_oil_ali": order(TODAY + timedelta(days=6), oil, v_ali, ali, province="اصفهان", city="اصفهان"),
        }
        world[slug] = dict(org=org, admin=admin, ali=ali, sara=sara, v_ali=v_ali, v_sara=v_sara, orders=orders)
        set_tenant(db, None)
    try:
        yield client, db, world
    finally:
        db.close()


def _codes(client, user, **params) -> set[str]:
    res = client.get("/orders/", params=params, headers=_auth(user))
    assert res.status_code == 200, res.text
    return {o["tracking_code"] for o in res.json()}


def _expect(w, *keys) -> set[str]:
    return {w["orders"][k].tracking_code for k in keys}


# ---------------------------------------------------------------------------
# جستجوی پیشرفته
# ---------------------------------------------------------------------------
def test_each_search_filter_returns_correct_orders(env):
    client, db, world = env
    a = world["alpha"]
    admin = a["admin"]
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    target = a["orders"]["tomorrow_oil_sara"].tracking_code

    assert _codes(client, admin, tracking_code=target[-4:]) == {target}                          # بخشی از کد
    assert _codes(client, admin, tracking_code=target.lower()) == {target}
    assert _codes(client, admin, product="برنج") == _expect(a, "today_rice_ali", "tomorrow_rice_pending")
    assert _codes(client, admin, product="OIL-alpha") == _expect(a, "tomorrow_oil_sara", "week_oil_ali")   # با کد کالا
    assert _codes(client, admin, driver="رضایی") == _expect(a, "today_rice_ali", "week_oil_ali")
    assert _codes(client, admin, driver="DRV-alpha-2") == _expect(a, "tomorrow_oil_sara")
    assert _codes(client, admin, driver_id=a["sara"].id) == _expect(a, "tomorrow_oil_sara")
    # پلاک با قالب‌های مختلف ذخیره‌شده؛ جستجو با ارقام فارسی/لاتین و با/بدون «ایران»
    assert _codes(client, admin, plate="987ج") == _expect(a, "today_rice_ali", "week_oil_ali")
    assert _codes(client, admin, plate="۹۸۷") == _expect(a, "today_rice_ali", "week_oil_ali")
    assert _codes(client, admin, plate="12 ب 345 ایران 67") == _expect(a, "tomorrow_oil_sara")
    assert _codes(client, admin, province="قزوین") == _expect(a, "tomorrow_oil_sara", "tomorrow_rice_pending")
    assert _codes(client, admin, delivery_from=tomorrow, delivery_to=tomorrow) == _expect(a, "tomorrow_oil_sara", "tomorrow_rice_pending")  # «سفارش‌های فردا»
    assert _codes(client, admin, delivery_from=TODAY.isoformat(), delivery_to=(TODAY + timedelta(days=6)).isoformat()) == _expect(
        a, "today_rice_ali", "tomorrow_oil_sara", "tomorrow_rice_pending", "week_oil_ali")
    assert _codes(client, admin, priority="true") == _expect(a, "tomorrow_oil_sara")
    assert _codes(client, admin, order_status="pending") == _expect(a, "tomorrow_rice_pending")
    # ترکیب فیلترها (AND)
    assert _codes(client, admin, product="برنج", delivery_from=tomorrow, delivery_to=tomorrow) == _expect(a, "tomorrow_rice_pending")
    assert _codes(client, admin, driver="علی", province="اصفهان") == _expect(a, "week_oil_ali")
    assert _codes(client, admin, product="ماکارونی") == set()


def test_global_search_box_covers_everything(env):
    client, db, world = env
    a = world["alpha"]
    admin = a["admin"]
    assert _codes(client, admin, q="روغن") == _expect(a, "tomorrow_oil_sara", "week_oil_ali")          # کالا
    assert _codes(client, admin, q="سارا") == _expect(a, "tomorrow_oil_sara")                          # راننده
    assert _codes(client, admin, q="۹۸۷ج") == _expect(a, "today_rice_ali", "week_oil_ali")              # پلاک
    assert _codes(client, admin, q="آبیک") == _expect(a, "tomorrow_rice_pending")                       # شهر
    assert _codes(client, admin, q="۰۹۱۲۱۱۱") == _expect(a, "today_rice_ali", "tomorrow_oil_sara", "tomorrow_rice_pending", "week_oil_ali")


def test_search_never_crosses_organizations(env):
    client, db, world = env
    a, b = world["alpha"], world["beta"]
    beta_code = b["orders"]["today_rice_ali"].tracking_code
    assert _codes(client, a["admin"], tracking_code=beta_code) == set()
    assert _codes(client, a["admin"], q=beta_code) == set()
    assert _codes(client, a["admin"], product="RICE-beta") == set()
    all_alpha = _codes(client, a["admin"])
    assert all_alpha == _expect(a, *a["orders"]) and not all_alpha & _expect(b, *b["orders"])


# ---------------------------------------------------------------------------
# پیگیری عمومی
# ---------------------------------------------------------------------------
def test_public_tracking_shows_only_public_info_without_phone(env):
    client, db, world = env
    a = world["alpha"]
    code = a["orders"]["tomorrow_oil_sara"].tracking_code
    res = client.get(f"/public/track/{code.lower()}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tracking_code"] == code and body["organization_name"] == "فروشگاه alpha"
    assert body["destination_city"] == "قزوین" and body["status"] == "assigned" and body["verified"] is False
    assert body["details"] is None                                    # نشانی و اقلام نه
    assert body["recipient_masked"] == "م*** ا***"
    assert body["driver"] == {"first_name": "سارا", "vehicle_type": "pickup", "vehicle_model": None}
    assert [s["done"] for s in body["steps"]] == [True, True, False, False, False]
    raw = res.text
    assert "خیابان آزادی" not in raw and "09121112233" not in raw and "محمدی" not in raw


def test_phone_digits_unlock_details_and_wrong_guesses_are_limited(env):
    client, db, world = env
    a = world["alpha"]
    code = a["orders"]["today_rice_ali"].tracking_code
    ok = client.get(f"/public/track/{code}?phone=۲۲۳۳")              # ارقام فارسی هم قبول
    assert ok.status_code == 200 and ok.json()["verified"] is True
    details = ok.json()["details"]
    assert details["destination_address"] == "خیابان آزادی، پلاک ۷" and details["items"][0]["name"] == "برنج ایرانی ۱۰ کیلویی"

    for _ in range(5):
        wrong = client.get(f"/public/track/{code}?phone=0000")
        assert wrong.status_code == 400 and "مطابقت ندارد" in wrong.json()["detail"]
    locked = client.get(f"/public/track/{code}?phone=0001")
    assert locked.status_code == 400 and "تلاش" in locked.json()["detail"]
    # پس از قفل، حدس درست هم جزئیات را باز نمی‌کند (وگرنه همه ۱۰٬۰۰۰ حالت قابل امتحان بود)
    still_locked = client.get(f"/public/track/{code}?phone=2233")
    assert still_locked.status_code == 400 and "تلاش" in still_locked.json()["detail"]
    # ثبت تیکت عمومی هم همان قفل را دارد
    ticket = client.post(f"/public/track/{code}/tickets", data={"phone": "2233", "category": "other", "body": "بسته نرسیده است"})
    assert ticket.status_code == 400 and "تلاش" in ticket.json()["detail"]
    assert client.get(f"/public/track/{code}?phone=12").status_code == 400


def test_customer_sees_only_own_order(env):
    client, db, world = env
    a, b = world["alpha"], world["beta"]
    mine = a["orders"]["today_rice_ali"].tracking_code
    body = client.get(f"/public/track/{mine}").json()
    assert body["tracking_code"] == mine and body["organization_name"] == "فروشگاه alpha"
    assert client.get("/public/track/LT-NOTREAL1").status_code == 404
    # نمی‌توان با کد یک سفارش، سفارش‌های دیگر را فهرست کرد؛ endpoint فهرست عمومی وجود ندارد
    assert client.get("/public/track").status_code in (404, 405)
    other = client.get(f"/public/track/{b['orders']['today_rice_ali'].tracking_code}").json()
    assert other["organization_name"] == "فروشگاه beta"


def test_final_states_and_rating_link_after_delivery(env):
    client, db, world = env
    a = world["alpha"]
    o = a["orders"]["today_rice_ali"]
    set_tenant(db, a["org"].id)
    row = db.get(Order, o.id)
    row.status, row.delivered_at, row.rating_token = "delivered", datetime.now(timezone.utc).replace(tzinfo=None), "tok-delivered-1"
    canceled = db.get(Order, a["orders"]["week_oil_ali"].id)
    canceled.status = "canceled"
    db.add(OrderStatusHistory(order_id=canceled.id, from_status="assigned", to_status="canceled"))
    db.commit()
    set_tenant(db, None)

    public = client.get(f"/public/track/{o.tracking_code}").json()
    assert public["is_final"] and all(s["done"] for s in public["steps"])
    assert public["details"] is None
    verified = client.get(f"/public/track/{o.tracking_code}?phone=2233").json()
    assert verified["details"]["rating_token"] == "tok-delivered-1"
    c = client.get(f"/public/track/{a['orders']['week_oil_ali'].tracking_code}").json()
    assert c["status"] == "canceled" and "لغو" in c["status_text"] and c["driver"] is None


def test_legacy_orders_without_driver_id_found_via_vehicle(env):
    client, db, world = env
    a = world["alpha"]
    set_tenant(db, a["org"].id)
    legacy = db.get(Order, a["orders"]["today_rice_ali"].id)
    legacy.driver_id = None          # مثل سفارش‌های پیش از مرحله ۸
    db.commit()
    set_tenant(db, None)
    assert legacy.tracking_code in _codes(client, a["admin"], driver="رضایی")
    assert legacy.tracking_code in _codes(client, a["admin"], q="علی")
    assert client.get(f"/public/track/{legacy.tracking_code}").json()["driver"]["first_name"] == "علی"
