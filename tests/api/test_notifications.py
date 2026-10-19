"""
اعلان‌ها:
  - هشدار نقطه سفارش همان لحظه خروج کالا (دفتر گردش)، یک‌بار در هر دور کمبود، با جزئیات و مسیر صفحه کالا
  - دامنه دید: ادمین همه، مدیر انبار فقط انبار خودش، راننده فقط اعلان‌های خودش، جداسازی سازمان‌ها
  - خواندن و بستن (حذف) برای هر کاربر جداست؛ خواندن همه / پاک کردن همه
  - رویدادهای دیگر: سفارش ناموفق (نه برای خود انجام‌دهنده)، تیکت تازه/پاسخ (یک اعلان برای هر تیکت)، سپردن سفارش به راننده
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core import storage
from app.routers.tickets import public_create_limiter, public_message_limiter
from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import (
    Customer, Inventory, Order, OrderItem, OrderStatusHistory, Organization, Product, RoleEnum, User, Vehicle, Warehouse,
)
from app.services import notification_service, stock_ledger


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MEDIA_ROOT", tmp_path / "media")
    public_create_limiter.reset()
    public_message_limiter.reset()
    yield


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    world = {}
    platform = User(username="root", email="root@x.io", role=RoleEnum.PLATFORM_ADMIN, hashed_password="x")
    db.add(platform)
    db.commit()
    for slug in ("alpha", "beta"):
        org = Organization(name=f"فروشگاه {slug}", slug=slug)
        db.add(org)
        db.commit()
        set_tenant(db, org.id)
        tehran = Warehouse(name="انبار تهران", province="تهران", city="تهران")
        tabriz = Warehouse(name="انبار تبریز", province="آذربایجان شرقی", city="تبریز")
        db.add_all([tehran, tabriz])
        db.commit()
        admin = User(username=f"{slug}_admin", email=f"{slug}@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x", full_name="ادمین")
        mgr = User(username=f"{slug}_mgr", email=f"{slug}m@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password="x", warehouse_id=tehran.id)
        mgr2 = User(username=f"{slug}_mgr2", email=f"{slug}m2@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password="x", warehouse_id=tabriz.id)
        ali = User(username=f"{slug}_ali", email=f"{slug}a@x.io", role=RoleEnum.DRIVER, hashed_password="x",
                   full_name="علی رضایی", driver_code=f"D-{slug}-1")
        db.add_all([admin, mgr, mgr2, ali])
        db.commit()
        vehicle = Vehicle(license_plate=f"12ب{345 + len(world)}-67", type="van", capacity_kg=900, driver_id=ali.id, status="on_route")
        product = Product(name="برنج", sku=f"R-{slug}", price=1, weight_kg=1, unit="کیسه")
        customer = Customer(name="مریم احمدی", mobile="09121112233")
        db.add_all([vehicle, product, customer])
        db.commit()
        inv = Inventory(product_id=product.id, warehouse_id=tehran.id, quantity=0, reorder_point=10, suggested_order_qty=40)
        db.add(inv)
        db.flush()
        stock_ledger.record(db, inv, 30, "receipt", reason="خرید")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        order = Order(tracking_code=f"LT-{slug[:2].upper()}000001", status="in_transit", size="m", priority=False,
                      delivery_window_start=now, delivery_window_end=now + timedelta(hours=4), destination_province="تهران",
                      destination_city="تهران", destination_address="خیابان آزادی", recipient_name="مریم احمدی",
                      recipient_mobile="09121112233", customer_id=customer.id, vehicle_id=vehicle.id, driver_id=ali.id,
                      warehouse_id=tehran.id, total_weight_kg=1, total_quantity=1)
        order.items.append(OrderItem(product_id=product.id, product_name="برنج", product_sku=product.sku, quantity=1))
        db.add(order)
        db.flush()
        db.add(OrderStatusHistory(order_id=order.id, from_status=None, to_status="in_transit"))
        db.commit()
        world[slug] = dict(org=org, tehran=tehran, admin=admin, mgr=mgr, mgr2=mgr2, ali=ali, product=product, inv=inv, order=order)
        set_tenant(db, None)
    try:
        yield client, db, world, platform
    finally:
        db.close()


def _list(client, user, **params):
    res = client.get("/notifications/", params=params, headers=_auth(user))
    assert res.status_code == 200, res.text
    return res.json()


def _ship(db, w, qty):
    set_tenant(db, w["org"].id)
    stock_ledger.record(db, db.get(Inventory, w["inv"].id), -qty, "order_out", reason="سفارش آزمون")
    db.commit()
    set_tenant(db, None)


# ---------------------------------------------------------------------------
def test_low_stock_alert_is_immediate_once_per_dip_with_details(env):
    client, db, w, _ = env
    a = w["alpha"]
    assert _list(client, a["admin"])["items"] == []

    _ship(db, a, 22)                                   # ۳۰ ← ۸ (زیر نقطه سفارش ۱۰)
    data = _list(client, a["admin"])
    assert data["unread_count"] == 1
    n = data["items"][0]
    assert (n["kind"], n["category"], n["severity"]) == ("low_stock", "inventory", "warning")
    assert n["link"] == f"/app/inventory?product={a['product'].id}"
    assert "برنج" in n["message"] and "انبار تهران" in n["message"] and n["is_read"] is False
    details = {d["label"]: d["value"] for d in n["details"]}
    assert details["موجودی فعلی"] == "۸ کیسه" and details["نقطه سفارش"] == "۱۰ کیسه" and details["پیشنهاد خرید"] == "۴۰ کیسه"

    _ship(db, a, 3)                                    # هنوز همان دور کمبود ← اعلان تازه نه
    assert len(_list(client, a["admin"])["items"]) == 1

    set_tenant(db, a["org"].id)
    stock_ledger.record(db, db.get(Inventory, a["inv"].id), 20, "receipt", reason="خرید")   # ۲۵: پر شد
    db.commit()
    set_tenant(db, None)
    _ship(db, a, 25)                                   # تمام شد ← دور تازه
    items = _list(client, a["admin"])["items"]
    assert [i["kind"] for i in items] == ["out_of_stock", "low_stock"]
    assert items[0]["severity"] == "danger" and "تمام شده" in items[0]["message"]


def test_scope_by_role_warehouse_and_organization(env):
    client, db, w, platform = env
    a, b = w["alpha"], w["beta"]
    _ship(db, a, 25)
    nid = _list(client, a["admin"])["items"][0]["id"]

    assert len(_list(client, a["mgr"])["items"]) == 1           # مدیر انبار تهران
    assert _list(client, a["mgr2"])["items"] == []              # مدیر انبار تبریز
    assert _list(client, a["ali"])["items"] == []               # راننده
    assert _list(client, b["admin"])["items"] == []             # سازمان دیگر
    assert client.get("/notifications/", headers=_auth(platform)).status_code == 403
    for res in (client.put(f"/notifications/{nid}/read", headers=_auth(b["admin"])),
                client.delete(f"/notifications/{nid}", headers=_auth(b["admin"])),
                client.delete(f"/notifications/{nid}", headers=_auth(a["mgr2"]))):
        assert res.status_code == 404
    # مسیر قدیمی همچنان کار می‌کند
    assert [n["id"] for n in client.get("/notifications/unread", headers=_auth(a["mgr"])).json()] == [nid]


def test_read_and_dismiss_are_per_user(env):
    client, db, w, _ = env
    a = w["alpha"]
    _ship(db, a, 25)
    set_tenant(db, a["org"].id)
    notification_service.notify(db, organization_id=a["org"].id, kind="ticket_new", title="تیکت", message="پیام", link="/app/tickets/1")
    db.commit()
    set_tenant(db, None)
    first, second = _list(client, a["admin"])["items"]

    assert client.put(f"/notifications/{first['id']}/read", headers=_auth(a["admin"])).status_code == 200
    admin_view = _list(client, a["admin"])
    assert admin_view["unread_count"] == 1 and admin_view["items"][0]["is_read"] is True
    assert _list(client, a["admin"], unread_only=True)["items"][0]["id"] == second["id"]
    assert _list(client, a["mgr"])["unread_count"] == 2             # خواندن ادمین روی مدیر انبار اثری ندارد

    assert client.delete(f"/notifications/{first['id']}", headers=_auth(a["admin"])).status_code == 204
    assert [n["id"] for n in _list(client, a["admin"])["items"]] == [second["id"]]
    assert len(_list(client, a["mgr"])["items"]) == 2               # بستن هم برای هر کاربر جداست

    assert client.put("/notifications/read-all", headers=_auth(a["mgr"])).json() == {"count": 2}
    assert _list(client, a["mgr"])["unread_count"] == 0
    assert client.delete("/notifications/", headers=_auth(a["mgr"])).json() == {"count": 2}
    assert _list(client, a["mgr"])["items"] == []
    assert len(_list(client, a["admin"])["items"]) == 1


def test_failed_order_notifies_staff_but_not_the_driver_who_did_it(env):
    client, db, w, _ = env
    a = w["alpha"]
    res = client.put(f"/orders/{a['order'].id}/status", json={"order_status": "failed", "note": "گیرنده در دسترس نبود"},
                     headers=_auth(a["ali"]))
    assert res.status_code == 200, res.text
    n = next(i for i in _list(client, a["admin"])["items"] if i["kind"] == "order_failed")
    assert n["link"] == f"/app/orders?order={a['order'].id}" and n["severity"] == "danger"
    details = {d["label"]: d["value"] for d in n["details"]}
    assert details["کد پیگیری"] == a["order"].tracking_code and details["علت"] == "گیرنده در دسترس نبود"
    assert details["راننده"] == "علی رضایی"
    assert any(i["kind"] == "order_failed" for i in _list(client, a["mgr"])["items"])
    assert not any(i["kind"] == "order_failed" for i in _list(client, a["mgr2"])["items"])
    assert _list(client, a["ali"])["items"] == []


def test_ticket_notifications_are_grouped_per_ticket_and_reach_the_driver(env):
    client, db, w, _ = env
    a = w["alpha"]
    res = client.post("/tickets/", data={"category": "payment", "body": "پورسانت دیروز ثبت نشده"}, headers=_auth(a["ali"]))
    assert res.status_code == 201, res.text
    tid = res.json()["id"]
    n = _list(client, a["admin"])["items"][0]
    assert (n["kind"], n["link"]) == ("ticket_new", f"/app/tickets/{tid}") and "پورسانت" in n["message"]
    client.put(f"/notifications/{n['id']}/read", headers=_auth(a["admin"]))

    client.post(f"/tickets/{tid}/messages", data={"body": "لطفاً پیگیری کنید", "visibility": "all"}, headers=_auth(a["ali"]))
    items = [i for i in _list(client, a["admin"])["items"] if i["category"] == "tickets"]
    assert len(items) == 1 and items[0]["is_read"] is False and items[0]["message"] == "لطفاً پیگیری کنید"

    client.post(f"/tickets/{tid}/messages", data={"body": "بررسی شد؛ فردا واریز می‌شود.", "visibility": "all"}, headers=_auth(a["admin"]))
    driver_items = _list(client, a["ali"])["items"]
    assert len(driver_items) == 1 and driver_items[0]["link"] == f"/app/driver/support/{tid}"
    # یادداشت داخلی برای راننده اعلان نمی‌سازد
    client.post(f"/tickets/{tid}/messages", data={"body": "یادداشت داخلی", "visibility": "side"}, headers=_auth(a["admin"]))
    assert _list(client, a["ali"])["items"][0]["message"] == "بررسی شد؛ فردا واریز می‌شود."


def test_driver_gets_assignment_notification(env):
    client, db, w, _ = env
    a = w["alpha"]
    set_tenant(db, a["org"].id)
    notification_service.order_assigned(db, db.get(Order, a["order"].id))
    db.commit()
    set_tenant(db, None)
    items = _list(client, a["ali"])["items"]
    assert len(items) == 1 and items[0]["kind"] == "order_assigned" and items[0]["link"] == "/app/driver"
    assert a["order"].tracking_code in items[0]["message"]
    assert not any(i["kind"] == "order_assigned" for i in _list(client, a["admin"])["items"])
