"""
مرحله B و C بهره‌وری (docs/productivity.md):
  - ماشین وضعیت تحویل ناموفق: موجودی تا تصمیم بی‌تغییر، سه مسیر تعیین تکلیف، دسترسی نقش‌ها، صفحه رهگیری
  - مدرک تحویل: عکس و دسترسی به آن، گزارش فعالیت
  - یک تعریف ظرفیت برای پیشنهاد راننده و محموله؛ پیش‌نمایش محموله
  - برآورد رسیدن و نمای «در خطر»
  - مرکز استثنا: ادغام، بسته شدن خودکار، تصمیم انسان، محدوده انبار
  - تأمین مجدد رویدادی، کلید ادغام اعلان، مسئول پیشنهادی، بودجه کوئری
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import (
    AuditLog, Inventory, Order, Organization, Product, RoleEnum, Ticket, User, Vehicle,
)
from app.models_fulfillment import Backorder, Package, ReplenishmentRule
from app.models_notification import Notification
from app.models_operations import Location
from app.models_productivity import DeliveryAttempt, OperationException
from app.services import capacity_service, eta_service, exception_service
from tests.factories import default_warehouse

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


def _window(hours_from_now=1, length=6) -> dict:
    start = _now() + timedelta(hours=hours_from_now)
    return {"delivery_window_start": start.isoformat() + "Z", "delivery_window_end": (start + timedelta(hours=length)).isoformat() + "Z"}


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    org = Organization(name="فروشگاه آلفا", slug="alpha")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    warehouse = default_warehouse(db, org.id)
    admin = User(username="adm", email="a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x", full_name="ادمین")
    manager = User(username="wm", email="m@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password="x", warehouse_id=warehouse.id, full_name="مدیر انبار")
    driver = User(username="drv", email="d@x.io", role=RoleEnum.DRIVER, hashed_password="x", full_name="علی رضایی",
                  driver_code="DRV-1", driver_status="approved")
    rival = User(username="drv2", email="d2@x.io", role=RoleEnum.DRIVER, hashed_password="x", full_name="رضا کریمی",
                 driver_code="DRV-2", driver_status="approved")
    db.add_all([admin, manager, driver, rival])
    db.commit()
    vehicle = Vehicle(license_plate="12ب345-67", type="van", capacity_kg=1000, driver_id=driver.id, status="available")
    product = Product(name="برنج", sku="RICE-1", barcode="62600001", price=1000, weight_kg=10)
    db.add_all([vehicle, product])
    db.commit()
    db.add(Inventory(product_id=product.id, warehouse_id=warehouse.id, quantity=100, stock_status="available"))
    db.commit()
    yield SimpleNamespace(client=client, db=db, org=org, warehouse=warehouse, admin=admin, manager=manager, driver=driver,
                          rival=rival, vehicle=vehicle, product=product)
    db.close()


def _order(env, quantity=5) -> dict:
    res = env.client.post("/orders/", headers=_auth(env.admin), json={
        "items": [{"product_id": env.product.id, "quantity": quantity}],
        "customer": {"name": "مریم احمدی", "mobile": "09121112233"},
        "destination_province": "تهران", "destination_city": "تهران", "destination_address": "خیابان آزادی پلاک ۱",
        "size": "m", "vehicle_id": env.vehicle.id, "warehouse_id": env.warehouse.id, **_window(-1),
    })
    assert res.status_code == 201, res.text
    return res.json()


def _status(env, order_id, status, user=None, **body):
    return env.client.put(f"/orders/{order_id}/status", headers=_auth(user or env.driver), json={"order_status": status, **body})


def _stock(env) -> tuple[int, int]:
    env.db.expire_all()
    inv = env.db.query(Inventory).filter(Inventory.product_id == env.product.id, Inventory.stock_status == "available").first()
    return inv.quantity, inv.reserved_quantity


def _pending_stock(env) -> int:
    env.db.expire_all()
    rows = env.db.query(Inventory).filter(Inventory.product_id == env.product.id, Inventory.stock_status == "pending").all()
    return sum(r.quantity for r in rows)


def _fail_after_pickup(env, **body) -> dict:
    order = _order(env)
    assert _status(env, order["id"], "picked_up").status_code == 200
    assert _status(env, order["id"], "in_transit").status_code == 200
    res = _status(env, order["id"], "failed", failure_reason="recipient_absent", note="کسی نبود", **body)
    assert res.status_code == 200, res.text
    return res.json()


def _receive_all(env, order_id):
    from app.services.field_service import list_returns, receive_return
    from app.schemas.field import ReceiveReturnIn
    env.db.expire_all()
    for row in list_returns(env.db, env.admin, order_id):
        if row["status"] == "open":
            lines = [{"product_id": line["product_id"], "received_quantity": line["expected_quantity"]} for line in row["lines"]]
            receive_return(env.db, env.admin, order_id, row["id"], ReceiveReturnIn(lines=lines))


def _resolve(env, order_id, user=None, **body):
    return env.client.post(f"/orders/{order_id}/resolve-failure", headers=_auth(user or env.admin), json=body)


# ---------------------------------------------------------------------------
# ماشین وضعیت تحویل ناموفق
# ---------------------------------------------------------------------------
def test_failed_delivery_waits_for_a_decision_and_keeps_stock_out(env):
    order = _fail_after_pickup(env)
    assert order["failure_resolution"] is None and order["delivery_attempt_count"] == 1
    assert _stock(env) == (95, 0) and _pending_stock(env) == 0        # کالا نزد راننده است، هنوز برگشت نخورده
    [attempt] = env.client.get(f"/orders/{order['id']}/attempts", headers=_auth(env.admin)).json()
    assert attempt["failure_reason"] == "recipient_absent" and attempt["failure_reason_label"] == "گیرنده در دسترس نبود"
    listed = env.client.get("/orders/", headers=_auth(env.admin), params={"view": "awaiting_resolution"}).json()
    assert [o["id"] for o in listed] == [order["id"]]


def test_return_to_warehouse_restocks_exactly_once_and_is_final(env):
    order = _fail_after_pickup(env)
    res = _resolve(env, order["id"], resolution="return_to_warehouse")
    assert res.status_code == 200 and res.json()["failure_resolution"] == "return_to_warehouse"
    _receive_all(env, order["id"])
    assert _pending_stock(env) == 5
    assert _resolve(env, order["id"], resolution="return_to_warehouse").status_code == 400
    assert _resolve(env, order["id"], resolution="redeliver", **_window()).status_code == 400
    assert _pending_stock(env) == 5


def test_failure_before_pickup_keeps_reservation_until_return(env):
    order = _order(env)
    assert _status(env, order["id"], "failed").status_code == 200
    assert _stock(env) == (100, 5)
    assert _resolve(env, order["id"], resolution="return_to_warehouse").status_code == 200
    assert _stock(env) == (100, 0)


def test_redelivery_does_not_issue_stock_twice_and_settles_on_delivery(env):
    order = _fail_after_pickup(env)
    res = _resolve(env, order["id"], resolution="redeliver", note="مشتری فردا هست", **_window(2))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "assigned" and body["failure_resolution"] == "redeliver" and body["vehicle_id"] == env.vehicle.id
    assert _stock(env) == (95, 0)
    assert _status(env, order["id"], "picked_up").status_code == 200
    assert _stock(env) == (95, 0)                                     # حواله دوباره زده نشد
    assert _status(env, order["id"], "in_transit").status_code == 200
    done = _status(env, order["id"], "delivered", recipient_name="مریم", recipient_role="self").json()
    assert done["status"] == "delivered" and done["delivered_at"] and done["delivery_attempt_count"] == 2
    attempts = env.client.get(f"/orders/{order['id']}/attempts", headers=_auth(env.admin)).json()
    assert [(a["outcome"], a["resolution"]) for a in attempts] == [("failed", "redeliver"), ("delivered", None)]
    assert attempts[1]["recipient_role_label"] == "خود گیرنده"
    # پس از ارسال دوباره، کالا تحویل شد و برگشت ندارد
    assert _pending_stock(env) == 0


def test_second_failure_needs_a_new_decision(env):
    order = _fail_after_pickup(env)
    assert _resolve(env, order["id"], resolution="redeliver", **_window(2)).status_code == 200
    again = _status(env, order["id"], "failed", failure_reason="refused").json()
    assert again["failure_resolution"] is None and again["delivery_attempt_count"] == 2
    assert _resolve(env, order["id"], resolution="return_to_warehouse").status_code == 200
    _receive_all(env, order["id"])
    assert _pending_stock(env) == 5


def test_dispute_opens_linked_ticket_without_moving_stock_then_can_be_resolved(env):
    order = _fail_after_pickup(env)
    res = _resolve(env, order["id"], resolution="dispute", note="مشتری می‌گوید کسی نیامد")
    assert res.status_code == 200 and res.json()["failure_resolution"] == "dispute"
    env.db.expire_all()
    ticket = env.db.query(Ticket).filter(Ticket.order_id == order["id"]).one()
    assert ticket.waiting_on == "org" and ticket.access_token is None
    assert _pending_stock(env) == 0
    assert _resolve(env, order["id"], resolution="dispute").status_code == 400
    listed = env.client.get("/orders/", headers=_auth(env.admin), params={"view": "awaiting_resolution"}).json()
    assert [o["id"] for o in listed] == [order["id"]]
    assert _resolve(env, order["id"], resolution="return_to_warehouse").status_code == 200
    _receive_all(env, order["id"])
    assert _pending_stock(env) == 5


def test_resolution_permissions(env):
    order = _fail_after_pickup(env)
    assert _resolve(env, order["id"], env.driver, resolution="return_to_warehouse").status_code == 403
    assert _resolve(env, order["id"], env.manager, resolution="dispute").status_code == 403
    assert _resolve(env, order["id"], env.manager, resolution="redeliver", **_window()).status_code == 403
    assert _resolve(env, order["id"], env.manager, resolution="return_to_warehouse").status_code == 200


def test_redelivery_needs_a_window_in_the_future(env):
    order = _fail_after_pickup(env)
    assert _resolve(env, order["id"], resolution="redeliver").status_code == 422
    assert _resolve(env, order["id"], resolution="redeliver", **_window(-20, 2)).status_code == 400


def test_legacy_failed_order_is_not_awaiting_a_decision(env):
    order = _order(env)
    env.db.query(Order).filter(Order.id == order["id"]).update({"status": "failed", "failure_resolution": "legacy"})
    env.db.commit()
    assert env.client.get("/orders/", headers=_auth(env.admin), params={"view": "awaiting_resolution"}).json() == []
    assert _resolve(env, order["id"], resolution="return_to_warehouse").status_code == 400


def test_failure_detaches_order_from_open_shipment(env):
    order = _order(env)
    env.db.add(Package(organization_id=env.org.id, code="P-1", order_id=order["id"], sequence=1, length_cm=10, width_cm=10, height_cm=10,
                       weight_kg=5, created_at=_now()))
    env.db.query(Order).filter(Order.id == order["id"]).update({"fulfillment_state": "packed"})
    env.db.commit()
    shipment = env.client.post("/shipping/shipments", headers=_auth(env.admin), json={
        "warehouse_id": env.warehouse.id, "vehicle_id": env.vehicle.id, "order_ids": [order["id"]]})
    assert shipment.status_code == 201, shipment.text
    assert _status(env, order["id"], "failed").status_code == 200
    env.db.expire_all()
    assert env.db.get(Order, order["id"]).shipment_id is None
    assert env.client.post(f"/shipping/shipments/{shipment.json()['id']}/dispatch", headers=_auth(env.admin), json={}).status_code == 400


def test_tracking_page_is_public_text_only(env):
    order = _fail_after_pickup(env)
    code = order["tracking_code"]
    assert "فروشنده با شما تماس" in env.client.get(f"/public/track/{code}").json()["status_text"]
    assert _resolve(env, order["id"], resolution="redeliver", **_window(2)).status_code == 200
    public = env.client.get(f"/public/track/{code}")
    assert "تلاش دوباره" in public.json()["status_text"]
    assert "کسی نبود" not in public.text and "recipient_absent" not in public.text
    assert _status(env, order["id"], "failed", failure_reason="refused").status_code == 200
    assert _resolve(env, order["id"], resolution="return_to_warehouse").status_code == 200
    assert "برگشت" in env.client.get(f"/public/track/{code}").json()["status_text"]


# ---------------------------------------------------------------------------
# عکس مدرک
# ---------------------------------------------------------------------------
def test_delivery_photo_access_and_audit(env, tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.storage.MEDIA_ROOT", tmp_path)
    order = _order(env)
    assert _status(env, order["id"], "picked_up").status_code == 200
    assert _status(env, order["id"], "in_transit").status_code == 200
    assert _status(env, order["id"], "delivered", recipient_name="نگهبان", recipient_role="guard", exception_note="یک کارتن خیس بود").status_code == 200
    url = f"/orders/{order['id']}/attempts/1/photo"

    bad = env.client.post(url, headers=_auth(env.driver), files={"file": ("a.txt", b"not an image", "text/plain")})
    assert bad.status_code == 400
    assert env.client.post(url, headers=_auth(env.manager), files={"file": ("a.png", PNG, "image/png")}).status_code == 403
    assert env.client.post(url, headers=_auth(env.rival), files={"file": ("a.png", PNG, "image/png")}).status_code == 404
    up = env.client.post(url, headers=_auth(env.driver), params={"photo_type": "door"}, files={"file": ("a.png", PNG, "image/png")})
    assert up.status_code == 200 and up.json()["has_photo"] and up.json()["photo_type"] == "door"

    assert env.client.get(url, headers=_auth(env.rival)).status_code == 404
    assert env.client.get(url, headers=_auth(env.driver)).status_code == 200
    env.db.expire_all()
    assert env.db.query(AuditLog).filter(AuditLog.action == "order.delivery_photo_view").count() == 0
    seen = env.client.get(url, headers=_auth(env.admin))
    assert seen.status_code == 200 and seen.content == PNG
    env.db.expire_all()
    assert env.db.query(AuditLog).filter(AuditLog.action == "order.delivery_photo_view").count() == 1
    assert env.client.get(url).status_code == 401
    # کد رهگیری چیزی از مدرک لو نمی‌دهد
    public = env.client.get(f"/public/track/{order['tracking_code']}").text
    assert "نگهبان" not in public and "خیس" not in public


def test_driver_sees_only_his_attempts(env):
    order = _fail_after_pickup(env)
    assert len(env.client.get(f"/orders/{order['id']}/attempts", headers=_auth(env.driver)).json()) == 1
    assert env.client.get(f"/orders/{order['id']}/attempts", headers=_auth(env.rival)).json() == []


# ---------------------------------------------------------------------------
# ظرفیت
# ---------------------------------------------------------------------------
def test_capacity_rule_is_shared_by_suggestions_and_shipments(env):
    # سقف وزن واقعی کمتر از ظرفیت اسمی است؛ پیشنهاد و محموله باید یکسان رفتار کنند
    env.vehicle.max_weight_kg = 20
    env.db.commit()
    res = env.client.post("/dispatch/suggest", headers=_auth(env.admin), json={
        "total_weight_kg": 30, "destination_city": "تهران", "destination_province": "تهران", **_window()})
    assert res.status_code == 200, res.text
    [excluded] = res.json()["excluded"]
    assert "۲۰" in excluded["reason"] and not res.json()["candidates"]


def test_volume_limit_excludes_vehicle_when_dimensions_are_known(env):
    env.vehicle.max_volume_m3 = 0.1
    env.product.length_cm, env.product.width_cm, env.product.height_cm = 100, 100, 100
    env.db.commit()
    assert capacity_service.items_volume(env.db, {env.product.id: 1}) == 1
    order = env.client.post("/orders/", headers=_auth(env.admin), json={
        "items": [{"product_id": env.product.id, "quantity": 1}], "customer": {"name": "مریم احمدی", "mobile": "09121112233"},
        "destination_province": "تهران", "destination_city": "تهران", "destination_address": "خیابان آزادی پلاک ۱",
        "size": "m", "auto_assign": False, "warehouse_id": env.warehouse.id, **_window(),
    }).json()
    sug = env.client.get(f"/dispatch/orders/{order['id']}/suggestions", headers=_auth(env.admin)).json()
    assert not sug["candidates"] and "حجمی" in sug["excluded"][0]["reason"]


def test_unknown_dimensions_fall_back_to_weight_only(env):
    assert capacity_service.items_volume(env.db, {env.product.id: 3}) is None
    assert capacity_service.check(SimpleNamespace(max_weight_kg=None, capacity_kg=10, max_volume_m3=1), 5).ok


def test_shipment_preview_reports_usage_and_overloading_orders(env):
    ids = []
    for _ in range(2):
        order = _order(env, quantity=1)
        env.db.add(Package(organization_id=env.org.id, code=f"P-{order['id']}", order_id=order["id"], sequence=1,
                           length_cm=100, width_cm=100, height_cm=100, weight_kg=60, created_at=_now()))
        ids.append(order["id"])
    env.vehicle.max_weight_kg = 100
    env.vehicle.max_volume_m3 = 10
    env.db.commit()
    body = {"warehouse_id": env.warehouse.id, "vehicle_id": env.vehicle.id, "order_ids": ids}
    res = env.client.post("/shipping/shipments/preview", headers=_auth(env.admin), json=body)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["weight_pct"] == 120 and data["volume_pct"] == 20 and data["ok"] is False
    assert [o["id"] for o in data["over_orders"]] == [ids[1]] and "وزنی" in data["message"]
    # همان پیام هنگام ساخت محموله
    assert env.client.post("/shipping/shipments", headers=_auth(env.admin), json=body).status_code == 400
    fit = env.client.post("/shipping/shipments/preview", headers=_auth(env.admin), json={**body, "order_ids": ids[:1]}).json()
    assert fit["ok"] is True and fit["weight_pct"] == 60 and fit["over_orders"] == []
    assert env.client.post("/shipping/shipments/preview", headers=_auth(env.driver), json=body).status_code in (403, 404)


# ---------------------------------------------------------------------------
# برآورد رسیدن
# ---------------------------------------------------------------------------
def _eta_order(status="assigned", start=1, end=2, route_km=500, **extra) -> SimpleNamespace:
    now = _now()
    return SimpleNamespace(id=1, status=status, delivery_window_start=now + timedelta(hours=start), delivery_window_end=now + timedelta(hours=end),
                           route={"total_km": route_km, "points": [{"km": 0}, {"km": route_km}]}, **extra)


def test_eta_flags_orders_that_cannot_make_the_window():
    risky = eta_service.estimate(None, _eta_order(route_km=2000), now=_now())
    assert risky["at_risk"] and risky["label"] == "برآورد برنامه‌ای" and "طول بازه" in risky["reason"]
    safe = eta_service.estimate(None, _eta_order(route_km=10), now=_now())
    assert not safe["at_risk"] and safe["reason"] is None
    late_start = eta_service.estimate(None, _eta_order(start=-2, end=1, route_km=2000), now=_now())
    assert late_start["at_risk"] and "شروع بازه گذشته" in late_start["reason"]
    assert eta_service.estimate(None, _eta_order(status="delivered"), now=_now()) is None


def test_at_risk_view_matches_timeline_and_action_center(env):
    order = _order(env)
    env.db.query(Order).filter(Order.id == order["id"]).update({
        "delivery_window_end": _now() + timedelta(minutes=30),
        "route": {"total_km": 5000, "warehouse_name": "x", "points": [
            {"seq": i, "city": "تهران", "province": "تهران", "lat": 35.7, "lon": 51.4, "km": km, "label": "تهران", "approx": False}
            for i, km in enumerate((0, 5000))]}})
    env.db.commit()
    listed = env.client.get("/orders/", headers=_auth(env.admin), params={"view": "at_risk"}).json()
    assert [o["id"] for o in listed] == [order["id"]]
    timeline = env.client.get(f"/orders/{order['id']}/timeline", headers=_auth(env.admin)).json()
    assert timeline["eta"]["at_risk"] and "در خطر تأخیر" in timeline["blocker"]
    card = next(c for c in env.client.get("/action-center", headers=_auth(env.admin)).json()["cards"] if c["key"] == "orders_at_risk")
    assert card["count"] == 1 and "at_risk" in card["link"]
    assert "eta" not in env.client.get(f"/public/track/{order['tracking_code']}").json()


# ---------------------------------------------------------------------------
# مرکز استثنا
# ---------------------------------------------------------------------------
def _scan(env):
    return env.client.post("/exceptions/scan", headers=_auth(env.admin))


def _make_failed_old(env) -> dict:
    order = _fail_after_pickup(env)
    env.db.query(Order).filter(Order.id == order["id"]).update({"updated_at": _now() - timedelta(hours=3)})
    env.db.commit()
    return order


def test_exception_is_opened_once_and_closes_itself(env):
    order = _make_failed_old(env)
    first = _scan(env).json()
    assert first["created"] >= 1
    items = env.client.get("/exceptions/", headers=_auth(env.admin)).json()
    item = next(i for i in items if i["kind"] == "order_failed_unresolved")
    assert item["entity_id"] == order["id"] and item["team"] == "fleet" and item["severity"] == "high"
    assert item["link"] == f"/app/orders?order={order['id']}" and item["suggested_owner"]["id"] == env.admin.id

    again = _scan(env).json()
    assert again["created"] == 0                                       # مورد باز تکراری ساخته نمی‌شود
    assert _resolve(env, order["id"], resolution="return_to_warehouse").status_code == 200
    assert _scan(env).json()["closed"] >= 1
    env.db.expire_all()
    closed = env.db.get(OperationException, item["id"])
    assert closed.status == "resolved" and closed.resolved_by_id is None and "خودکار" in closed.resolution
    detail = env.client.get(f"/exceptions/{item['id']}", headers=_auth(env.admin)).json()
    assert [e["action"] for e in detail["events"]] == ["ثبت خودکار", "حل‌شده (سیستم)"]


def test_human_decision_is_not_overridden_by_detection(env):
    _make_failed_old(env)
    _scan(env)
    item = next(i for i in env.client.get("/exceptions/", headers=_auth(env.admin)).json() if i["kind"] == "order_failed_unresolved")
    url = f"/exceptions/{item['id']}"
    assert env.client.patch(url, headers=_auth(env.admin), json={"status": "resolved"}).status_code == 400
    res = env.client.patch(url, headers=_auth(env.admin), json={"owner_id": env.manager.id, "status": "in_progress", "note": "پیگیری شد"})
    assert res.status_code == 200 and res.json()["owner_name"] == "مدیر انبار" and res.json()["status"] == "in_progress"
    assert env.client.patch(url, headers=_auth(env.admin), json={"owner_id": env.driver.id}).status_code == 400
    assert env.client.patch(url, headers=_auth(env.admin), json={"status": "resolved", "resolution": "با مشتری صحبت شد"}).status_code == 200
    _scan(env)
    assert not [i for i in env.client.get("/exceptions/", headers=_auth(env.admin)).json() if i["kind"] == "order_failed_unresolved"]
    assert env.client.patch(url, headers=_auth(env.admin), json={"note": "دوباره"}).status_code == 400


def test_exception_merge_and_scope(env):
    _make_failed_old(env)
    _make_failed_old(env)
    _scan(env)
    a, b = [i for i in env.client.get("/exceptions/", headers=_auth(env.admin)).json() if i["kind"] == "order_failed_unresolved"][:2]
    assert env.client.patch(f"/exceptions/{a['id']}", headers=_auth(env.admin), json={"merged_into_id": a["id"]}).status_code == 400
    merged = env.client.patch(f"/exceptions/{a['id']}", headers=_auth(env.admin), json={"merged_into_id": b["id"]}).json()
    assert merged["status"] == "merged" and merged["merged_into_id"] == b["id"]

    # مدیر انبار دیگر چیزی از این انبار نمی‌بیند
    assert env.client.get("/exceptions/", headers=_auth(env.manager)).json()
    env.manager.warehouse_id = None
    env.db.commit()
    assert env.client.get("/exceptions/", headers=_auth(env.manager)).json() == []
    assert env.client.get(f"/exceptions/{b['id']}", headers=_auth(env.manager)).status_code == 404
    assert env.client.get("/exceptions/", headers=_auth(env.driver)).status_code == 403


def test_detection_covers_data_driven_kinds(env):
    order = _order(env)
    env.db.query(Order).filter(Order.id == order["id"]).update({"status": "assigned"})
    env.driver.is_active = False
    env.db.add(Backorder(organization_id=env.org.id, order_id=order["id"], product_id=env.product.id, warehouse_id=env.warehouse.id, quantity=2,
                         status="open", due_at=_now(), created_at=_now() - timedelta(hours=30)))
    env.db.add(Ticket(organization_id=env.org.id, code="TK-ESC", subject="s", category="other", source="customer", handler="platform", status="open",
                      waiting_on="platform", escalated_at=_now() - timedelta(hours=10), last_activity_at=_now() - timedelta(hours=10)))
    env.db.commit()
    assert exception_service.detect(env.db, env.org.id)["created"] >= 3
    kinds = {i["kind"] for i in env.client.get("/exceptions/", headers=_auth(env.admin)).json()}
    assert {"driver_ineligible", "backorder_open", "ticket_escalated_waiting"} <= kinds
    notes = env.db.query(Notification).filter(Notification.kind == "exception_opened").all()
    assert len(notes) == len({n.warehouse_id for n in notes})          # یک اعلان خلاصه برای هر انبار


def test_exception_card_and_timeline(env):
    order = _make_failed_old(env)
    _scan(env)
    card = next(c for c in env.client.get("/action-center", headers=_auth(env.admin)).json()["cards"] if c["key"] == "exceptions_urgent")
    assert card["count"] == len(env.client.get("/exceptions/", headers=_auth(env.admin), params={"urgent": True}).json())
    events = env.client.get(f"/orders/{order['id']}/timeline", headers=_auth(env.admin)).json()["events"]
    assert {"attempt", "exception"} <= {e["source"] for e in events}
    driver_events = env.client.get(f"/orders/{order['id']}/timeline", headers=_auth(env.driver)).json()["events"]
    assert "exception" not in {e["source"] for e in driver_events}


# ---------------------------------------------------------------------------
# تأمین مجدد رویدادی و اعلان
# ---------------------------------------------------------------------------
def _replenishment_site(env):
    bulk = Location(warehouse_id=env.warehouse.id, code="BULK-1", barcode="LOC-B1", name="نگهداری", location_type="storage")
    pick = Location(warehouse_id=env.warehouse.id, code="PICK-1", barcode="LOC-P1", name="برداشت", location_type="picking")
    env.db.add_all([bulk, pick])
    env.db.commit()
    env.db.add(ReplenishmentRule(organization_id=env.org.id, warehouse_id=env.warehouse.id, location_id=pick.id, product_id=env.product.id,
                                 min_quantity=5, max_quantity=20, is_active=True))
    env.db.commit()
    return pick


def test_backorder_and_released_reservation_trigger_replenishment_check(env, monkeypatch):
    from app.services import backorder_service, replenishment_rule_service
    pick = _replenishment_site(env)
    calls = []
    monkeypatch.setattr(replenishment_rule_service, "check", lambda db, user, ids: calls.append(set(ids)) or 0)
    created = _order(env)
    assert calls == []
    backorder_service.open_backorder(env.db, env.admin, env.db.get(Order, created["id"]), env.product, 2, 1000)
    env.db.commit()
    assert calls == [{pick.id}]
    assert _status(env, created["id"], "canceled", env.admin).status_code == 200
    assert len(calls) >= 2 and calls[1] == {pick.id}
    assert _stock(env)[0] == 100                                       # موجودی قطعی تغییر نکرد


def test_replenishment_failure_never_breaks_the_operation(env, monkeypatch):
    from app.services import replenishment_rule_service
    from app.services.exceptions import ConflictError
    _replenishment_site(env)

    def boom(*a, **k):
        raise ConflictError("محل مقصد پر است")
    monkeypatch.setattr(replenishment_rule_service, "check", boom)
    order = _order(env)
    assert _status(env, order["id"], "canceled", env.admin).status_code == 200
    assert _stock(env) == (100, 0)


def test_repeat_order_events_refresh_one_notification(env):
    order = _fail_after_pickup(env)
    assert _resolve(env, order["id"], resolution="redeliver", **_window(2)).status_code == 200
    assert _status(env, order["id"], "failed").status_code == 200
    env.db.expire_all()
    rows = env.db.query(Notification).filter(Notification.kind == "order_failed").all()
    assert len(rows) == 1 and rows[0].dedupe_key == f"order:{order['id']}:failed"
    assert env.db.query(Notification).filter(Notification.kind == "order_assigned").count() == 1


def test_ticket_detail_suggests_least_loaded_staff(env):
    order = _order(env)
    busy = Ticket(organization_id=env.org.id, code="TK-BUSY", subject="s", category="other", source="customer", handler="org", status="open",
                  waiting_on="org", assignee_id=env.admin.id, last_activity_at=_now())
    fresh = Ticket(organization_id=env.org.id, code="TK-FRESH", subject="s", category="other", source="customer", handler="org", status="open",
                   waiting_on="org", order_id=order["id"], last_activity_at=_now())
    env.db.add_all([busy, fresh])
    env.db.commit()
    detail = env.client.get(f"/tickets/{fresh.id}", headers=_auth(env.admin)).json()
    assert detail["suggested_assignee"] == {"id": env.manager.id, "name": "مدیر انبار", "open_count": 0}
    env.db.expire_all()
    assert env.db.get(Ticket, fresh.id).assignee_id is None            # فقط پیشنهاد است


# ---------------------------------------------------------------------------
# بودجه کوئری (C1)
# ---------------------------------------------------------------------------
@pytest.fixture()
def count_queries(env):
    engine = env.db.get_bind()
    state = {"count": 0}

    def counter(conn, cursor, statement, parameters, context, executemany):
        state["count"] += 1
    event.listen(engine, "before_cursor_execute", counter)
    yield state
    event.remove(engine, "before_cursor_execute", counter)


def _measure(env, state, method, url, **kwargs) -> int:
    state["count"] = 0
    res = getattr(env.client, method)(url, headers=_auth(env.admin), **kwargs)
    assert res.status_code == 200, res.text
    return state["count"]


@pytest.mark.parametrize("url,budget", [
    ("/action-center", 140), ("/search?q=RICE", 35), ("/orders/", 20), ("/exceptions/", 15),
])
def test_endpoint_query_budget(env, count_queries, url, budget):
    for _ in range(3):
        _make_failed_old(env)
    _scan(env)
    used = _measure(env, count_queries, "get", url)
    assert used <= budget, f"{url}: {used} queries"


def test_timeline_query_budget(env, count_queries):
    order = _make_failed_old(env)
    used = _measure(env, count_queries, "get", f"/orders/{order['id']}/timeline")
    assert used <= 40, f"{used} queries"


def test_orders_list_has_no_n_plus_one(env, count_queries):
    _order(env, quantity=1)
    small = _measure(env, count_queries, "get", "/orders/")
    for _ in range(5):
        _order(env, quantity=1)
    assert _measure(env, count_queries, "get", "/orders/") == small


def test_attempt_row_only_for_delivery_outcomes(env):
    order = _order(env)
    assert _status(env, order["id"], "picked_up").status_code == 200
    env.db.expire_all()
    assert env.db.query(DeliveryAttempt).filter(DeliveryAttempt.order_id == order["id"]).count() == 0
