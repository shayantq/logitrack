"""
مرحله ۲ راهنمای عملیات (docs/operations-guide.md): تحویل جزئی، برگشت از راننده، بستن سفر، تماس، قبول مأموریت،
مدرک منقضی، خودروی خارج از سرویس، تحویل بین رانندگان، مدرک الزامی و درخواست‌های مشتری.
"""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import DriverProfile, Inventory, Order, Organization, Product, RoleEnum, User, Vehicle
from app.models_fulfillment import Package, Shipment
from app.models_productivity import DriverReturn, OperationException
from app.services import exception_service, stock_ledger
from tests.factories import default_warehouse


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


def _window(hours=-1, length=8) -> dict:
    start = _now() + timedelta(hours=hours)
    return {"delivery_window_start": start.isoformat() + "Z", "delivery_window_end": (start + timedelta(hours=length)).isoformat() + "Z"}


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    org = Organization(name="فروشگاه آلفا", slug="alpha")
    other = Organization(name="فروشگاه بتا", slug="beta")
    db.add_all([org, other])
    db.commit()
    set_tenant(db, org.id)
    warehouse = default_warehouse(db, org.id)
    admin = User(username="adm", email="a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x", full_name="ادمین")
    manager = User(username="wm", email="m@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password="x", warehouse_id=warehouse.id)
    driver = User(username="drv", email="d@x.io", role=RoleEnum.DRIVER, hashed_password="x", full_name="علی", driver_code="D1", driver_status="approved")
    rival = User(username="drv2", email="d2@x.io", role=RoleEnum.DRIVER, hashed_password="x", full_name="رضا", driver_code="D2", driver_status="approved")
    db.add_all([admin, manager, driver, rival])
    db.commit()
    vehicle = Vehicle(license_plate="11الف111-11", type="van", capacity_kg=1000, driver_id=driver.id, status="available")
    spare = Vehicle(license_plate="22ب222-22", type="van", capacity_kg=1000, driver_id=rival.id, status="available")
    rice = Product(name="برنج", sku="RICE-1", barcode="62600001", price=1000, weight_kg=1)
    oil = Product(name="روغن", sku="OIL-1", barcode="62600002", price=1000, weight_kg=1)
    db.add_all([vehicle, spare, rice, oil])
    db.commit()
    for product in (rice, oil):
        inventory = stock_ledger.lock_bucket(db, product.id, warehouse.id, "available", organization_id=org.id)
        document = stock_ledger.new_document(db, "receipt", organization_id=org.id, warehouse_id=warehouse.id, note="اولیه")
        stock_ledger.record(db, inventory, 100, "receipt", document=document, reason="اولیه")
    db.commit()
    set_tenant(db, other.id)
    outsider = User(username="out", email="o@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    db.add(outsider)
    db.commit()
    set_tenant(db, org.id)
    yield SimpleNamespace(client=client, db=db, org=org, warehouse=warehouse, admin=admin, manager=manager, driver=driver, rival=rival,
                          vehicle=vehicle, spare=spare, rice=rice, oil=oil, outsider=outsider)
    db.close()


def _order(env, rice=5, oil=None, vehicle=True, mobile="09121112233", **extra) -> dict:
    items = [{"product_id": env.rice.id, "quantity": rice}]
    if oil:
        items.append({"product_id": env.oil.id, "quantity": oil})
    body = {"items": items, "customer": {"name": "مریم احمدی", "mobile": mobile}, "destination_province": "تهران", "destination_city": "تهران",
            "destination_address": "خیابان آزادی پلاک ۱", "size": "m", "warehouse_id": env.warehouse.id, **_window(), **extra}
    if vehicle:
        body["vehicle_id"] = env.vehicle.id
    else:
        body["auto_assign"] = False
    res = env.client.post("/orders/", headers=_auth(env.admin), json=body)
    assert res.status_code == 201, res.text
    return res.json()


def _status(env, order_id, status, user=None, **body):
    return env.client.put(f"/orders/{order_id}/status", headers=_auth(user or env.driver), json={"order_status": status, **body})


def _on_road(env, order) -> None:
    assert _status(env, order["id"], "picked_up").status_code == 200
    assert _status(env, order["id"], "in_transit").status_code == 200


def _stock(env, product, status="available") -> int:
    env.db.expire_all()
    rows = env.db.query(Inventory).filter(Inventory.product_id == product.id, Inventory.stock_status == status).all()
    return sum(r.quantity for r in rows)


def _returns(env, order_id, user=None) -> list:
    res = env.client.get(f"/orders/{order_id}/driver-returns", headers=_auth(user or env.admin))
    assert res.status_code == 200, res.text
    return res.json()


def _receive(env, order_id, return_id, lines, user=None):
    return env.client.post(f"/orders/{order_id}/driver-returns/{return_id}/receive", headers=_auth(user or env.admin), json={"lines": lines})


# ---------------------------------------------------------------------------
# تحویل جزئی و برگشت
# ---------------------------------------------------------------------------
def test_partial_delivery_records_each_line_and_waits_for_the_return(env):
    order = _order(env, rice=5, oil=2)
    _on_road(env, order)
    rice_item = next(i for i in order["items"] if i["product_id"] == env.rice.id)
    res = _status(env, order["id"], "delivered", recipient_name="مریم", recipient_role="self",
                  delivery_lines=[{"item_id": rice_item["id"], "delivered_quantity": 3, "reason": "دو عدد خیس بود"}])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "delivered" and body["delivered_at"] and body["commission_amount"] is not None   # تسویه عوض نمی‌شود
    [attempt] = env.client.get(f"/orders/{order['id']}/attempts", headers=_auth(env.admin)).json()
    assert attempt["partial"] and {(x["product_name"], x["delivered_quantity"], x["returned_quantity"]) for x in attempt["lines"]} == {("برنج", 3, 2), ("روغن", 2, 0)}
    [ret] = _returns(env, order["id"])
    assert ret["status"] == "open" and [(x["product_id"], x["expected_quantity"]) for x in ret["lines"]] == [(env.rice.id, 2)]
    assert _stock(env, env.rice, "pending") == 0                           # هنوز به انبار نرسیده

    assert _receive(env, order["id"], ret["id"], [{"product_id": env.rice.id, "received_quantity": 2}]).status_code == 200
    assert _stock(env, env.rice, "pending") == 2 and _stock(env, env.rice) == 95
    assert _receive(env, order["id"], ret["id"], [{"product_id": env.rice.id, "received_quantity": 2}]).status_code == 400   # دوبار ثبت نمی‌شود
    assert _stock(env, env.rice, "pending") == 2
    public = env.client.get(f"/public/track/{order['tracking_code']}").json()
    assert "بخشی از سفارش" in public["status_text"] and "خیس" not in str(public)


def test_partial_with_nothing_delivered_is_rejected(env):
    order = _order(env, rice=2)
    _on_road(env, order)
    res = _status(env, order["id"], "delivered", delivery_lines=[{"item_id": order["items"][0]["id"], "delivered_quantity": 0, "reason": "رد شد"}])
    assert res.status_code == 400
    env.db.expire_all()
    assert env.db.get(Order, order["id"]).status == "in_transit"
    over = _status(env, order["id"], "delivered", delivery_lines=[{"item_id": order["items"][0]["id"], "delivered_quantity": 9, "reason": "زیاد"}])
    assert over.status_code == 400


def test_return_to_warehouse_waits_for_count_and_records_shortage(env):
    order = _order(env, rice=5)
    _on_road(env, order)
    assert _status(env, order["id"], "failed", failure_reason="refused").status_code == 200
    res = env.client.post(f"/orders/{order['id']}/resolve-failure", headers=_auth(env.admin), json={"resolution": "return_to_warehouse"})
    assert res.status_code == 200 and res.json()["stock_state"] == "returning"
    assert _stock(env, env.rice, "pending") == 0
    [ret] = _returns(env, order["id"])
    no_reason = _receive(env, order["id"], ret["id"], [{"product_id": env.rice.id, "received_quantity": 4}], env.manager)
    assert no_reason.status_code == 400
    over = _receive(env, order["id"], ret["id"], [{"product_id": env.rice.id, "received_quantity": 6}])
    assert over.status_code == 400
    ok = _receive(env, order["id"], ret["id"], [{"product_id": env.rice.id, "received_quantity": 4, "shortage_reason": "یک عدد گم شد"}], env.manager)
    assert ok.status_code == 200
    assert _stock(env, env.rice, "pending") == 4
    env.db.expire_all()
    assert env.db.get(Order, order["id"]).stock_state == "returned"
    [item] = env.db.query(OperationException).filter(OperationException.kind == "return_shortage").all()
    assert item.status == "open"
    exception_service.detect(env.db, env.org.id)
    env.db.expire_all()
    assert env.db.get(OperationException, item.id).status == "open"       # کار انسانی است و خودکار بسته نمی‌شود
    assert env.client.get(f"/orders/{order['id']}/driver-returns", headers=_auth(env.driver)).status_code == 403


def test_trip_cannot_close_with_open_order_or_return(env):
    order = _order(env, rice=1)
    env.db.add(Package(organization_id=env.org.id, code="P-1", order_id=order["id"], sequence=1, length_cm=10, width_cm=10, height_cm=10, weight_kg=1, created_at=_now()))
    env.db.query(Order).filter(Order.id == order["id"]).update({"fulfillment_state": "packed"})
    env.db.commit()
    shipment = env.client.post("/shipping/shipments", headers=_auth(env.admin), json={
        "warehouse_id": env.warehouse.id, "vehicle_id": env.vehicle.id, "order_ids": [order["id"]]}).json()
    assert env.client.post(f"/shipping/shipments/{shipment['id']}/dispatch", headers=_auth(env.admin), json={}).status_code == 200
    close = f"/shipping/shipments/{shipment['id']}/close"
    assert env.client.post(close, headers=_auth(env.admin)).status_code == 400          # سفارش هنوز در راه است
    assert _status(env, order["id"], "failed").status_code == 200
    assert env.client.post(close, headers=_auth(env.admin)).status_code == 400          # منتظر تصمیم است
    assert env.client.post(f"/orders/{order['id']}/resolve-failure", headers=_auth(env.admin), json={"resolution": "return_to_warehouse"}).status_code == 200
    blocked = env.client.post(close, headers=_auth(env.admin))
    assert blocked.status_code == 400 and "برگشت" in blocked.json()["detail"]
    [ret] = _returns(env, order["id"])
    assert _receive(env, order["id"], ret["id"], [{"product_id": env.rice.id, "received_quantity": 1}]).status_code == 200
    closed = env.client.post(close, headers=_auth(env.admin))
    assert closed.status_code == 200 and closed.json()["status"] == "closed"
    env.db.expire_all()
    assert env.db.get(Shipment, shipment["id"]).closed_at is not None


# ---------------------------------------------------------------------------
# تماس و مأموریت
# ---------------------------------------------------------------------------
def test_contact_attempts_are_logged_and_scoped(env):
    order = _order(env)
    url = f"/orders/{order['id']}/contacts"
    assert env.client.post(url, headers=_auth(env.rival), json={"outcome": "no_answer"}).status_code == 404
    res = env.client.post(url, headers=_auth(env.driver), json={"outcome": "no_answer", "note": "سه بار زنگ زدم"})
    assert res.status_code == 200 and res.json()["outcome_label"] == "پاسخ نداد"
    assert env.client.post(url, headers=_auth(env.driver), json={"outcome": "نامعتبر"}).status_code == 422
    assert len(env.client.get(url, headers=_auth(env.admin)).json()) == 1
    assert env.client.get(url, headers=_auth(env.outsider)).status_code == 404
    events = env.client.get(f"/orders/{order['id']}/timeline", headers=_auth(env.admin)).json()["events"]
    assert any(e["source"] == "contact" for e in events)


def _require_missions(env):
    res = env.client.put("/valuation/settings", headers=_auth(env.admin), json={"mission_accept_required": True, "mission_deadline_minutes": 15})
    assert res.status_code == 200, res.text


def test_missions_are_off_by_default(env):
    order = _order(env)
    assert order["assignment_state"] is None
    assert _status(env, order["id"], "picked_up").status_code == 200


def test_driver_must_answer_mission_when_required(env):
    _require_missions(env)
    order = _order(env)
    assert order["assignment_state"] == "pending" and order["assignment_deadline"]
    assert _status(env, order["id"], "picked_up").status_code == 400
    url = f"/orders/{order['id']}/mission"
    assert env.client.post(url, headers=_auth(env.rival), json={"accept": True}).status_code == 400
    res = env.client.post(url, headers=_auth(env.driver), json={"accept": True})
    assert res.status_code == 200 and res.json()["assignment_state"] == "accepted"
    assert env.client.post(url, headers=_auth(env.driver), json={"accept": True}).status_code == 400   # پاسخ دوباره اثری ندارد
    assert _status(env, order["id"], "picked_up").status_code == 200


def test_rejecting_mission_returns_order_to_the_queue(env):
    _require_missions(env)
    order = _order(env)
    url = f"/orders/{order['id']}/mission"
    assert env.client.post(url, headers=_auth(env.driver), json={"accept": False}).status_code == 400
    assert env.client.post(url, headers=_auth(env.driver), json={"accept": False, "reason": "خارج از شیفتم"}).status_code == 200
    env.db.expire_all()
    row = env.db.get(Order, order["id"])
    assert (row.status, row.vehicle_id, row.driver_id, row.assignment_state) == ("pending", None, None, None)
    assert _stock(env, env.rice) == 100 and env.db.query(Inventory).filter(Inventory.product_id == env.rice.id).first().reserved_quantity == 5


def test_unanswered_mission_becomes_an_exception(env):
    _require_missions(env)
    order = _order(env)
    env.db.query(Order).filter(Order.id == order["id"]).update({"assignment_deadline": _now() - timedelta(minutes=1)})
    env.db.commit()
    exception_service.detect(env.db, env.org.id)
    assert env.db.query(OperationException).filter(OperationException.kind == "mission_unanswered").count() == 1


# ---------------------------------------------------------------------------
# مدرک منقضی، خودروی خارج از سرویس، تحویل بین رانندگان
# ---------------------------------------------------------------------------
def test_expired_inspection_blocks_assignment(env):
    env.db.add(DriverProfile(organization_id=env.org.id, user_id=env.driver.id, inspection_expiry=date(2020, 1, 1)))
    env.db.commit()
    sug = env.client.post("/dispatch/suggest", headers=_auth(env.admin), json={"total_weight_kg": 5, "destination_city": "تهران", "destination_province": "تهران", **_window()}).json()
    blocked = next(e for e in sug["excluded"] if e["vehicle_id"] == env.vehicle.id)
    assert "معاینه فنی" in blocked["reason"]
    res = env.client.post("/orders/", headers=_auth(env.admin), json={
        "items": [{"product_id": env.rice.id, "quantity": 1}], "customer": {"name": "مریم احمدی", "mobile": "09121112233"},
        "destination_province": "تهران", "destination_city": "تهران", "destination_address": "خیابان آزادی پلاک ۱", "size": "m",
        "warehouse_id": env.warehouse.id, "vehicle_id": env.vehicle.id, **_window()})
    assert res.status_code == 400 and "معاینه" in res.json()["detail"]


def test_out_of_service_moves_unloaded_orders_and_flags_loaded_ones(env):
    waiting = _order(env, rice=1)
    loaded = _order(env, rice=1)
    assert _status(env, loaded["id"], "picked_up").status_code == 200
    url = f"/vehicles/{env.vehicle.id}/out-of-service"
    assert env.client.post(url, headers=_auth(env.rival), json={"reason": "خراب شد"}).status_code == 403
    res = env.client.post(url, headers=_auth(env.driver), json={"reason": "موتور خراب شد"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reassigned"] == [waiting["tracking_code"]] and body["handover_needed"] == [loaded["tracking_code"]]
    env.db.expire_all()
    assert env.db.get(Order, waiting["id"]).vehicle_id == env.spare.id and env.db.get(Order, loaded["id"]).vehicle_id == env.vehicle.id
    exception_service.detect(env.db, env.org.id)
    assert env.db.query(OperationException).filter(OperationException.kind == "vehicle_down_order").count() == 1


def test_out_of_service_without_a_substitute_leaves_order_pending(env):
    env.spare.status = "inactive"
    env.db.commit()
    order = _order(env, rice=1)
    res = env.client.post(f"/vehicles/{env.vehicle.id}/out-of-service", headers=_auth(env.admin), json={"reason": "تصادف کرد"})
    assert res.json()["unassigned"] == [order["tracking_code"]]
    env.db.expire_all()
    assert env.db.get(Order, order["id"]).status == "pending"


def test_handover_moves_the_order_only_after_target_driver_confirms(env):
    order = _order(env, rice=1)
    assert _status(env, order["id"], "picked_up").status_code == 200
    url = f"/orders/{order['id']}/handovers"
    assert env.client.post(url, headers=_auth(env.rival), json={"to_vehicle_id": env.spare.id}).status_code == 404
    assert env.client.post(url, headers=_auth(env.manager), json={"to_vehicle_id": env.spare.id}).status_code == 403
    res = env.client.post(url, headers=_auth(env.driver), json={"to_vehicle_id": env.spare.id, "note": "موتور خراب شد"})
    assert res.status_code == 200, res.text
    handover = res.json()
    assert env.client.post(url, headers=_auth(env.driver), json={"to_vehicle_id": env.spare.id}).status_code == 400
    env.db.expire_all()
    assert env.db.get(Order, order["id"]).vehicle_id == env.vehicle.id
    assert [h["id"] for h in env.client.get("/handovers/mine", headers=_auth(env.rival)).json()] == [handover["id"]]
    respond = f"/handovers/{handover['id']}/respond"
    assert env.client.post(respond, headers=_auth(env.driver), json={"accept": True}).status_code == 404
    assert env.client.post(respond, headers=_auth(env.rival), json={"accept": False}).status_code == 400
    assert env.client.post(respond, headers=_auth(env.rival), json={"accept": True, "note": "شمردم"}).status_code == 200
    assert env.client.post(respond, headers=_auth(env.rival), json={"accept": True}).status_code == 400
    env.db.expire_all()
    row = env.db.get(Order, order["id"])
    assert (row.vehicle_id, row.driver_id) == (env.spare.id, env.rival.id)
    assert _status(env, order["id"], "in_transit", env.rival).status_code == 200
    assert _status(env, order["id"], "delivered", env.driver).status_code == 403


def test_handover_rejected_for_unloaded_order_and_too_small_vehicle(env):
    order = _order(env, rice=5)
    url = f"/orders/{order['id']}/handovers"
    assert env.client.post(url, headers=_auth(env.admin), json={"to_vehicle_id": env.spare.id}).status_code == 400
    assert _status(env, order["id"], "picked_up").status_code == 200
    env.spare.capacity_kg = 1
    env.db.commit()
    assert env.client.post(url, headers=_auth(env.admin), json={"to_vehicle_id": env.spare.id}).status_code == 400


def test_proof_can_be_required_per_organization(env):
    order = _order(env)
    _on_road(env, order)
    assert env.client.put("/valuation/settings", headers=_auth(env.admin), json={"proof_required": True}).status_code == 200
    assert _status(env, order["id"], "delivered").status_code == 400
    assert _status(env, order["id"], "delivered", recipient_name="مریم", recipient_role="self").status_code == 200


# ---------------------------------------------------------------------------
# درخواست مشتری
# ---------------------------------------------------------------------------
def _ask(env, code, **body):
    return env.client.post(f"/public/track/{code}/requests", json={"phone": "2233", **body})


def _decide(env, request_id, user=None, **body):
    return env.client.post(f"/customer-requests/{request_id}/decide", headers=_auth(user or env.admin), json=body)


def test_public_request_needs_phone_and_changes_nothing_until_approved(env):
    order = _order(env)
    code = order["tracking_code"]
    assert _ask(env, code, kind="cancel", phone="0000").status_code == 403
    res = _ask(env, code, kind="cancel", note="پشیمان شدم")
    assert res.status_code == 200 and res.json()["status"] == "pending"
    assert _ask(env, code, kind="cancel").status_code == 400                    # تکراری
    env.db.expire_all()
    assert env.db.get(Order, order["id"]).status == "assigned"
    listed = env.client.get(f"/orders/{order['id']}/customer-requests", headers=_auth(env.admin)).json()
    assert listed[0]["note"] == "پشیمان شدم"
    assert env.client.get(f"/orders/{order['id']}/customer-requests", headers=_auth(env.driver)).status_code == 403
    assert env.client.get(f"/orders/{order['id']}/customer-requests", headers=_auth(env.outsider)).status_code == 404
    card = next(c for c in env.client.get("/action-center", headers=_auth(env.admin)).json()["cards"] if c["key"] == "customer_requests")
    assert card["count"] == 1

    assert _decide(env, res.json()["id"], approve=False).status_code == 400     # رد بدون دلیل
    assert _decide(env, res.json()["id"], approve=True, note="لغو شد").status_code == 200
    env.db.expire_all()
    assert env.db.get(Order, order["id"]).status == "canceled"
    assert _decide(env, res.json()["id"], approve=True).status_code == 400
    public = env.client.get(f"/public/track/{code}", params={"phone": "2233"}).json()
    assert public["details"]["requests"][0]["status"] == "approved"
    assert "پشیمان" not in str(env.client.get(f"/public/track/{code}").json())


def test_address_change_only_before_loading_and_validated(env):
    order = _order(env)
    code = order["tracking_code"]
    bad = _ask(env, code, kind="address_change", address={"destination_province": "تهران", "destination_city": "شهرناموجود", "destination_address": "نشانی تازه پلاک ۲"})
    assert bad.status_code == 422
    res = _ask(env, code, kind="address_change", address={"destination_province": "قزوین", "destination_city": "قزوین", "destination_address": "خیابان تازه پلاک ۲"})
    assert res.status_code == 200, res.text
    assert _status(env, order["id"], "picked_up").status_code == 200
    late = _decide(env, res.json()["id"], approve=True)
    assert late.status_code == 400                                              # سفارش بارگیری شد؛ تأیید دیر است
    env.db.expire_all()
    assert env.db.get(Order, order["id"]).destination_city == "تهران"


def test_address_change_applies_on_approval(env):
    order = _order(env)
    res = _ask(env, order["tracking_code"], kind="address_change", address={"destination_province": "قزوین", "destination_city": "قزوین", "destination_address": "خیابان تازه پلاک ۲"})
    assert _decide(env, res.json()["id"], approve=True).status_code == 200
    env.db.expire_all()
    row = env.db.get(Order, order["id"])
    assert (row.destination_city, row.destination_address) == ("قزوین", "خیابان تازه پلاک ۲")


def _deliver(env, order):
    _on_road(env, order)
    assert _status(env, order["id"], "delivered", recipient_name="مریم", recipient_role="self").status_code == 200


def test_return_request_creates_inbound_receipt_on_approval(env):
    order = _order(env, rice=3)
    code = order["tracking_code"]
    assert _ask(env, code, kind="return", items=[{"product_id": env.rice.id, "quantity": 1}]).status_code == 400   # هنوز تحویل نشده
    _deliver(env, order)
    assert _ask(env, code, kind="return", items=[{"product_id": env.rice.id, "quantity": 9}]).status_code == 400
    res = _ask(env, code, kind="return", items=[{"product_id": env.rice.id, "quantity": 1}], note="ناراضی‌ام")
    assert res.status_code == 200, res.text
    assert _decide(env, res.json()["id"], approve=True).status_code == 200
    receipts = env.client.get("/inbound/receipts", headers=_auth(env.admin), params={"status": "open"}).json()
    assert any(r.get("order_id") == order["id"] and r["receipt_type"] == "return" for r in receipts)


def test_dispute_keeps_delivery_evidence_and_is_tracked(env):
    order = _order(env)
    _deliver(env, order)
    res = _ask(env, order["tracking_code"], kind="dispute", note="کسی نیامد")
    assert res.status_code == 200
    exception_service.detect(env.db, env.org.id)
    assert env.db.query(OperationException).filter(OperationException.kind == "delivery_dispute", OperationException.status == "open").count() == 1
    assert _decide(env, res.json()["id"], approve=True, note="مدرک بررسی شد").status_code == 200
    env.db.expire_all()
    row = env.db.get(Order, order["id"])
    assert row.status == "delivered" and row.delivered_at is not None
    [attempt] = env.client.get(f"/orders/{order['id']}/attempts", headers=_auth(env.admin)).json()
    assert attempt["recipient_name"] == "مریم"
    exception_service.detect(env.db, env.org.id)
    env.db.expire_all()
    assert env.db.query(OperationException).filter(OperationException.kind == "delivery_dispute").one().status == "resolved"


def test_driver_return_view_card_matches_list(env):
    order = _order(env, rice=2)
    _on_road(env, order)
    assert _status(env, order["id"], "delivered", delivery_lines=[{"item_id": order["items"][0]["id"], "delivered_quantity": 1, "reason": "آسیب"}]).status_code == 200
    listed = env.client.get("/orders/", headers=_auth(env.admin), params={"view": "driver_returns"}).json()
    assert [o["id"] for o in listed] == [order["id"]]
    card = next(c for c in env.client.get("/action-center", headers=_auth(env.admin)).json()["cards"] if c["key"] == "driver_returns")
    assert card["count"] == 1
    assert env.db.query(DriverReturn).count() == 1
