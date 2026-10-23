"""API مرحله ۸: قوانین پورسانت، امتیاز سازمان/مشتری/پلتفرم، پروفایل کامل، عملکرد من و برترین رانندگان."""
from datetime import timedelta

import pytest

from app.core.security import bcrypt_context, create_access_token
from app.core.tenancy import set_tenant
from app.models import DriverDocument, Inventory, Organization, Product, RoleEnum, User, Vehicle
from app.services.commission_service import DEFAULT_LEVELS, DEFAULT_TIERS
from tests.factories import default_warehouse, order_payload

PASSWORD = "secret123"


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    h = bcrypt_context.hash(PASSWORD)
    platform = User(username="root", email="r@x.io", role=RoleEnum.PLATFORM_ADMIN, hashed_password=h)
    db.add(platform)
    db.commit()
    out = {"platform": platform}
    for slug in ("alpha", "beta"):
        org = Organization(name=f"سازمان {slug}", slug=slug)
        db.add(org)
        db.commit()
        set_tenant(db, org.id)
        admin = User(username=f"{slug}_admin", email=f"{slug}a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password=h)
        manager = User(username=f"{slug}_mgr", email=f"{slug}m@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password=h)
        drivers = [User(username=f"{slug}_d{i}", email=f"{slug}d{i}@x.io", role=RoleEnum.DRIVER, hashed_password=h,
                        full_name=f"راننده {i} {slug}", city="تهران") for i in range(2)]
        db.add_all([admin, manager, *drivers])
        db.commit()
        vehicles = [Vehicle(license_plate=f"{slug}-{i}", type="van", capacity_kg=50_000, status="available",
                            driver_id=d.id, city="تهران") for i, d in enumerate(drivers)]
        product = Product(name="کالا", sku=f"S-{slug}", price=10, weight_kg=2)
        db.add_all([*vehicles, product])
        db.commit()
        db.add(Inventory(product_id=product.id, warehouse_id=default_warehouse(db, org.id).id, quantity=500))
        db.commit()
        out[slug] = dict(org=org, admin=admin, manager=manager, drivers=drivers, vehicles=vehicles, product=product)
        set_tenant(db, None)
    try:
        yield client, db, out
    finally:
        db.close()


def _deliver(client, e, driver_index=0, fee=1_000_000, status="delivered"):
    res = client.post("/orders/", json=order_payload(e["product"].id, e["vehicles"][driver_index].id, delivery_fee=fee), headers=_auth(e["admin"]))
    assert res.status_code == 201, res.text
    if status == "delivered":   # تحویل فقط پس از بارگیری و حرکت
        client.put(f"/orders/{res.json()['id']}/status", json={"order_status": "picked_up"}, headers=_auth(e["drivers"][driver_index]))
        client.put(f"/orders/{res.json()['id']}/status", json={"order_status": "in_transit"}, headers=_auth(e["drivers"][driver_index]))
    done = client.put(f"/orders/{res.json()['id']}/status", json={"order_status": status}, headers=_auth(e["drivers"][driver_index]))
    assert done.status_code == 200, done.text
    return done.json()


def test_plan_read_validate_and_save(env):
    client, db, e = env
    a = e["alpha"]
    plan = client.get("/commission-plan", headers=_auth(a["manager"])).json()
    assert plan["is_default"] and [lv["code"] for lv in plan["levels"]] == ["D", "C", "B", "A"]
    body = {"base_fare": 300_000, "fare_per_kg": 0, "levels": DEFAULT_LEVELS, "tiers": DEFAULT_TIERS}
    assert client.put("/commission-plan", json=body, headers=_auth(a["manager"])).status_code == 403
    bad_first = {**body, "levels": [{**DEFAULT_LEVELS[0], "min_deliveries": 5}, *DEFAULT_LEVELS[1:]]}
    assert client.put("/commission-plan", json=bad_first, headers=_auth(a["admin"])).status_code == 422
    bad_order = {**body, "levels": [DEFAULT_LEVELS[0], DEFAULT_LEVELS[2], DEFAULT_LEVELS[1]]}
    assert client.put("/commission-plan", json=bad_order, headers=_auth(a["admin"])).status_code == 422
    bad_tiers = {**body, "tiers": [{"from_trip": 3, "multiplier_percent": 50}]}
    assert client.put("/commission-plan", json=bad_tiers, headers=_auth(a["admin"])).status_code == 422
    saved = client.put("/commission-plan", json=body, headers=_auth(a["admin"])).json()
    assert saved["base_fare"] == 300_000 and not saved["is_default"]
    assert client.get("/commission-plan", headers=_auth(e["beta"]["admin"])).json()["is_default"]      # سازمان دیگر دست‌نخورده
    # کرایه پیش‌فرض سفارش با قانون جدید
    res = client.post("/orders/", json=order_payload(a["product"].id, a["vehicles"][0].id), headers=_auth(a["admin"]))
    assert res.json()["delivery_fee"] == 300_000            # ۳۰۰٬۰۰۰ + وزن × ۰


def test_org_and_customer_ratings(env):
    client, db, e = env
    a = e["alpha"]
    order = _deliver(client, a)
    assert order["commission_amount"] == 150_000 and order["driver_earning"] == 850_000
    assert "rating_token" not in order                       # توکن مشتری به راننده نشان داده نمی‌شود

    info = client.get(f"/orders/{order['id']}/rating", headers=_auth(a["manager"])).json()
    token = info["customer_link_token"]
    assert token and info["organization"] is None
    assert client.get(f"/orders/{order['id']}/rating", headers=_auth(a["drivers"][0])).status_code == 403

    rated = client.put(f"/orders/{order['id']}/rating", json={"score": 4, "comment": "به‌موقع"}, headers=_auth(a["admin"])).json()
    assert rated["organization"]["score"] == 4
    again = client.put(f"/orders/{order['id']}/rating", json={"score": 5}, headers=_auth(a["admin"])).json()
    assert again["organization"]["score"] == 5                # ویرایش، نه رکورد تکراری

    public = client.get(f"/public/ratings/{token}")
    assert public.status_code == 200 and public.json()["rated"] is False and public.json()["organization_name"] == "سازمان alpha"
    assert public.json()["driver_name"] == "راننده"           # فقط نام کوچک
    # برچسب باید با ستاره بخواند: ۵ ستاره + برچسب منفی ← رد
    assert client.post(f"/public/ratings/{token}", json={"score": 5, "tags": ["دیر رسید"]}).status_code == 422
    assert client.post(f"/public/ratings/{token}", json={"score": 1, "tags": ["به‌موقع رسید"]}).status_code == 422
    sent = client.post(f"/public/ratings/{token}", json={"score": 3, "comment": "کمی دیر", "tags": ["دیر رسید", "برخورد محترمانه"]})
    assert sent.status_code == 200 and sent.json()["rated"] is True
    # پس از ثبت، لینک منقضی است (نه «نظر شما ثبت شد»)
    again = client.get(f"/public/ratings/{token}")
    assert again.status_code == 410 and "قبلاً ثبت شده" in again.json()["detail"]
    assert client.post(f"/public/ratings/{token}", json={"score": 5}).status_code == 410
    stored = client.get(f"/orders/{order['id']}/rating", headers=_auth(a["admin"])).json()["customer"]
    assert stored["comment"] == "کمی دیر" and stored["tags"] == ["دیر رسید", "برخورد محترمانه"]
    assert client.get("/public/ratings/not-a-token").status_code == 404

    pending = client.post("/orders/", json=order_payload(a["product"].id, a["vehicles"][0].id), headers=_auth(a["admin"])).json()
    assert client.put(f"/orders/{pending['id']}/rating", json={"score": 5}, headers=_auth(a["admin"])).status_code == 400

    perf = client.get("/driver/performance", headers=_auth(a["drivers"][0])).json()
    by_source = perf["progress"]["ratings_by_source"]
    assert by_source["organization"]["average"] == 5 and by_source["customer"]["average"] == 3
    assert perf["progress"]["rating"] == round((5 * 0.5 + 3 * 0.35) / 0.85, 2)
    assert all(r["tracking_code"] is None for r in perf["recent_ratings"] if r["source"] == "customer")


def test_platform_rating_and_isolation(env):
    client, db, e = env
    a, b = e["alpha"], e["beta"]
    driver = a["drivers"][0]
    url = f"/platform/organizations/{a['org'].id}/drivers/{driver.id}/ratings"
    assert client.post(url, json={"score": 2, "comment": "شکایت مشتری"}, headers=_auth(a["admin"])).status_code == 403
    assert client.post(f"/platform/organizations/{b['org'].id}/drivers/{driver.id}/ratings", json={"score": 2},
                       headers=_auth(e["platform"])).status_code == 404     # راننده این سازمان نیست
    assert client.post(url, json={"score": 2, "comment": "شکایت مشتری"}, headers=_auth(e["platform"])).status_code == 201
    listing = client.get(f"/platform/organizations/{a['org'].id}/drivers", headers=_auth(e["platform"])).json()
    assert next(d for d in listing if d["driver_id"] == driver.id)["rating"] == 2.0
    assert client.get(f"/drivers/{driver.id}/overview", headers=_auth(b["admin"])).status_code == 404


def test_overview_and_leaderboard(env):
    client, db, e = env
    a = e["alpha"]
    for _ in range(3):
        _deliver(client, a, 0)
    _deliver(client, a, 1)
    _deliver(client, a, 1, status="failed")
    _deliver(client, e["beta"], 0)                              # سازمان دیگر در رتبه‌بندی نیست

    board = client.get("/drivers/leaderboard?period=month", headers=_auth(a["manager"])).json()
    assert [(r["rank"], r["driver_id"], r["deliveries"]) for r in board] == [(1, a["drivers"][0].id, 3), (2, a["drivers"][1].id, 1)]
    assert board[1]["success_rate"] == 50.0 and board[0]["earnings"] == 3 * 850_000
    assert client.get("/drivers/leaderboard", headers=_auth(a["drivers"][0])).status_code == 403

    set_tenant(db, a["org"].id)
    db.add(DriverDocument(user_id=a["drivers"][0].id, kind="selfie", file_path="x.png", content_type="image/png", size_bytes=3))
    db.commit()
    set_tenant(db, None)
    res = client.get(f"/drivers/{a['drivers'][0].id}/overview", headers=_auth(a["admin"]))
    assert res.status_code == 200, res.text
    ov = res.json()
    assert ov["profile"]["documents"][0]["kind"] == "selfie"
    assert ov["all_time"]["deliveries"] == 3 and ov["all_time"]["commission"] == 450_000
    assert ov["progress"]["level"]["code"] == "D" and ov["progress"]["next_level"]["code"] == "C"
    assert any("تحویل موفق دیگر" in n for n in ov["progress"]["needs"])
    assert ov["progress"]["trips_today"] == 3 and ov["today"]["deliveries"] == 3
    assert len(ov["recent_orders"]) == 3 and ov["vehicles"][0]["license_plate"] == "alpha-0"


def test_rating_link_expires_after_deadline(env):
    client, db, e = env
    a = e["alpha"]
    order = _deliver(client, a)
    token = client.get(f"/orders/{order['id']}/rating", headers=_auth(a["admin"])).json()["customer_link_token"]
    from app.models import Order
    from datetime import datetime, timezone
    row = db.get(Order, order["id"])
    row.delivered_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=15)
    db.commit()
    res = client.get(f"/public/ratings/{token}")
    assert res.status_code == 410 and "مهلت" in res.json()["detail"]
