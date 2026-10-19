"""
پنل راننده: برنامه و کارنامه روزانه، پروفایل، تغییر رمز، درخواست مرخصی فوری/عادی
و درخواست تغییر خودرو — به‌همراه بررسی ادمین و دسترسی‌ها.
"""
import base64
from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.core import storage
from app.core.security import bcrypt_context, create_access_token
from app.core.tenancy import set_tenant
from app.models import (
    DriverDocument, DriverProfile, DriverShift, DriverTimeOff, Order, Organization, RoleEnum, User, Vehicle,
)
from app.services.dispatch_service import local_to_utc

PASSWORD = "secret123"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


def _iran(day: date, hour: int = 0) -> str:
    return f"{day.isoformat()}T{hour:02d}:00:00+03:30"


TODAY = (datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)).date()


@pytest.fixture(autouse=True)
def _media(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MEDIA_ROOT", tmp_path / "media")


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    h = bcrypt_context.hash(PASSWORD)
    out = {}
    for slug in ("alpha", "beta"):
        org = Organization(name=slug, slug=slug)
        db.add(org)
        db.commit()
        set_tenant(db, org.id)
        admin = User(username=f"{slug}_admin", email=f"{slug}a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password=h)
        manager = User(username=f"{slug}_mgr", email=f"{slug}m@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password=h)
        driver = User(username=f"{slug}_drv", email=f"{slug}d@x.io", role=RoleEnum.DRIVER, hashed_password=h,
                      full_name="راننده " + slug, city="قزوین", driver_code=f"DRV-{slug}")
        other = User(username=f"{slug}_drv2", email=f"{slug}d2@x.io", role=RoleEnum.DRIVER, hashed_password=h, city="قزوین")
        db.add_all([admin, manager, driver, other])
        db.commit()
        vehicle = Vehicle(license_plate=f"1{len(slug)}ب111-11", type="pickup", model="وانت قدیمی", capacity_kg=1000,
                          status="available", driver_id=driver.id, city="قزوین")
        db.add(vehicle)
        db.commit()
        db.add(DriverProfile(user_id=driver.id, first_name="راننده", last_name=slug, national_code="0012345679",
                             mobile="09120000000", province="قزوین", city="قزوین", vehicle_id=vehicle.id,
                             vehicle_type="pickup", license_plate=vehicle.license_plate, max_weight_kg=1000))
        db.add(DriverDocument(user_id=driver.id, kind="vehicle_photo", file_path="old/photo.png", content_type="image/png", size_bytes=1))
        for wd in range(7):
            db.add(DriverShift(user_id=driver.id, weekday=wd, start_time=time(8), end_time=time(20)))
        db.commit()
        out[slug] = dict(org=org, admin=admin, manager=manager, driver=driver, other=other, vehicle=vehicle)
        set_tenant(db, None)
    try:
        yield client, db, out
    finally:
        db.close()


def _order(db, org, vehicle, day, hour=10, status="assigned", kg=100, n=[0]):
    n[0] += 1
    set_tenant(db, org.id)
    o = Order(tracking_code=f"LT-T{n[0]:06d}", status=status, size="m", priority=False,
              delivery_window_start=local_to_utc(datetime.combine(day, time(hour))),
              delivery_window_end=local_to_utc(datetime.combine(day, time(hour + 2))),
              destination_city="قزوین", total_weight_kg=kg, vehicle_id=vehicle.id)
    db.add(o)
    db.commit()
    set_tenant(db, None)
    return o


# ---------------------------------------------------------------------------
# برنامه و کارنامه
# ---------------------------------------------------------------------------
def test_agenda_shows_future_and_past_days_with_summary(env):
    client, db, e = env
    a = e["alpha"]
    _order(db, a["org"], a["vehicle"], TODAY + timedelta(days=2))
    _order(db, a["org"], a["vehicle"], TODAY - timedelta(days=3), status="delivered", kg=250)
    _order(db, a["org"], a["vehicle"], TODAY - timedelta(days=3), hour=14, status="failed")
    _order(db, e["beta"]["org"], e["beta"]["vehicle"], TODAY + timedelta(days=2))   # سازمان دیگر

    future = client.get(f"/driver/agenda?start={TODAY.isoformat()}&days=7", headers=_auth(a["driver"])).json()
    day2 = future["days"][2]
    assert len(future["days"]) == 7 and [o["status"] for o in day2["orders"]] == ["assigned"]
    assert day2["shifts"] == ["08:00–20:00"] and future["summary"]["active"] == 1

    past = client.get(f"/driver/agenda?start={(TODAY - timedelta(days=6)).isoformat()}&days=7", headers=_auth(a["driver"])).json()
    assert sorted(o["status"] for o in past["days"][3]["orders"]) == ["delivered", "failed"]
    assert past["summary"]["delivered"] == 1 and past["summary"]["failed"] == 1 and past["summary"]["delivered_kg"] == 250

    assert client.get("/driver/agenda", headers=_auth(a["other"])).json()["summary"]["active"] == 0   # راننده دیگر
    assert client.get("/driver/agenda", headers=_auth(a["admin"])).status_code == 403


# ---------------------------------------------------------------------------
# پروفایل و رمز عبور
# ---------------------------------------------------------------------------
def test_profile_view_and_contact_edit_only(env):
    client, db, e = env
    a = e["alpha"]
    me = client.get("/driver/profile", headers=_auth(a["driver"])).json()
    assert me["current_vehicle"]["license_plate"] == a["vehicle"].license_plate and me["email"] == "alphad@x.io"

    res = client.put("/driver/profile", json={"mobile": "۰۹۱۲۹۹۹۸۸۷۷", "address": "قزوین، خیابان نو، پلاک ۵", "email": "new@x.io",
                                              "national_code": "1111111111", "first_name": "تقلب"}, headers=_auth(a["driver"]))
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["mobile"], body["email"], body["address"]) == ("09129998877", "new@x.io", "قزوین، خیابان نو، پلاک ۵")
    assert body["national_code"] == "0012345679" and body["first_name"] == "راننده"     # هویت قابل تغییر نیست
    assert client.put("/driver/profile", json={"email": "betaa@x.io"}, headers=_auth(a["driver"])).status_code == 400


def test_change_password(env):
    client, db, e = env
    driver = e["alpha"]["driver"]
    bad = client.put("/users/me/password", json={"old_password": "wrong-pass", "new_password": "newpass123"}, headers=_auth(driver))
    assert bad.status_code == 400
    ok = client.put("/users/me/password", json={"old_password": PASSWORD, "new_password": "newpass123"}, headers=_auth(driver))
    assert ok.status_code == 200
    # توکن قبلی باطل می‌شود و توکن تازه برمی‌گردد
    assert client.get("/users/me", headers=_auth(driver)).status_code == 401
    assert client.get("/users/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"}).status_code == 200
    login = client.post("/auth/token", data={"username": driver.username, "password": "newpass123"})
    assert login.status_code == 200


# ---------------------------------------------------------------------------
# مرخصی
# ---------------------------------------------------------------------------
def test_leave_rules_approval_frees_orders_and_blocks_dispatch(env):
    client, db, e = env
    a = e["alpha"]
    tomorrow = TODAY + timedelta(days=1)
    assigned = _order(db, a["org"], a["vehicle"], tomorrow, hour=10)
    loaded = _order(db, a["org"], a["vehicle"], tomorrow, hour=14, status="in_transit")
    h = _auth(a["driver"])
    body = {"leave_type": "normal", "category": "family", "reason": "مراسم خانوادگی",
            "starts_at": _iran(tomorrow), "ends_at": _iran(tomorrow + timedelta(days=1))}

    # عادی کمتر از ۲۴ ساعت قبل ← رد؛ فوری برای هفته بعد ← رد
    soon = {**body, "starts_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            "ends_at": (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat()}
    assert "۲۴ ساعت" in client.post("/driver/requests/leave", json=soon, headers=h).json()["detail"]
    far = {**body, "leave_type": "urgent", "starts_at": _iran(TODAY + timedelta(days=7)), "ends_at": _iran(TODAY + timedelta(days=8))}
    assert client.post("/driver/requests/leave", json=far, headers=h).status_code == 400

    urgent = client.post("/driver/requests/leave", json={**body, "leave_type": "urgent", "category": "sickness"}, headers=h)
    assert urgent.status_code == 201, urgent.text
    req = urgent.json()
    assert req["status"] == "pending" and {o["tracking_code"] for o in req["affected_orders"]} == {assigned.tracking_code, loaded.tracking_code}
    assert client.post("/driver/requests/leave", json=body, headers=h).status_code == 400          # هم‌پوشانی

    counts = client.get("/driver-requests/pending-count", headers=_auth(a["admin"])).json()
    assert counts == {"count": 1, "urgent": 1}
    assert client.get("/driver-requests", headers=_auth(a["manager"])).status_code == 403
    assert client.post(f"/driver-requests/{req['id']}/approve", json={}, headers=_auth(e["beta"]["admin"])).status_code == 404

    res = client.post(f"/driver-requests/{req['id']}/approve", json={"note": "سلامت باشید"}, headers=_auth(a["admin"]))
    assert res.status_code == 200 and res.json()["status"] == "approved"
    db.expire_all()
    assert db.query(DriverTimeOff).filter(DriverTimeOff.user_id == a["driver"].id).count() == 1
    freed = db.get(Order, assigned.id)
    assert (freed.status, freed.vehicle_id) == ("pending", None)                                    # آزاد شد
    assert db.get(Order, loaded.id).status == "in_transit"                                          # بار گرفته؛ دست نخورد
    suggest = client.post("/dispatch/suggest", headers=_auth(a["admin"]), json={
        "total_weight_kg": 10, "destination_city": "قزوین", "delivery_window_start": _iran(tomorrow, 11),
        "delivery_window_end": _iran(tomorrow, 12)}).json()
    assert a["vehicle"].id not in [c["vehicle_id"] for c in suggest["candidates"]]

    agenda = client.get(f"/driver/agenda?start={tomorrow.isoformat()}&days=1", headers=h).json()
    assert agenda["days"][0]["off"] is True and "مرخصی فوری" in agenda["days"][0]["off_reason"]

    # لغو مرخصی تأییدشده‌ای که شروع نشده ← مرخصی حذف می‌شود
    assert client.post(f"/driver/requests/{req['id']}/cancel", headers=h).json()["status"] == "canceled"
    db.expire_all()
    assert db.query(DriverTimeOff).filter(DriverTimeOff.user_id == a["driver"].id).count() == 0


def test_reject_requires_reason(env):
    client, db, e = env
    a = e["alpha"]
    day = TODAY + timedelta(days=3)
    req = client.post("/driver/requests/leave", headers=_auth(a["driver"]), json={
        "leave_type": "normal", "category": "personal", "reason": "کار اداری", "starts_at": _iran(day), "ends_at": _iran(day, 12)}).json()
    assert client.post(f"/driver-requests/{req['id']}/reject", json={}, headers=_auth(a["admin"])).status_code == 400
    res = client.post(f"/driver-requests/{req['id']}/reject", json={"note": "آن روز بار زیاد داریم"}, headers=_auth(a["admin"]))
    assert res.json()["status"] == "rejected"
    mine = client.get("/driver/requests", headers=_auth(a["driver"])).json()
    assert mine[0]["review_note"] == "آن روز بار زیاد داریم"
    assert client.post(f"/driver/requests/{req['id']}/cancel", headers=_auth(a["driver"])).status_code == 400


# ---------------------------------------------------------------------------
# تغییر خودرو
# ---------------------------------------------------------------------------
def _vehicle_request(client, driver, **overrides):
    body = {"vehicle_type": "van", "vehicle_model": "ون هیوندای", "license_plate": "۴۵ ج ۶۷۸ ایران ۱۱", "max_weight_kg": 1500,
            "inspection_expiry": (TODAY + timedelta(days=300)).isoformat()}
    body.update(overrides)
    return client.post("/driver/requests/vehicle", json=body, headers=_auth(driver))


def test_vehicle_change_full_flow(env):
    client, db, e = env
    a = e["alpha"]
    h = _auth(a["driver"])
    req = _vehicle_request(client, a["driver"]).json()
    assert req["status"] == "draft" and req["vehicle_data"]["license_plate"] == "45ج678-11"
    assert set(req["missing"]) == {"vehicle_photo", "vehicle_card", "technical_inspection"}
    assert _vehicle_request(client, a["driver"]).status_code == 400                                 # یک درخواست باز کافی است
    assert client.post(f"/driver/requests/{req['id']}/submit", headers=h).status_code == 400        # بدون مدارک
    assert client.get("/driver-requests", headers=_auth(a["admin"])).json() == []                   # پیش‌نویس برای ادمین نیست

    for kind in ("vehicle_photo", "vehicle_card", "technical_inspection"):
        r = client.post(f"/driver/requests/{req['id']}/documents/{kind}", files={"file": ("p.png", PNG, "image/png")}, headers=h)
        assert r.status_code == 200, r.text
    assert client.post(f"/driver/requests/{req['id']}/submit", headers=h).json()["status"] == "pending"
    assert client.get(f"/driver-requests/{req['id']}/documents/vehicle_card", headers=_auth(a["admin"])).content == PNG
    assert client.get(f"/driver/requests/{req['id']}/documents/vehicle_card", headers=_auth(a["other"])).status_code == 404

    # خودروی فعلی سفارش فعال دارد ← اول باید تکمیل شود
    active = _order(db, a["org"], a["vehicle"], TODAY)
    blocked = client.post(f"/driver-requests/{req['id']}/approve", json={}, headers=_auth(a["admin"]))
    assert blocked.status_code == 400 and "سفارش فعال" in blocked.json()["detail"]
    client.put(f"/orders/{active.id}/status", json={"order_status": "picked_up"}, headers=h)
    client.put(f"/orders/{active.id}/status", json={"order_status": "in_transit"}, headers=h)
    assert client.put(f"/orders/{active.id}/status", json={"order_status": "delivered"}, headers=h).status_code == 200

    ok = client.post(f"/driver-requests/{req['id']}/approve", json={}, headers=_auth(a["admin"]))
    assert ok.status_code == 200, ok.text
    assert ok.json()["current_vehicle"]["license_plate"] == a["vehicle"].license_plate   # «قبل» حفظ می‌شود
    assert "previous" not in ok.json()["vehicle_data"]
    vehicles = client.get("/vehicles/", headers=h).json()
    assert [v["license_plate"] for v in vehicles] == ["45ج678-11", a["vehicle"].license_plate]       # جدید اول، قبلی در سابقه
    assert (vehicles[0]["capacity_kg"], vehicles[0]["type"], vehicles[1]["status"]) == (1500, "van", "inactive")
    profile = client.get("/driver/profile", headers=h).json()
    assert profile["current_vehicle"]["id"] == vehicles[0]["id"] and profile["vehicle_model"] == "ون هیوندای"
    assert client.get("/driver-onboarding/documents/vehicle_photo", headers=h).content == PNG       # مدرک جدید جایگزین شد
    # سفارش‌های خودروی قبلی هنوز در کارنامه راننده است
    history = client.get(f"/driver/agenda?start={TODAY.isoformat()}&days=1", headers=h).json()
    assert history["summary"]["delivered"] == 1


def test_same_plate_updates_vehicle_in_place_and_motorcycle_rules(env):
    client, db, e = env
    a = e["alpha"]
    h = _auth(a["driver"])
    req = _vehicle_request(client, a["driver"], vehicle_type="pickup", license_plate=a["vehicle"].license_plate, max_weight_kg=1400).json()
    for kind in ("vehicle_photo", "vehicle_card", "technical_inspection"):
        client.post(f"/driver/requests/{req['id']}/documents/{kind}", files={"file": ("p.png", PNG, "image/png")}, headers=h)
    client.post(f"/driver/requests/{req['id']}/submit", headers=h)
    assert client.post(f"/driver-requests/{req['id']}/approve", json={}, headers=_auth(a["admin"])).status_code == 200
    vehicles = client.get("/vehicles/", headers=h).json()
    assert len(vehicles) == 1 and vehicles[0]["capacity_kg"] == 1400

    moto = _vehicle_request(client, a["driver"], vehicle_type="motorcycle", license_plate="12ب345-67", max_weight_kg=100).json()
    assert "technical_inspection" not in moto["required_documents"]
    for kind in ("vehicle_photo", "vehicle_card"):
        client.post(f"/driver/requests/{moto['id']}/documents/{kind}", files={"file": ("p.png", PNG, "image/png")}, headers=h)
    res = client.post(f"/driver/requests/{moto['id']}/submit", headers=h)
    assert res.status_code == 400 and "پلاک" in res.json()["detail"]                                  # پلاک خودرو برای موتور
    assert client.post(f"/driver/requests/{moto['id']}/cancel", headers=h).json()["status"] == "canceled"


def test_future_orders_locked_until_delivery_day_and_no_delivery_without_pickup(env):
    client, db, e = env
    a = e["alpha"]
    h = _auth(a["driver"])
    future = _order(db, a["org"], a["vehicle"], TODAY + timedelta(days=5))
    for status in ("picking_up", "picked_up", "delivered", "failed"):
        res = client.put(f"/orders/{future.id}/status", json={"order_status": status}, headers=h)
        assert res.status_code == 400
    assert "تا آن روز" in res.json()["detail"]
    # ادمین هم نمی‌تواند سفارش روزهای آینده را تحویل‌شده ثبت کند؛ ولی لغو مجاز است
    assert client.put(f"/orders/{future.id}/status", json={"order_status": "picked_up"}, headers=_auth(a["admin"])).status_code == 400
    assert client.put(f"/orders/{future.id}/status", json={"order_status": "canceled"}, headers=_auth(a["admin"])).status_code == 200

    today = _order(db, a["org"], a["vehicle"], TODAY, hour=21)       # بازه امروز ← امروز مجاز است
    skipped = client.put(f"/orders/{today.id}/status", json={"order_status": "delivered"}, headers=h)
    assert skipped.status_code == 400 and "مجاز نیست" in skipped.json()["detail"]   # بدون بارگیری
    assert client.put(f"/orders/{today.id}/status", json={"order_status": "picked_up"}, headers=h).status_code == 200
    # تحویل فقط پس از ثبت حرکت («در مسیر مقصد»)
    no_departure = client.put(f"/orders/{today.id}/status", json={"order_status": "delivered"}, headers=h)
    assert no_departure.status_code == 400 and "مجاز نیست" in no_departure.json()["detail"]
    assert client.put(f"/orders/{today.id}/status", json={"order_status": "in_transit"}, headers=h).status_code == 200
    assert client.put(f"/orders/{today.id}/status", json={"order_status": "delivered"}, headers=h).status_code == 200
