"""
مرحله ۳ راهنمای عملیات (docs/operations-guide.md): حالت‌های تازه استثنا، تکرار و بازگشایی فقط با رویداد، یادآوری و
escalation، دید راننده و مشتری، مهلت پاسخ تیکت و تأیید دونفره اصلاح موجودی.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import Inventory, Organization, Product, RoleEnum, Ticket, User, Vehicle
from app.models_notification import Notification
from app.models_productivity import OperationException
from app.services import exception_service, stock_ledger
from tests.factories import default_warehouse


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    org = Organization(name="فروشگاه آلفا", slug="alpha")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    warehouse = default_warehouse(db, org.id)
    admin = User(username="adm", email="a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x", full_name="ادمین یک")
    admin2 = User(username="adm2", email="a2@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x", full_name="ادمین دو")
    manager = User(username="wm", email="m@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password="x", warehouse_id=warehouse.id, full_name="مدیر انبار")
    driver = User(username="drv", email="d@x.io", role=RoleEnum.DRIVER, hashed_password="x", full_name="علی", driver_code="D1", driver_status="approved")
    rival = User(username="drv2", email="d2@x.io", role=RoleEnum.DRIVER, hashed_password="x", full_name="رضا", driver_code="D2", driver_status="approved")
    db.add_all([admin, admin2, manager, driver, rival])
    db.commit()
    vehicle = Vehicle(license_plate="11الف111-11", type="van", capacity_kg=1000, driver_id=driver.id, status="available")
    product = Product(name="برنج", sku="RICE-1", barcode="62600001", price=1000, weight_kg=1)
    db.add_all([vehicle, product])
    db.commit()
    inventory = stock_ledger.lock_bucket(db, product.id, warehouse.id, "available", organization_id=org.id)
    document = stock_ledger.new_document(db, "receipt", organization_id=org.id, warehouse_id=warehouse.id, note="اولیه")
    stock_ledger.record(db, inventory, 100, "receipt", document=document, reason="اولیه")
    db.commit()
    yield SimpleNamespace(client=client, db=db, org=org, warehouse=warehouse, admin=admin, admin2=admin2, manager=manager, driver=driver, rival=rival,
                          vehicle=vehicle, product=product, inventory=inventory)
    db.close()


def _order(env) -> dict:
    start = _now() - timedelta(hours=1)
    res = env.client.post("/orders/", headers=_auth(env.admin), json={
        "items": [{"product_id": env.product.id, "quantity": 1}], "customer": {"name": "مریم احمدی", "mobile": "09121112233"},
        "destination_province": "تهران", "destination_city": "تهران", "destination_address": "خیابان آزادی پلاک ۱", "size": "m",
        "vehicle_id": env.vehicle.id, "warehouse_id": env.warehouse.id,
        "delivery_window_start": start.isoformat() + "Z", "delivery_window_end": (start + timedelta(hours=8)).isoformat() + "Z"})
    assert res.status_code == 201, res.text
    return res.json()


def _exception(env, **kw) -> OperationException:
    data = dict(organization_id=env.org.id, kind="backorder_open", entity_type="backorder", entity_id=1, warehouse_id=env.warehouse.id, severity="high",
                team="warehouse", status="open", opened_at=_now(), trigger_reason="دلیل آزمون", suggested_action="اقدام")
    data.update(kw)
    item = OperationException(**data)
    env.db.add(item)
    env.db.commit()
    return item


def _patch(env, item_id, user=None, **body):
    return env.client.patch(f"/exceptions/{item_id}", headers=_auth(user or env.admin), json=body)


def _notes(env, **filters):
    env.db.expire_all()
    query = env.db.query(Notification)
    for key, value in filters.items():
        query = query.filter(getattr(Notification, key) == value)
    return query.all()


# ---------------------------------------------------------------------------
# حالت‌ها و تکرار
# ---------------------------------------------------------------------------
def test_acknowledge_and_external_wait_are_active_states(env):
    item = _exception(env)
    res = _patch(env, item.id, status="acknowledged")
    assert res.status_code == 200 and res.json()["status_label"] == "دیده شد" and res.json()["acknowledged_at"]
    assert _patch(env, item.id, status="waiting_external").json()["status"] == "waiting_external"
    assert [i["id"] for i in env.client.get("/exceptions/", headers=_auth(env.admin)).json()] == [item.id]


def test_resolution_uses_a_standard_code(env):
    item = _exception(env)
    assert _patch(env, item.id, status="resolved", resolution="متن", resolution_code="نامعتبر").status_code == 422
    res = _patch(env, item.id, status="resolved", resolution="با تأمین‌کننده حل شد", resolution_code="supplier_followup")
    assert res.status_code == 200 and res.json()["resolution_code_label"] == "پیگیری با تأمین‌کننده"


def test_evidence_links_accumulate_in_history(env):
    item = _exception(env)
    assert _patch(env, item.id, evidence_ref="/app/documents?doc=7").json()["evidence_refs"] == ["/app/documents?doc=7"]
    res = _patch(env, item.id, evidence_ref="/app/receipts?receipt=2")
    assert res.json()["evidence_refs"] == ["/app/documents?doc=7", "/app/receipts?receipt=2"]
    assert _patch(env, item.id, evidence_ref="javascript:alert(1)").status_code == 400


def test_new_event_bumps_count_and_reopens_but_periodic_scan_does_not(env):
    def fire():
        exception_service.record(env.db, "return_shortage", "driver_return", 5, organization_id=env.org.id, warehouse_id=env.warehouse.id, reason="کسری")
        env.db.commit()
    fire()
    fire()
    env.db.expire_all()
    item = env.db.query(OperationException).filter(OperationException.kind == "return_shortage").one()
    assert item.occurrence_count == 2
    assert _patch(env, item.id, status="resolved", resolution="حل شد").status_code == 200
    exception_service.detect(env.db, env.org.id)
    env.db.expire_all()
    assert env.db.get(OperationException, item.id).status == "resolved"    # بررسی دوره‌ای بازش نمی‌کند
    fire()
    env.db.expire_all()
    row = env.db.get(OperationException, item.id)
    assert row.status == "open" and row.occurrence_count == 3 and row.resolved_by_id is None and row.resolution is None
    assert env.db.query(OperationException).filter(OperationException.kind == "return_shortage").count() == 1
    actions = [e["action"] for e in env.client.get(f"/exceptions/{item.id}", headers=_auth(env.admin)).json()["events"]]
    assert "بازگشایی با رویداد تازه" in actions


# ---------------------------------------------------------------------------
# اعلان، یادآوری و escalation
# ---------------------------------------------------------------------------
def test_owner_and_status_changes_notify_only_the_owner(env):
    item = _exception(env)
    assert _patch(env, item.id, owner_id=env.manager.id).status_code == 200
    assert len(_notes(env, kind="exception_opened", user_id=env.manager.id)) == 1
    assert _patch(env, item.id, status="in_progress").status_code == 200
    assert len(_notes(env, kind="exception_opened", user_id=env.manager.id)) == 1      # همان اعلان تازه می‌شود، نه اعلان دوم
    before = len(_notes(env))
    assert _patch(env, item.id, note="فقط یادداشت").status_code == 200
    assert len(_notes(env)) == before                                                  # یادداشت اعلان نمی‌سازد


def test_reminder_once_before_due_and_escalation_after_due(env):
    item = _exception(env, kind="pick_return_pending", due_at=_now() + timedelta(minutes=30), owner_id=env.manager.id)
    exception_service.detect(env.db, env.org.id)
    exception_service.detect(env.db, env.org.id)
    assert len(_notes(env, dedupe_key=f"exception:{item.id}:reminder")) == 1
    env.db.expire_all()
    row = env.db.get(OperationException, item.id)
    assert row.reminded_at is not None and row.escalated_at is None
    first = row.reminded_at
    row.due_at = _now() - timedelta(minutes=1)
    env.db.commit()
    exception_service.detect(env.db, env.org.id)
    [note] = _notes(env, dedupe_key=f"exception:{item.id}:escalation")
    assert note.audience == "admin"
    env.db.expire_all()
    row = env.db.get(OperationException, item.id)
    assert row.escalated_at is not None and row.reminded_at == first


def test_critical_unacknowledged_escalates_without_due_date(env):
    item = _exception(env, kind="pick_return_pending", severity="critical", opened_at=_now() - timedelta(hours=1))
    other = _exception(env, kind="pick_return_pending", entity_id=2, severity="critical", opened_at=_now() - timedelta(hours=1), status="acknowledged")
    exception_service.detect(env.db, env.org.id)
    assert len(_notes(env, dedupe_key=f"exception:{item.id}:escalation")) == 1
    assert _notes(env, dedupe_key=f"exception:{other.id}:escalation") == []


# ---------------------------------------------------------------------------
# دید راننده و مشتری
# ---------------------------------------------------------------------------
def test_driver_reports_incident_and_sees_only_his_own(env):
    order = _order(env)
    url = "/exceptions/report"
    assert env.client.post(url, headers=_auth(env.rival), json={"order_id": order["id"], "issue": "breakdown"}).status_code == 404
    res = env.client.post(url, headers=_auth(env.driver), json={"order_id": order["id"], "issue": "breakdown", "note": "پنچر شدم"})
    assert res.status_code == 200, res.text
    assert env.client.post(url, headers=_auth(env.driver), json={"order_id": order["id"], "issue": "breakdown"}).status_code == 200
    mine = env.client.get("/exceptions/mine", headers=_auth(env.driver)).json()
    assert len(mine) == 1 and mine[0]["occurrence_count"] == 2 and "پنچر" in mine[0]["trigger_reason"]
    assert set(mine[0]) == {"id", "kind_label", "trigger_reason", "suggested_action", "occurrence_count", "order_id", "opened_at", "status_label"}
    assert env.client.get("/exceptions/mine", headers=_auth(env.rival)).json() == []
    assert env.client.get("/exceptions/mine", headers=_auth(env.admin)).status_code == 403
    assert env.client.get("/exceptions/", headers=_auth(env.driver)).status_code == 403
    assert any(i["kind"] == "driver_incident" for i in env.client.get("/exceptions/", headers=_auth(env.admin)).json())


def test_customer_sees_only_a_next_action_for_his_own_order(env):
    order = _order(env)
    code = order["tracking_code"]
    base = env.client.get(f"/public/track/{code}", params={"phone": "2233"}).json()
    assert base["details"]["next_action"] is None
    env.db.add(OperationException(organization_id=env.org.id, kind="order_stock_held", entity_type="order", entity_id=order["id"], warehouse_id=env.warehouse.id,
                                  severity="high", team="warehouse", status="open", opened_at=_now(), trigger_reason="متن داخلی محرمانه", suggested_action="اقدام داخلی"))
    env.db.commit()
    verified = env.client.get(f"/public/track/{code}", params={"phone": "2233"})
    assert "فروشنده" in verified.json()["details"]["next_action"] and "محرمانه" not in verified.text
    public = env.client.get(f"/public/track/{code}")
    assert public.json()["details"] is None and "محرمانه" not in public.text


# ---------------------------------------------------------------------------
# مهلت پاسخ تیکت
# ---------------------------------------------------------------------------
def _ticket(env, created=None, **kw) -> Ticket:
    data = dict(organization_id=env.org.id, code=f"TK-{kw.pop('suffix', 'A')}", subject="s", category="other", source="customer", handler="org", status="open",
                waiting_on="org", created_at=created or _now(), last_activity_at=created or _now())
    data.update(kw)
    ticket = Ticket(**data)
    env.db.add(ticket)
    env.db.commit()
    return ticket


def test_first_response_is_recorded_once_and_internal_note_does_not_count(env):
    ticket = _ticket(env)
    url = f"/tickets/{ticket.id}/messages"
    assert env.client.post(url, headers=_auth(env.admin), data={"body": "یادداشت", "visibility": "side"}).status_code in (200, 201)
    env.db.expire_all()
    assert env.db.get(Ticket, ticket.id).first_response_at is None
    assert env.client.post(url, headers=_auth(env.admin), data={"body": "پاسخ", "visibility": "all"}).status_code in (200, 201)
    env.db.expire_all()
    first = env.db.get(Ticket, ticket.id).first_response_at
    assert first is not None
    assert env.client.post(url, headers=_auth(env.admin), data={"body": "پاسخ دوم", "visibility": "all"}).status_code in (200, 201)
    env.db.expire_all()
    assert env.db.get(Ticket, ticket.id).first_response_at == first


def test_ticket_sla_uses_organization_setting_and_opens_exceptions(env):
    assert env.client.put("/valuation/settings", headers=_auth(env.admin), json={"ticket_first_response_hours": 2, "ticket_resolution_hours": 10}).status_code == 200
    late = _ticket(env, created=_now() - timedelta(hours=3), suffix="LATE")
    fresh = _ticket(env, created=_now() - timedelta(hours=1), suffix="NEW")
    old = _ticket(env, created=_now() - timedelta(hours=11), suffix="OLD", first_response_at=_now() - timedelta(hours=10))
    platform = _ticket(env, created=_now() - timedelta(hours=11), suffix="PLT", source="org", handler="platform", waiting_on="platform")
    detail = env.client.get(f"/tickets/{late.id}", headers=_auth(env.admin)).json()
    assert detail["sla_breached"] is True and detail["first_response_due"]
    assert env.client.get(f"/tickets/{fresh.id}", headers=_auth(env.admin)).json()["sla_breached"] is False
    exception_service.detect(env.db, env.org.id)
    kinds = {(i.kind, i.entity_id) for i in env.db.query(OperationException).all()}
    assert ("ticket_first_response", late.id) in kinds and ("ticket_resolution", old.id) in kinds
    assert not any(entity in (fresh.id, platform.id) for _, entity in kinds)


# ---------------------------------------------------------------------------
# تأیید دونفره
# ---------------------------------------------------------------------------
def _limit(env, units=10):
    assert env.client.put("/valuation/settings", headers=_auth(env.admin), json={"adjustment_approval_units": units}).status_code == 200


def _movement(env, quantity, user=None):
    return env.client.post("/inventory/movements", headers=_auth(user or env.manager), json={
        "product_id": env.product.id, "warehouse_id": env.warehouse.id, "movement_type": "damage", "quantity": quantity, "reason": "شکستگی"})


def _stock(env):
    env.db.expire_all()
    return env.db.get(Inventory, env.inventory.id).quantity


def test_small_adjustment_runs_and_off_by_default(env):
    assert _movement(env, 50).status_code == 201
    assert _stock(env) == 50


def test_large_adjustment_needs_a_second_person(env):
    _limit(env)
    assert _movement(env, 5).status_code == 201
    assert _stock(env) == 95
    res = _movement(env, 20)
    assert res.status_code == 400 and "تأیید" in res.json()["detail"]
    assert _stock(env) == 95
    assert _movement(env, 20).status_code == 400                                       # درخواست تکراری ساخته نمی‌شود
    pending = env.client.get("/adjustment-approvals", headers=_auth(env.admin)).json()
    assert len(pending) == 1 and pending[0]["quantity"] == 20
    assert env.client.get("/adjustment-approvals", headers=_auth(env.manager)).status_code == 403
    url = f"/adjustment-approvals/{pending[0]['id']}/decide"
    assert env.client.post(url, headers=_auth(env.manager), json={"approve": True}).status_code == 403
    assert env.client.post(url, headers=_auth(env.admin), json={"approve": True}).status_code == 200
    assert _stock(env) == 75
    assert env.client.post(url, headers=_auth(env.admin2), json={"approve": True}).status_code == 400   # دوبار اجرا نمی‌شود
    assert _stock(env) == 75


def test_requester_cannot_approve_his_own_request(env):
    _limit(env)
    assert _movement(env, 20, env.admin).status_code == 400
    [row] = env.client.get("/adjustment-approvals", headers=_auth(env.admin2)).json()
    url = f"/adjustment-approvals/{row['id']}/decide"
    assert env.client.post(url, headers=_auth(env.admin), json={"approve": True}).status_code == 403
    assert env.client.post(url, headers=_auth(env.admin2), json={"approve": False}).status_code == 400
    assert env.client.post(url, headers=_auth(env.admin2), json={"approve": False, "note": "شمارش دوباره کنید"}).status_code == 200
    assert _stock(env) == 100


def test_set_balance_is_also_covered_and_failed_execution_keeps_request_open(env):
    _limit(env)
    url = f"/inventory/stock/{env.product.id}"
    res = env.client.put(url, headers=_auth(env.manager), json={"quantity": 80, "warehouse_id": env.warehouse.id, "reason": "شمارش"})
    assert res.status_code == 400 and _stock(env) == 100
    [row] = env.client.get("/adjustment-approvals", headers=_auth(env.admin)).json()
    assert row["kind"] == "set_balance" and row["quantity"] == 20
    assert _movement(env, 90, env.admin2).status_code == 400
    approvals = env.client.get("/adjustment-approvals", headers=_auth(env.admin)).json()
    big = next(a for a in approvals if a["quantity"] == 90)
    assert env.client.post(f"/adjustment-approvals/{big['id']}/decide", headers=_auth(env.admin), json={"approve": True}).status_code == 200
    assert _stock(env) == 10
    # حالا موجودی ۱۰ است؛ اصلاح قبلی هنوز معتبر است و به ۸۰ می‌رساند
    assert env.client.post(f"/adjustment-approvals/{row['id']}/decide", headers=_auth(env.admin), json={"approve": True}).status_code == 200
    assert _stock(env) == 80


def test_card_for_pending_approvals(env):
    _limit(env)
    assert _movement(env, 20).status_code == 400
    cards = {c["key"]: c for c in env.client.get("/action-center", headers=_auth(env.admin)).json()["cards"]}
    assert cards["adjustment_approvals"]["count"] == 1
    assert "adjustment_approvals" not in {c["key"] for c in env.client.get("/action-center", headers=_auth(env.manager)).json()["cards"]}


