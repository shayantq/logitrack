"""
مرحله ۱۰: انبارها (شهر مبدأ)، مسیر سفارش، گزارش «رسیدم به ...» راننده، نقشه ارسال‌ها و مسیر در پیگیری عمومی.
"""
from datetime import datetime, time, timedelta, timezone

import pytest

from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import (
    Customer, Inventory, Order, OrderCheckpoint, OrderItem, OrderStatusHistory, Organization, Product, RoleEnum, User,
    Vehicle, Warehouse,
)
from app.routers.tracking import track_limiter
from app.services.dispatch_service import local_to_utc

TODAY = (datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)).date()


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


@pytest.fixture(autouse=True)
def _limits():
    track_limiter.reset()
    yield
    track_limiter.reset()


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    world = {}
    for slug in ("alpha", "beta"):
        org = Organization(name=f"فروشگاه {slug}", slug=slug)
        db.add(org)
        db.commit()
        set_tenant(db, org.id)
        tehran = Warehouse(name="انبار تهران", location="خیابان آزادی", province="تهران", city="تهران")
        nowhere = Warehouse(name="انبار بی‌نشان", location="جاده قدیم")
        db.add_all([tehran, nowhere])
        db.commit()
        admin = User(username=f"{slug}_admin", email=f"{slug}@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
        manager = User(username=f"{slug}_mgr", email=f"{slug}m@x.io", role=RoleEnum.WAREHOUSE_MANAGER,
                       hashed_password="x", warehouse_id=tehran.id)
        ali = User(username=f"{slug}_ali", email=f"{slug}ali@x.io", role=RoleEnum.DRIVER, hashed_password="x",
                   full_name="علی رضایی", driver_code=f"DRV-{slug}-1")
        sara = User(username=f"{slug}_sara", email=f"{slug}sara@x.io", role=RoleEnum.DRIVER, hashed_password="x",
                    full_name="سارا محمدی", driver_code=f"DRV-{slug}-2")
        db.add_all([admin, manager, ali, sara])
        db.commit()
        v_ali = Vehicle(license_plate=f"12ب345-{10 + len(world)}", type="truck", capacity_kg=5000, driver_id=ali.id, status="available")
        v_sara = Vehicle(license_plate=f"13ب345-{10 + len(world)}", type="van", capacity_kg=900, driver_id=sara.id, status="available")
        rice = Product(name="برنج", sku=f"RICE-{slug}", price=1, weight_kg=10)
        customer = Customer(name="مریم احمدی", mobile="09121112233")
        db.add_all([v_ali, v_sara, rice, customer])
        db.commit()
        db.add(Inventory(product_id=rice.id, warehouse_id=tehran.id, quantity=0))
        db.commit()

        def order(code, warehouse, city, province, vehicle=None, driver=None, status="assigned"):
            o = Order(tracking_code=code, status=status, size="m", priority=False, warehouse_id=warehouse.id,
                      delivery_window_start=local_to_utc(datetime.combine(TODAY, time(0, 5))),
                      delivery_window_end=local_to_utc(datetime.combine(TODAY, time(23, 55))),
                      destination_province=province, destination_city=city, destination_address="خیابان امام، پلاک ۳",
                      recipient_name="مریم احمدی", recipient_mobile="09121112233", customer_id=customer.id,
                      total_weight_kg=10, vehicle_id=vehicle.id if vehicle else None, driver_id=driver.id if driver else None)
            o.items.append(OrderItem(product_id=rice.id, product_name="برنج", product_sku=rice.sku, quantity=1))
            db.add(o)
            db.flush()
            db.add(OrderStatusHistory(order_id=o.id, from_status=None, to_status=status))
            db.commit()
            return o

        orders = {
            "tabriz": order(f"LT-{slug[:2].upper()}TABRIZ", tehran, "تبریز", "آذربایجان شرقی", v_ali, ali),
            "local": order(f"LT-{slug[:2].upper()}LOCAL1", tehran, "تهران", "تهران", v_sara, sara),
            "lost": order(f"LT-{slug[:2].upper()}LOST01", nowhere, "تبریز", "آذربایجان شرقی", v_sara, sara, status="pending"),
        }
        world[slug] = dict(org=org, admin=admin, manager=manager, ali=ali, sara=sara, tehran=tehran,
                           nowhere=nowhere, orders=orders)
        set_tenant(db, None)
    try:
        yield client, db, world
    finally:
        db.close()


def _status(client, user, order, status):
    res = client.put(f"/orders/{order.id}/status", json={"order_status": status}, headers=_auth(user))
    assert res.status_code == 200, res.text


def _depart(client, driver, order):
    _status(client, driver, order, "picked_up")
    _status(client, driver, order, "in_transit")


# ---------------------------------------------------------------------------
# انبارها
# ---------------------------------------------------------------------------
def test_warehouse_crud_with_city_and_permissions(env):
    client, db, world = env
    a = world["alpha"]
    listed = {w["name"]: w for w in client.get("/warehouses/", headers=_auth(a["manager"])).json()}
    assert listed["انبار تهران"]["on_map"] is True and listed["انبار تهران"]["map_city"] == "تهران"
    assert listed["انبار بی‌نشان"]["on_map"] is False
    assert listed["انبار تهران"]["products_count"] == 1 and listed["انبار تهران"]["managers_count"] == 1

    body = {"name": "انبار قزوین", "province": "قزوین", "city": "آبیك", "location": "شهرک صنعتی"}
    assert client.post("/warehouses/", json=body, headers=_auth(a["manager"])).status_code == 403
    assert client.post("/warehouses/", json={**body, "province": "کالیفرنیا"}, headers=_auth(a["admin"])).status_code == 422
    created = client.post("/warehouses/", json=body, headers=_auth(a["admin"]))
    assert created.status_code == 201, created.text
    assert created.json()["city"] == "آبیک" and created.json()["map_city"] == "آبیک"
    assert client.post("/warehouses/", json=body, headers=_auth(a["admin"])).status_code == 400   # نام تکراری

    wid = created.json()["id"]
    updated = client.put(f"/warehouses/{wid}", json={**body, "city": "تاکستان"}, headers=_auth(a["admin"]))
    assert updated.json()["map_city"] == "تاکستان"
    # انبار سازمان دیگر دیده/ویرایش نمی‌شود
    assert client.put(f"/warehouses/{wid}", json=body, headers=_auth(world["beta"]["admin"])).status_code == 404
    assert all(w["id"] != wid for w in client.get("/warehouses/", headers=_auth(world["beta"]["admin"])).json())

    assert client.delete(f"/warehouses/{a['tehran'].id}", headers=_auth(a["admin"])).status_code == 400   # کالا دارد
    assert client.delete(f"/warehouses/{wid}", headers=_auth(a["admin"])).status_code == 204

    cities = client.get("/warehouses/cities", params={"province": "قزوین"}, headers=_auth(a["admin"])).json()
    assert {"قزوین", "آبیک", "تاکستان"} <= {c["name"] for c in cities}


# ---------------------------------------------------------------------------
# مسیر و گزارش راننده
# ---------------------------------------------------------------------------
def test_route_visible_only_inside_org_and_to_own_driver(env):
    client, db, world = env
    a = world["alpha"]
    tabriz = a["orders"]["tabriz"]
    res = client.get(f"/orders/{tabriz.id}/route", headers=_auth(a["admin"]))
    assert res.status_code == 200, res.text
    route = res.json()
    assert route["available"] and [p["city"] for p in route["points"]][:2] == ["تهران", "کرج"]
    assert route["points"][-1]["city"] == "تبریز" and route["progress"]["fraction"] == 0
    assert route["frozen"] is False
    assert client.get(f"/orders/{tabriz.id}/route", headers=_auth(a["ali"])).status_code == 200
    assert client.get(f"/orders/{tabriz.id}/route", headers=_auth(a["sara"])).status_code == 404
    assert client.get(f"/orders/{tabriz.id}/route", headers=_auth(world["beta"]["admin"])).status_code == 404

    lost = client.get(f"/orders/{a['orders']['lost'].id}/route", headers=_auth(a["admin"])).json()
    assert lost["available"] is False and "انبار بی‌نشان" in lost["reason"]


def test_driver_reports_cities_in_order_and_can_undo(env):
    client, db, world = env
    a = world["alpha"]
    order, ali = a["orders"]["tabriz"], a["ali"]
    url = f"/orders/{order.id}/checkpoints"
    assert client.post(url, json={"seq": 1}, headers=_auth(ali)).status_code == 400    # هنوز حرکت نکرده
    _depart(client, ali, order)
    db.expire_all()
    assert db.get(Order, order.id).route is not None                                     # مسیر با حرکت ثابت شد

    res = client.post(url, json={"seq": 3}, headers=_auth(ali))                          # قزوین (کرج و آبیک رد شده)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["progress"]["passed_seq"] == 3 and body["progress"]["last_report"]["city"] == "قزوین"
    assert body["checkpoints"][0]["reported_by"] == "علی رضایی"
    assert client.post(url, json={"seq": 2}, headers=_auth(ali)).status_code == 400     # عقب‌تر از آخرین گزارش
    assert client.post(url, json={"seq": 3}, headers=_auth(ali)).status_code == 400     # تکراری
    assert client.post(url, json={"seq": 0}, headers=_auth(ali)).status_code == 422     # مبدأ
    assert client.post(url, json={"seq": 99}, headers=_auth(ali)).status_code == 400
    assert client.post(url, json={"seq": 4}, headers=_auth(a["sara"])).status_code == 404   # راننده دیگر
    assert client.post(url, json={"seq": 4}, headers=_auth(a["manager"])).status_code == 403

    undone = client.delete(f"{url}/last", headers=_auth(ali))
    assert undone.status_code == 200 and undone.json()["checkpoints"] == []
    assert client.post(url, json={"seq": 5}, headers=_auth(ali)).status_code == 200      # زنجان
    # گزارش قدیمی‌تر از ۳۰ دقیقه را راننده نمی‌تواند برگرداند؛ ادمین می‌تواند
    cp = db.query(OrderCheckpoint).filter(OrderCheckpoint.order_id == order.id).one()
    cp.reached_at = cp.reached_at - timedelta(hours=1)
    db.commit()
    assert client.delete(f"{url}/last", headers=_auth(ali)).status_code == 400
    assert client.delete(f"{url}/last", headers=_auth(a["admin"])).status_code == 200

    _status(client, ali, order, "delivered")
    final = client.get(f"/orders/{order.id}/route", headers=_auth(a["admin"])).json()
    assert final["progress"]["fraction"] == 1 and final["frozen"] is True
    assert client.post(url, json={"seq": 6}, headers=_auth(ali)).status_code == 400     # بعد از تحویل


def test_map_lists_active_orders_with_progress(env):
    client, db, world = env
    a = world["alpha"]
    _depart(client, a["ali"], a["orders"]["tabriz"])
    data = client.get("/map/orders", headers=_auth(a["admin"])).json()
    codes = {o["tracking_code"]: o for o in data["orders"]}
    assert set(codes) == {o.tracking_code for o in a["orders"].values()}
    assert data["unmapped"] == 1 and codes[a["orders"]["lost"].tracking_code]["available"] is False
    tabriz = codes[a["orders"]["tabriz"].tracking_code]
    assert tabriz["driver_name"] == "علی رضایی" and tabriz["status"] == "in_transit" and tabriz["plate"]

    only_moving = client.get("/map/orders", params={"scope": "in_transit"}, headers=_auth(a["admin"])).json()
    assert [o["tracking_code"] for o in only_moving["orders"]] == [a["orders"]["tabriz"].tracking_code]
    mine = client.get("/map/orders", headers=_auth(a["sara"])).json()
    assert {o["tracking_code"] for o in mine["orders"]} == {a["orders"]["local"].tracking_code, a["orders"]["lost"].tracking_code}
    assert client.get("/map/orders", params={"scope": "everything"}, headers=_auth(a["admin"])).status_code == 422


def test_public_tracking_shows_route_without_reporter_names(env):
    client, db, world = env
    a = world["alpha"]
    order = a["orders"]["tabriz"]
    _depart(client, a["ali"], order)
    client.post(f"/orders/{order.id}/checkpoints", json={"seq": 4}, headers=_auth(a["ali"]))
    public = client.get(f"/public/track/{order.tracking_code}").json()
    route = public["route"]
    assert route["available"] and route["points"][-1]["city"] == "تبریز"
    assert route["progress"]["passed_seq"] == 4
    assert route["checkpoints"][0]["city"] == "تاکستان" and route["checkpoints"][0]["reported_by"] is None
    # سفارش بدون مبدأ معلوم: بدون نقشه
    assert client.get(f"/public/track/{a['orders']['lost'].tracking_code}").json()["route"] is None


# ---------------------------------------------------------------------------
# فهرست رسمی شهرها
# ---------------------------------------------------------------------------
def test_city_list_is_public_and_per_province(env):
    client, *_ = env
    qazvin = client.get("/geo/cities", params={"province": "قزوین"}).json()
    names = [c["name"] for c in qazvin]
    assert names[0] == "قزوین" and qazvin[0]["capital"] is True        # مرکز استان اول
    assert {"تاکستان", "آبیک", "الوند", "بوئین‌زهرا"} <= set(names)
    assert len(client.get("/geo/cities").json()) > 1200


def test_unknown_or_mismatched_city_is_rejected_and_names_are_canonical(env):
    client, db, world = env
    a = world["alpha"]
    body = {"name": "انبار تست", "province": "قزوین", "city": "سسس"}
    res = client.post("/warehouses/", json=body, headers=_auth(a["admin"]))
    assert res.status_code == 422 and "در فهرست شهرها نیست" in res.text
    assert client.post("/warehouses/", json={**body, "province": "تهران", "city": "تاکستان"}, headers=_auth(a["admin"])).status_code == 422
    ok = client.post("/warehouses/", json={**body, "city": "بوئين زهرا"}, headers=_auth(a["admin"]))   # «ي» عربی و فاصله
    assert ok.status_code == 201 and ok.json()["city"] == "بوئین‌زهرا" and ok.json()["map_city"] == "بوئین‌زهرا"


def test_route_to_small_city_uses_exact_location(env):
    client, db, world = env
    a = world["alpha"]
    wh = client.post("/warehouses/", json={"name": "انبار قزوین", "province": "قزوین", "city": "قزوین"}, headers=_auth(a["admin"])).json()
    order = db.get(Order, a["orders"]["tabriz"].id)
    order.warehouse_id, order.destination_province, order.destination_city = wh["id"], "قزوین", "الوند"
    db.commit()
    route = client.get(f"/orders/{order.id}/route", headers=_auth(a["admin"])).json()
    last = route["points"][-1]
    assert [p["city"] for p in route["points"]] == ["قزوین", "الوند"] and last["approx"] is False
    assert abs(last["lat"] - 36.17) < 0.1 and 0 < route["total_km"] < 40
