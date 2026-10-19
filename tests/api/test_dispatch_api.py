"""تست‌های API مرحله ۷: برنامه کاری رانندگان، مرخصی، پیشنهاد راننده و دسترسی‌ها."""
from datetime import date, timedelta

import pytest

from app.core.security import bcrypt_context, create_access_token
from app.core.tenancy import set_tenant
from app.models import Inventory, Organization, Product, RoleEnum, User, Vehicle, Warehouse

PASSWORD = "secret123"


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


def _next(weekday: int) -> date:
    today = date.today()
    return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    h = bcrypt_context.hash(PASSWORD)
    orgs = {}
    for slug in ("alpha", "beta"):
        org = Organization(name=slug, slug=slug)
        db.add(org)
        db.commit()
        set_tenant(db, org.id)
        wh = Warehouse(name="انبار", location="قزوین")
        db.add(wh)
        db.commit()
        admin = User(username=f"{slug}_admin", email=f"{slug}a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password=h)
        manager = User(username=f"{slug}_mgr", email=f"{slug}m@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password=h, warehouse_id=wh.id)
        driver = User(username=f"{slug}_drv", email=f"{slug}d@x.io", role=RoleEnum.DRIVER, hashed_password=h,
                      full_name="راننده " + slug, city="قزوین")
        db.add_all([admin, manager, driver])
        db.commit()
        vehicle = Vehicle(license_plate=f"{slug}-1", type="van", capacity_kg=1000, status="available", driver_id=driver.id, city="قزوین")
        product = Product(name="کالا", sku=f"S-{slug}", price=1, weight_kg=150)
        db.add_all([vehicle, product])
        db.commit()
        db.add(Inventory(product_id=product.id, warehouse_id=wh.id, quantity=20))
        db.commit()
        orgs[slug] = dict(org=org, admin=admin, manager=manager, driver=driver, vehicle=vehicle, product=product)
        set_tenant(db, None)
    try:
        yield client, db, orgs
    finally:
        db.close()


WED = _next(2)
FULL_TIME = {"employment_type": "full_time", "max_daily_orders": 6, "intercity": True, "shifts": [
    {"weekday": d, "start_time": "08:00", "end_time": "17:00"} for d in (5, 6, 0, 1, 2)
] + [{"weekday": 3, "start_time": "08:00", "end_time": "13:00"}]}


def test_schedule_crud_and_permissions(env):
    client, db, orgs = env
    a = orgs["alpha"]
    url = f"/dispatch/schedules/{a['driver'].id}"
    assert client.put(url, json=FULL_TIME, headers=_auth(a["manager"])).status_code == 403
    assert client.put(url, json=FULL_TIME, headers=_auth(orgs["beta"]["admin"])).status_code == 404   # سازمان دیگر
    res = client.put(url, json=FULL_TIME, headers=_auth(a["admin"]))
    assert res.status_code == 200, res.text
    assert len(res.json()["shifts"]) == 6 and res.json()["intercity"] is True

    overlapping = {**FULL_TIME, "shifts": [{"weekday": 2, "start_time": "08:00", "end_time": "12:00"},
                                           {"weekday": 2, "start_time": "11:00", "end_time": "15:00"}]}
    assert client.put(url, json=overlapping, headers=_auth(a["admin"])).status_code == 422
    reversed_shift = {**FULL_TIME, "shifts": [{"weekday": 2, "start_time": "18:00", "end_time": "08:00"}]}
    assert client.put(url, json=reversed_shift, headers=_auth(a["admin"])).status_code == 422

    listing = client.get(f"/dispatch/schedules?day={WED.isoformat()}", headers=_auth(a["manager"])).json()
    assert [d["driver_id"] for d in listing] == [a["driver"].id]                 # فقط رانندگان همین سازمان
    assert listing[0]["day"]["shifts"] == ["08:00–17:00"] and listing[0]["vehicle"]["capacity_kg"] == 1000

    mine = client.get("/dispatch/my-schedule", headers=_auth(a["driver"]))
    assert mine.status_code == 200 and mine.json()["max_daily_orders"] == 6
    assert client.get("/dispatch/my-schedule", headers=_auth(a["admin"])).status_code == 403


def test_time_off_blocks_suggestions_until_removed(env):
    client, db, orgs = env
    a = orgs["alpha"]
    client.put(f"/dispatch/schedules/{a['driver'].id}", json=FULL_TIME, headers=_auth(a["admin"]))
    body = {"total_weight_kg": 150, "destination_city": "قزوین", "destination_province": "قزوین",
            "delivery_window_start": f"{WED.isoformat()}T10:00:00+03:30", "delivery_window_end": f"{WED.isoformat()}T12:00:00+03:30"}
    assert len(client.post("/dispatch/suggest", json=body, headers=_auth(a["admin"])).json()["candidates"]) == 1

    off = client.post(f"/dispatch/schedules/{a['driver'].id}/time-off", headers=_auth(a["admin"]), json={
        "starts_at": f"{WED.isoformat()}T00:00:00+03:30", "ends_at": f"{(WED + timedelta(days=1)).isoformat()}T00:00:00+03:30",
        "reason": "مرخصی استحقاقی"})
    assert off.status_code == 201, off.text
    result = client.post("/dispatch/suggest", json=body, headers=_auth(a["admin"])).json()
    assert result["candidates"] == [] and "مرخصی" in result["excluded"][0]["reason"]
    listing = client.get(f"/dispatch/schedules?day={WED.isoformat()}", headers=_auth(a["admin"])).json()
    assert listing[0]["day"]["off"] is True and listing[0]["time_off"][0]["reason"] == "مرخصی استحقاقی"

    assert client.delete(f"/dispatch/schedules/{a['driver'].id}/time-off/{off.json()['id']}", headers=_auth(a["admin"])).status_code == 204
    assert len(client.post("/dispatch/suggest", json=body, headers=_auth(a["admin"])).json()["candidates"]) == 1
    assert client.post("/dispatch/suggest", json=body, headers=_auth(a["driver"])).status_code == 403


def test_order_suggestions_and_assignment_flow(env):
    client, db, orgs = env
    a = orgs["alpha"]
    client.put(f"/dispatch/schedules/{a['driver'].id}", json=FULL_TIME, headers=_auth(a["admin"]))
    payload = {
        "items": [{"product_id": a["product"].id, "quantity": 1}], "customer": {"name": "مشتری", "mobile": "09120000000"},
        "destination_province": "قزوین", "destination_city": "قزوین", "destination_address": "خیابان آزمایش ۱",
        "size": "m", "priority": False, "auto_assign": False,
        "delivery_window_start": f"{WED.isoformat()}T10:00:00+03:30", "delivery_window_end": f"{WED.isoformat()}T12:00:00+03:30",
    }
    order = client.post("/orders/", json=payload, headers=_auth(a["admin"])).json()
    sug = client.get(f"/dispatch/orders/{order['id']}/suggestions", headers=_auth(a["manager"]))
    assert sug.status_code == 200 and [c["vehicle_id"] for c in sug.json()["candidates"]] == [a["vehicle"].id]
    assert client.get(f"/dispatch/orders/{order['id']}/suggestions", headers=_auth(orgs["beta"]["admin"])).status_code == 404

    assigned = client.put(f"/orders/{order['id']}/assign", json={"vehicle_id": a["vehicle"].id}, headers=_auth(a["admin"]))
    assert assigned.status_code == 200 and assigned.json()["status"] == "assigned"
    # همان سفارش دیگر در ظرفیت خودش شمرده نمی‌شود، ولی سفارش بعدی می‌بیندش
    day = client.get(f"/dispatch/schedules?day={WED.isoformat()}", headers=_auth(a["admin"])).json()[0]["day"]
    assert (day["orders"], day["load_kg"]) == (1, 150)

    sunday = _next(6)
    payload_off = {**payload, "delivery_window_start": f"{sunday.isoformat()}T19:00:00+03:30",
                   "delivery_window_end": f"{sunday.isoformat()}T21:00:00+03:30", "auto_assign": True}
    res = client.post("/orders/", json=payload_off, headers=_auth(a["admin"]))
    assert res.status_code == 400 and "خارج از شیفت" in res.json()["detail"]
