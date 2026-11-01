"""
مرحله ۱ راهنمای عملیات (docs/operations-guide.md):
  - صف پایدار پیام: atomic با عملیات، بدون تکرار رویداد، retry محدود، lease، پاک شدن متن حساس
  - وظایف ناموفق: ثبت، دید کارکنان پلتفرم، اجرای دوباره با گزارش فعالیت
  - وظیفه بدون سازمان معتبر اجرا نمی‌شود
  - تطبیق دوره‌ای فقط گزارش می‌دهد و چیزی را اصلاح نمی‌کند
  - نگه‌داشت کیفی کالای رزروشده و لغو وسط برداشت
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app import tasks
from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import AuditLog, Inventory, Order, Organization, Product, RoleEnum, User, Vehicle
from app.models_productivity import OperationException, OutboundMessage, TaskFailure
from app.models_wms import StockReservation
from app.services import exception_service, messaging, outbox_service, stock_ledger
from tests.factories import default_warehouse


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


def _window() -> dict:
    start = _now() - timedelta(hours=1)
    return {"delivery_window_start": start.isoformat() + "Z", "delivery_window_end": (start + timedelta(hours=8)).isoformat() + "Z"}


@pytest.fixture()
def env(api_env, monkeypatch):
    client, Session = api_env
    monkeypatch.setattr(tasks, "SessionLocal", Session)
    db = Session()
    org = Organization(name="فروشگاه آلفا", slug="alpha")
    other = Organization(name="فروشگاه بتا", slug="beta")
    db.add_all([org, other])
    db.commit()
    set_tenant(db, org.id)
    warehouse = default_warehouse(db, org.id)
    admin = User(username="adm", email="a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x", full_name="ادمین")
    driver = User(username="drv", email="d@x.io", role=RoleEnum.DRIVER, hashed_password="x", full_name="علی", driver_code="D1", driver_status="approved")
    db.add_all([admin, driver])
    db.commit()
    vehicle = Vehicle(license_plate="12ب345-67", type="van", capacity_kg=1000, driver_id=driver.id, status="available")
    product = Product(name="برنج", sku="RICE-1", barcode="62600001", price=1000, weight_kg=1)
    db.add_all([vehicle, product])
    db.commit()
    inventory = stock_ledger.lock_bucket(db, product.id, warehouse.id, "available", organization_id=org.id)
    document = stock_ledger.new_document(db, "receipt", organization_id=org.id, warehouse_id=warehouse.id, note="موجودی اولیه")
    stock_ledger.record(db, inventory, 100, "receipt", document=document, reason="موجودی اولیه")
    db.commit()
    set_tenant(db, None)
    support = User(username="plat", email="p@x.io", role=RoleEnum.PLATFORM_ADMIN, hashed_password="x")
    staff = User(username="sup", email="s@x.io", role=RoleEnum.PLATFORM_SUPPORT, hashed_password="x")
    db.add_all([support, staff])
    db.commit()
    set_tenant(db, org.id)
    yield SimpleNamespace(client=client, db=db, Session=Session, org=org, other=other, warehouse=warehouse, admin=admin, driver=driver,
                          vehicle=vehicle, product=product, inventory=inventory, platform=support, support=staff)
    db.close()


@pytest.fixture()
def sms_on(monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER", "kavenegar")
    monkeypatch.setenv("SMS_API_KEY", "SECRETKEY")
    monkeypatch.setenv("ORDER_SMS_ENABLED", "1")
    sent = []

    def deliver(mobile, text, local_id=None):
        sent.append((mobile, text, local_id))
        return True
    monkeypatch.setattr(messaging, "deliver_sms", deliver)
    return sent


def _order(env, quantity=5, **extra) -> dict:
    res = env.client.post("/orders/", headers=_auth(env.admin), json={
        "items": [{"product_id": env.product.id, "quantity": quantity}], "customer": {"name": "مریم احمدی", "mobile": "09121112233"},
        "destination_province": "تهران", "destination_city": "تهران", "destination_address": "خیابان آزادی پلاک ۱", "size": "m",
        "vehicle_id": env.vehicle.id, "warehouse_id": env.warehouse.id, **_window(), **extra})
    assert res.status_code == 201, res.text
    return res.json()


def _status(env, order_id, status, user=None):
    return env.client.put(f"/orders/{order_id}/status", headers=_auth(user or env.admin), json={"order_status": status})


def _publisher_session(env):
    db = env.Session()
    set_tenant(db, None)
    return db


# ---------------------------------------------------------------------------
# صف پایدار پیام
# ---------------------------------------------------------------------------
def test_message_is_saved_with_the_operation_not_sent_inline(env, sms_on):
    order = _order(env)
    assert sms_on == []                                        # درخواست کاربر منتظر سرویس بیرونی نیست
    env.db.expire_all()
    [row] = env.db.query(OutboundMessage).all()
    assert row.dedupe_key == f"order:{order['id']}:created" and row.status == "pending" and row.organization_id == env.org.id


def test_rolled_back_operation_leaves_no_message(env, sms_on):
    db = env.db
    messaging.queue_sms(db, "09121112233", "متن")
    db.rollback()
    assert db.query(OutboundMessage).count() == 0


def test_publish_delivers_once_and_clears_the_body(env, sms_on):
    _order(env)
    db = _publisher_session(env)
    assert outbox_service.publish_due(db)["sent"] == 1
    assert outbox_service.publish_due(db)["sent"] == 0         # اجرای دوباره ناشر پیام را دوباره نمی‌فرستد
    assert len(sms_on) == 1 and sms_on[0][2] is not None
    [row] = db.query(OutboundMessage).all()
    assert row.status == "sent" and row.body is None and "***" in row.recipient
    db.close()


def test_same_event_is_not_queued_twice(env, sms_on):
    db = env.db
    assert outbox_service.enqueue(db, "sms", "09121112233", "الف", dedupe_key="order:1:created") is not None
    db.commit()
    assert outbox_service.enqueue(db, "sms", "09121112233", "ب", dedupe_key="order:1:created") is None
    db.commit()
    assert db.query(OutboundMessage).count() == 1


def test_retry_is_bounded_with_backoff_and_failed_stays_visible(env, monkeypatch, sms_on):
    db = _publisher_session(env)
    outbox_service.enqueue(db, "sms", "09121112233", "متن عادی")
    db.commit()

    def boom(*a, **k):
        raise RuntimeError("provider down SECRETKEY")
    monkeypatch.setattr(messaging, "deliver_sms", boom)
    now = _now()
    assert outbox_service.publish_due(db, now)["retry"] == 1
    row = db.query(OutboundMessage).one()
    assert row.status == "pending" and row.next_attempt_at > now and "SECRETKEY" not in row.last_error
    assert outbox_service.publish_due(db, now)["retry"] == 0   # پیش از موعد برداشته نمی‌شود
    for _ in range(outbox_service.MAX_ATTEMPTS):
        row.next_attempt_at = _now() - timedelta(seconds=1)
        db.commit()
        outbox_service.publish_due(db)
    db.refresh(row)
    assert row.status == "failed" and row.attempts == outbox_service.MAX_ATTEMPTS and row.body == "متن عادی"
    db.close()

    listed = env.client.get("/platform/operations", headers=_auth(env.support)).json()
    assert listed["messages"][0]["id"] == row.id and listed["messages"][0]["replayable"] is True
    assert "متن عادی" not in str(listed) and "09121112233" not in str(listed)


def test_sensitive_message_never_replayed_and_body_removed_on_failure(env, monkeypatch, sms_on):
    db = _publisher_session(env)
    user = SimpleNamespace(mobile="09121112233", email=None)
    messaging.password_reset_code(db, user, "654321", "sms")
    db.commit()

    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(messaging, "deliver_sms", boom)
    row = db.query(OutboundMessage).one()
    assert row.sensitive and row.expires_at is not None
    row.attempts = outbox_service.MAX_ATTEMPTS - 1
    db.commit()
    outbox_service.publish_due(db)
    db.refresh(row)
    assert row.status == "failed" and row.body is None
    message_id = row.id
    db.close()
    res = env.client.post(f"/platform/operations/messages/{message_id}/retry", headers=_auth(env.platform), json={"reason": "تلاش دوباره"})
    assert res.status_code == 400


def test_expired_code_is_not_sent(env, sms_on):
    db = _publisher_session(env)
    messaging.password_reset_code(db, SimpleNamespace(mobile="09121112233", email=None), "654321", "sms")
    db.commit()
    assert outbox_service.publish_due(db, _now() + timedelta(minutes=11))["expired"] == 1
    assert sms_on == [] and db.query(OutboundMessage).one().body is None
    db.close()


def test_dead_worker_lease_is_picked_up_again(env, sms_on):
    db = _publisher_session(env)
    outbox_service.enqueue(db, "sms", "09121112233", "متن")
    db.commit()
    row = db.query(OutboundMessage).one()
    now = _now()
    row.status, row.attempts, row.lease_until = "sending", 1, now + timedelta(minutes=1)   # worker وسط ارسال مرد
    db.commit()
    assert outbox_service.publish_due(db, now)["sent"] == 0    # lease هنوز معتبر است
    assert outbox_service.publish_due(db, now + timedelta(minutes=2))["sent"] == 1
    assert len(sms_on) == 1
    db.close()


def test_unconfigured_channel_queues_nothing(env, monkeypatch):
    monkeypatch.delenv("SMS_PROVIDER", raising=False)
    _order(env)
    assert env.db.query(OutboundMessage).count() == 0


def test_purge_keeps_active_messages(env, sms_on):
    db = _publisher_session(env)
    old = _now() - timedelta(days=40)
    db.add_all([OutboundMessage(channel="sms", recipient="0912***", status="sent", created_at=old, next_attempt_at=old),
                 OutboundMessage(channel="sms", recipient="0912", body="x", status="pending", created_at=old, next_attempt_at=old)])
    db.commit()
    assert outbox_service.purge_old(db)["messages"] == 1
    assert db.query(OutboundMessage).one().status == "pending"
    db.close()


# ---------------------------------------------------------------------------
# وظایف ناموفق و سازمان معتبر
# ---------------------------------------------------------------------------
def test_task_without_valid_tenant_refuses_to_run(env):
    for bad in (None, 0, -1, "1", True):
        with pytest.raises(tasks.TaskContextError):
            tasks._tenant_session(bad)
    with pytest.raises(tasks.TaskContextError):
        tasks._tenant_session(999999)
    env.other.is_active = False
    env.db.commit()
    with pytest.raises(tasks.TaskContextError):
        tasks._tenant_session(env.other.id)
    tasks._tenant_session(env.org.id).close()


def test_report_task_rejects_user_of_another_organization(env):
    with pytest.raises(tasks.TaskContextError):
        tasks.generate_report_task(env.other.id, env.admin.id, "inventory", "excel", {})


def test_failed_task_is_recorded_without_arguments_and_can_be_replayed(env, monkeypatch):
    tasks._record_task_failure(sender=SimpleNamespace(name="tasks.detect_exceptions"), task_id="abc", exception=RuntimeError("خطا"), args=["09121112233"])
    tasks._record_task_failure(sender=SimpleNamespace(name="tasks.generate_report"), task_id="def", exception=RuntimeError("خطا"))
    url = "/platform/operations"
    body = env.client.get(url, headers=_auth(env.support)).json()
    by_name = {t["task_name"]: t for t in body["tasks"]}
    assert "09121112233" not in str(body)
    assert by_name["tasks.detect_exceptions"]["replayable"] and not by_name["tasks.generate_report"]["replayable"]

    sent = []
    from app.celery_app import celery_app
    monkeypatch.setattr(celery_app, "send_task", lambda name: sent.append(name))
    replay = f"{url}/tasks/{by_name['tasks.detect_exceptions']['id']}/replay"
    assert env.client.post(replay, headers=_auth(env.support), json={"reason": "اجرای دوباره"}).status_code == 403
    assert env.client.post(replay, headers=_auth(env.platform), json={"reason": "x"}).status_code == 422
    assert env.client.post(replay, headers=_auth(env.platform), json={"reason": "بررسی شد"}).status_code == 200
    assert sent == ["tasks.detect_exceptions"]
    assert env.client.post(replay, headers=_auth(env.platform), json={"reason": "بررسی شد"}).status_code == 400
    assert env.client.post(f"{url}/tasks/{by_name['tasks.generate_report']['id']}/replay", headers=_auth(env.platform), json={"reason": "بررسی شد"}).status_code == 400
    set_tenant(env.db, None)
    log = env.db.query(AuditLog).filter(AuditLog.action == "platform.task_replay").execution_options(skip_tenant_filter=True).one()
    assert log.reason == "بررسی شد"


def test_org_staff_cannot_see_platform_operations(env):
    assert env.client.get("/platform/operations", headers=_auth(env.admin)).status_code == 403


def test_one_organization_failure_does_not_stop_others_and_is_visible(env):
    calls = []

    def work(db):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("خطای سازمان اول")
    assert tasks._each_organization(work, "آزمون", "tasks.detect_exceptions")["organizations"] == 1
    assert len(calls) == 2
    db = env.Session()
    assert db.query(TaskFailure).one().organization_id is not None
    db.close()


# ---------------------------------------------------------------------------
# تطبیق
# ---------------------------------------------------------------------------
def _exceptions(env, kind):
    env.db.expire_all()
    return env.db.query(OperationException).filter(OperationException.kind == kind).all()


def test_healthy_stock_reports_nothing(env):
    _order(env)
    exception_service.detect(env.db, env.org.id, reconcile=True)
    for kind in exception_service.RECONCILE_KINDS:
        assert _exceptions(env, kind) == []


def test_ledger_mismatch_is_reported_and_never_corrected(env):
    env.db.execute(text("UPDATE inventories SET quantity = 90 WHERE id = :i"), {"i": env.inventory.id})
    env.db.commit()
    exception_service.detect(env.db, env.org.id, reconcile=True)
    [item] = _exceptions(env, "stock_mismatch")
    assert item.severity == "critical" and item.entity_id == env.inventory.id and item.warehouse_id == env.warehouse.id
    env.db.expire_all()
    assert env.db.get(Inventory, env.inventory.id).quantity == 90          # چیزی اصلاح نشد

    # اجرای عادی تطبیق نمی‌کند، پس نباید مورد را بسته فرض کند
    exception_service.detect(env.db, env.org.id)
    assert _exceptions(env, "stock_mismatch")[0].status == "open"

    env.db.execute(text("UPDATE inventories SET quantity = 100 WHERE id = :i"), {"i": env.inventory.id})
    env.db.commit()
    exception_service.detect(env.db, env.org.id, reconcile=True)
    assert _exceptions(env, "stock_mismatch")[0].status == "resolved"


def test_orphan_reservation_of_finished_order_is_reported(env):
    order = _order(env)
    env.db.execute(text("UPDATE orders SET status = 'canceled' WHERE id = :i"), {"i": order["id"]})
    env.db.commit()
    exception_service.detect(env.db, env.org.id, reconcile=True)
    assert len(_exceptions(env, "reservation_orphan")) == 1
    assert env.db.query(StockReservation).filter(StockReservation.status == "active").count() == 1


def test_failed_order_waiting_for_decision_is_not_an_orphan(env):
    order = _order(env)
    assert _status(env, order["id"], "failed").status_code == 200
    exception_service.detect(env.db, env.org.id, reconcile=True)
    assert _exceptions(env, "reservation_orphan") == []


def test_transit_stock_mismatch_is_reported(env):
    transit = stock_ledger.lock_bucket(env.db, env.product.id, env.warehouse.id, "in_transit", organization_id=env.org.id)
    document = stock_ledger.new_document(env.db, "adjustment", organization_id=env.org.id, warehouse_id=env.warehouse.id, note="آزمون")
    stock_ledger.record(env.db, transit, 3, "adjustment", document=document, reason="آزمون")
    env.db.commit()
    exception_service.detect(env.db, env.org.id, reconcile=True)
    [item] = _exceptions(env, "transit_mismatch")
    assert item.entity_id == transit.id


# ---------------------------------------------------------------------------
# نگه‌داشت کیفی کالای رزروشده (تصمیم ت۱)
# ---------------------------------------------------------------------------
def _inspect(env, quantity, **extra):
    return env.client.post("/quality/inspections", headers=_auth(env.admin), json={
        "product_id": env.product.id, "warehouse_id": env.warehouse.id, "from_status": "available",
        "results": [{"status": "damaged", "quantity": quantity, "reason": "خیس شده"}], **extra})


def _bucket(env, status="available"):
    env.db.expire_all()
    return env.db.query(Inventory).filter(Inventory.product_id == env.product.id, Inventory.stock_status == status).first()


def test_reserved_stock_cannot_be_held_without_explicit_consent(env):
    _order(env, quantity=98)
    assert _inspect(env, 5).status_code == 400
    assert _bucket(env).reserved_quantity == 98


def test_holding_reserved_stock_releases_least_urgent_order_and_blocks_loading(env):
    urgent = _order(env, quantity=50, priority=True)
    normal = _order(env, quantity=48)
    res = _inspect(env, 5, release_reservations=True)
    assert res.status_code in (200, 201), res.text
    bucket = _bucket(env)
    assert bucket.quantity == 95 and bucket.reserved_quantity == 50
    assert _bucket(env, "damaged").quantity == 5
    env.db.expire_all()
    assert env.db.get(Order, urgent["id"]).stock_state == "reserved"
    held = env.db.get(Order, normal["id"])
    assert held.stock_state == "held"
    [item] = _exceptions(env, "order_stock_held")
    assert item.entity_id == normal["id"] and item.status == "open"

    blocked = _status(env, normal["id"], "picked_up")
    assert blocked.status_code == 400 and "نگه‌داشت" in blocked.json()["detail"]
    assert _bucket(env).quantity == 95                                      # کالایی بدون رزرو خارج نشد
    timeline = env.client.get(f"/orders/{normal['id']}/timeline", headers=_auth(env.admin)).json()
    assert "نگه‌داشت" in timeline["blocker"]


def test_re_reserve_returns_order_to_normal_flow_and_closes_exception(env):
    order = _order(env, quantity=90)
    assert _inspect(env, 15, release_reservations=True).status_code in (200, 201)     # ۸۵ سالم می‌ماند
    url = f"/orders/{order['id']}/re-reserve"
    assert env.client.post(url, headers=_auth(env.driver)).status_code == 403
    assert env.client.post(url, headers=_auth(env.admin)).status_code == 400         # هنوز کافی نیست
    inventory = _bucket(env)
    document = stock_ledger.new_document(env.db, "receipt", organization_id=env.org.id, warehouse_id=env.warehouse.id, note="ورود")
    stock_ledger.record(env.db, stock_ledger.lock_bucket(env.db, env.product.id, env.warehouse.id, "available"), 10, "receipt",
                        document=document, reason="ورود تازه")
    env.db.commit()
    assert inventory.id
    res = env.client.post(url, headers=_auth(env.admin))
    assert res.status_code == 200 and res.json()["stock_state"] == "reserved"
    assert _bucket(env).reserved_quantity == 90
    assert env.client.post(url, headers=_auth(env.admin)).status_code == 400         # نگه‌داشته نیست
    assert _status(env, order["id"], "picked_up").status_code == 200
    assert _bucket(env).quantity == 5
    exception_service.detect(env.db, env.org.id)
    assert _exceptions(env, "order_stock_held")[0].status == "resolved"


def test_re_reserve_fails_cleanly_when_stock_is_short(env):
    order = _order(env, quantity=98)
    assert _inspect(env, 5, release_reservations=True).status_code in (200, 201)
    res = env.client.post(f"/orders/{order['id']}/re-reserve", headers=_auth(env.admin))
    assert res.status_code == 400
    env.db.expire_all()
    assert env.db.get(Order, order["id"]).stock_state == "held" and _bucket(env).reserved_quantity == 0


def test_canceling_a_held_order_releases_what_remains(env):
    order = _order(env, quantity=98)
    assert _inspect(env, 5, release_reservations=True).status_code in (200, 201)
    assert _status(env, order["id"], "canceled").status_code == 200
    env.db.expire_all()
    assert env.db.get(Order, order["id"]).stock_state == "released" and _bucket(env).reserved_quantity == 0
    exception_service.detect(env.db, env.org.id)
    assert _exceptions(env, "order_stock_held")[0].status == "resolved"
