"""
مرحله A بهره‌وری (docs/productivity.md):
  - مرکز اقدام: عدد هر کارت = طول همان فهرستی که پیوند کارت باز می‌کند؛ کارت صفر برنمی‌گردد؛ هر نقش کارت خودش
  - جستجوی سراسری: گروه‌بندی، تطابق دقیق، یکسان‌سازی ارقام، جداسازی سازمان‌ها و محدوده نقش
  - نماهای ذخیره‌شده: خودم و مشترک با نقش، حذف فقط توسط سازنده
  - خط زمانی سفارش و عملیات گروهی با پیش‌نمایش
"""
from datetime import datetime, time, timedelta, timezone

import pytest

from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import (
    Customer, Order, OrderItem, OrderStatusHistory, Organization, Product, RoleEnum, Ticket, User, Vehicle,
)
from app.services import action_center_service
from app.services.dispatch_service import local_to_utc
from tests.factories import default_warehouse

NOW_LOCAL = datetime.now(timezone.utc) + timedelta(hours=3, minutes=30)
TODAY = NOW_LOCAL.date()


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


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
        warehouse = default_warehouse(db, org.id)
        admin = User(username=f"{slug}_admin", email=f"{slug}@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
        manager = User(username=f"{slug}_wm", email=f"{slug}wm@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password="x",
                       warehouse_id=warehouse.id)
        driver = User(username=f"{slug}_drv", email=f"{slug}drv@x.io", role=RoleEnum.DRIVER, hashed_password="x",
                      full_name="علی رضایی", driver_code=f"DRV-{slug}")
        db.add_all([admin, manager, driver])
        db.commit()
        vehicle = Vehicle(license_plate="12ب345-67", type="van", capacity_kg=1000, driver_id=driver.id, status="available")
        rice = Product(name="برنج ایرانی", sku=f"RICE-{slug.upper()}", barcode=f"6260000{n[0]}1", price=1, weight_kg=10)
        customer = Customer(name="مریم احمدی", mobile="09121112233")
        db.add_all([vehicle, rice, customer])
        db.commit()

        def order(status, start, end, with_vehicle=True, priority=False):
            n[0] += 1
            o = Order(tracking_code=f"LT-{slug[:2].upper()}{n[0]:06d}", status=status, size="m", priority=priority,
                      delivery_window_start=start, delivery_window_end=end, destination_province="تهران",
                      destination_city="تهران", recipient_name="مریم احمدی", recipient_mobile="09121112233",
                      customer_id=customer.id, total_weight_kg=10, warehouse_id=warehouse.id,
                      vehicle_id=vehicle.id if with_vehicle else None, driver_id=driver.id if with_vehicle else None)
            o.items.append(OrderItem(product_id=rice.id, product_name=rice.name, product_sku=rice.sku, quantity=1))
            db.add(o)
            db.flush()
            db.add(OrderStatusHistory(order_id=o.id, from_status=None, to_status="pending"))
            db.commit()
            return o

        today_10 = local_to_utc(datetime.combine(TODAY, time(10)))
        past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=3)
        orders = {
            "late": order("in_transit", past - timedelta(hours=2), past),
            "pending": order("pending", today_10 + timedelta(days=1), today_10 + timedelta(days=1, hours=2), with_vehicle=False),
            "failed": order("failed", past - timedelta(days=1), past - timedelta(days=1) + timedelta(hours=2)),
            "assigned_now": order("assigned", past - timedelta(hours=1), datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=5)),
        }
        ticket = Ticket(code=f"TK-{slug.upper()}1", subject="کالا نرسید", category="delivery", priority="normal",
                        source="customer", handler="org", status="open", waiting_on="org", order_id=orders["late"].id,
                        requester_name="مریم")
        db.add(ticket)
        db.commit()
        world[slug] = dict(org=org, admin=admin, manager=manager, driver=driver, vehicle=vehicle, rice=rice, orders=orders,
                           ticket=ticket, warehouse=warehouse)
    set_tenant(db, None)
    yield client, db, world
    db.close()


# ---------------------------------------------------------------------------
# مرکز اقدام
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("who", ["admin", "manager", "driver"])
def test_every_card_count_equals_its_list_length(env, who):
    client, db, world = env
    user = world["alpha"][who]
    res = client.get("/action-center", headers=_auth(user))
    assert res.status_code == 200, res.text
    cards = res.json()["cards"]
    assert cards, "دست‌کم یک کارت انتظار می‌رفت"
    db.expire_all()
    set_tenant(db, user.organization_id)
    definitions = {c.key: c for c in action_center_service.cards_for(db, db.get(User, user.id))}
    for card in cards:
        assert card["count"] > 0
        assert len(card["items"]) <= action_center_service.SAMPLE
        assert card["title"] and card["why"] and card["owner"] and card["next_action"]
        spec = definitions[card["key"]]
        query = {k: str(v).lower() if isinstance(v, bool) else v for k, v in spec.query.items()}
        if spec.api == "/orders/":
            query["limit"] = 500
        listed = client.get(spec.api, params=query, headers=_auth(user))
        assert listed.status_code == 200, (card["key"], listed.text)
        body = listed.json()
        rows = body["items"] if isinstance(body, dict) else body
        assert len(rows) == card["count"], card["key"]
    weights = [c["weight"] for c in cards]
    assert weights == sorted(weights, reverse=True)


def test_cards_per_role_and_tenant(env):
    client, _, world = env
    admin_keys = {c["key"] for c in client.get("/action-center", headers=_auth(world["alpha"]["admin"])).json()["cards"]}
    assert {"orders_late", "orders_unassigned", "orders_failed", "tickets_waiting"} <= admin_keys
    late = next(c for c in client.get("/action-center", headers=_auth(world["alpha"]["admin"])).json()["cards"]
                if c["key"] == "orders_late")
    assert late["count"] == 1 and late["items"][0]["label"] == world["alpha"]["orders"]["late"].tracking_code
    assert late["link"] == "/app/orders?view=late"
    driver_keys = {c["key"] for c in client.get("/action-center", headers=_auth(world["alpha"]["driver"])).json()["cards"]}
    assert driver_keys <= {"driver_needs_update", "driver_today"} and "driver_needs_update" in driver_keys


def test_orders_view_filter(env):
    client, _, world = env
    res = client.get("/orders/", params={"view": "late"}, headers=_auth(world["alpha"]["admin"]))
    assert [o["tracking_code"] for o in res.json()] == [world["alpha"]["orders"]["late"].tracking_code]
    assert client.get("/orders/", params={"view": "nope"}, headers=_auth(world["alpha"]["admin"])).status_code == 422


# ---------------------------------------------------------------------------
# جستجوی سراسری
# ---------------------------------------------------------------------------
def test_search_exact_code_with_persian_digits_and_tenant_isolation(env):
    client, _, world = env
    code = world["alpha"]["orders"]["late"].tracking_code
    persian = code.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    res = client.get("/search", params={"q": persian}, headers=_auth(world["alpha"]["admin"])).json()
    assert res["exact"]["label"] == code and res["exact"]["link"].endswith(f"order={world['alpha']['orders']['late'].id}")
    other = client.get("/search", params={"q": code}, headers=_auth(world["beta"]["admin"])).json()
    assert other["exact"] is None
    assert all(code not in h["label"] for g in other["groups"] for h in g["hits"])


def test_search_groups_products_vehicles_and_roles(env):
    client, _, world = env
    res = client.get("/search", params={"q": "RICE-ALPHA"}, headers=_auth(world["alpha"]["manager"])).json()
    assert res["exact"]["link"] == f"/app/stock-card?product={world['alpha']['rice'].id}"
    plate = client.get("/search", params={"q": "۱۲ب۳۴۵"}, headers=_auth(world["alpha"]["admin"])).json()
    assert any(g["type"] == "vehicle" for g in plate["groups"])
    assert all(len(g["hits"]) <= 5 for g in plate["groups"])
    assert client.get("/search", params={"q": "LT"}, headers=_auth(world["alpha"]["driver"])).status_code == 403


# ---------------------------------------------------------------------------
# نماهای ذخیره‌شده
# ---------------------------------------------------------------------------
def test_saved_views_own_shared_and_delete(env):
    client, _, world = env
    a, m = world["alpha"]["admin"], world["alpha"]["manager"]
    mine = client.post("/saved-views", json={"page_key": "orders", "name": "دیرکردها", "filters": {"view": "late"}}, headers=_auth(a))
    assert mine.status_code == 201, mine.text
    shared = client.post("/saved-views", json={"page_key": "orders", "name": "فوری‌ها", "filters": {"priority": "true"},
                                               "shared_role": "warehouse_manager"}, headers=_auth(a)).json()
    assert client.post("/saved-views", json={"page_key": "orders", "name": "دیرکردها"}, headers=_auth(a)).status_code == 400
    assert [v["name"] for v in client.get("/saved-views", params={"page": "orders"}, headers=_auth(m)).json()] == ["فوری‌ها"]
    assert client.delete(f"/saved-views/{shared['id']}", headers=_auth(m)).status_code == 403
    assert client.get("/saved-views", headers=_auth(world["beta"]["admin"])).json() == []
    assert client.post("/saved-views", json={"page_key": "orders", "name": "x", "filters": {"a b": 1}}, headers=_auth(a)).status_code == 400
    assert client.get("/saved-views", headers=_auth(world["alpha"]["driver"])).status_code == 403
    assert client.delete(f"/saved-views/{shared['id']}", headers=_auth(a)).status_code == 204


# ---------------------------------------------------------------------------
# خط زمانی سفارش
# ---------------------------------------------------------------------------
def test_order_timeline_header_and_access(env):
    client, _, world = env
    late = world["alpha"]["orders"]["late"]
    res = client.get(f"/orders/{late.id}/timeline", headers=_auth(world["alpha"]["admin"]))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["stage"] == "در مسیر مقصد"
    assert body["blocker"] == "از بازه تحویل گذشته و هنوز تحویل نشده"
    areas = {e["area"] for e in body["events"]}
    assert {"order", "support"} <= areas
    assert body["events"] == sorted(body["events"], key=lambda e: e["at"])
    assert client.get(f"/orders/{late.id}/timeline", headers=_auth(world["beta"]["admin"])).status_code == 404
    driver_view = client.get(f"/orders/{late.id}/timeline", headers=_auth(world["alpha"]["driver"])).json()
    assert all(e["area"] != "support" for e in driver_view["events"])


# ---------------------------------------------------------------------------
# عملیات گروهی
# ---------------------------------------------------------------------------
def test_bulk_priority_preview_then_execute(env):
    client, _, world = env
    a, orders = world["alpha"]["admin"], world["alpha"]["orders"]
    foreign = world["beta"]["orders"]["late"].id
    ids = [orders["late"].id, orders["pending"].id, orders["failed"].id, foreign]
    preview = client.post("/orders/bulk", json={"action": "priority", "ids": ids, "params": {"priority": True}}, headers=_auth(a))
    assert preview.status_code == 200, preview.text
    p = preview.json()
    assert (p["dry_run"], p["valid"], p["invalid"], p["unauthorized"]) == (True, 2, 1, 1)
    assert client.get(f"/orders/{orders['late'].id}", headers=_auth(a)).json()["priority"] is False
    done = client.post("/orders/bulk", json={"action": "priority", "ids": ids, "params": {"priority": True}, "dry_run": False},
                       headers=_auth(a)).json()
    assert done["valid"] == 2 and {r["status"] for r in done["results"]} == {"done", "invalid", "unauthorized"}
    detail = client.get(f"/orders/{orders['late'].id}", headers=_auth(a)).json()
    assert detail["priority"] is True and detail["history"][-1]["note"] == "فوری شد"
    wm = client.post("/orders/bulk", json={"action": "priority", "ids": ids, "params": {"priority": False}},
                     headers=_auth(world["alpha"]["manager"]))
    assert wm.status_code == 403


def test_bulk_assign_only_pending(env):
    client, _, world = env
    a, orders = world["alpha"]["admin"], world["alpha"]["orders"]
    res = client.post("/orders/bulk", json={"action": "assign", "ids": [orders["late"].id]}, headers=_auth(a)).json()
    assert res["results"][0]["status"] == "invalid"


def test_bulk_ticket_close_requires_typed_confirmation(env):
    client, _, world = env
    a, ticket = world["alpha"]["admin"], world["alpha"]["ticket"]
    body = {"action": "close", "ids": [ticket.id], "dry_run": False}
    assert client.post("/tickets/bulk", json=body, headers=_auth(a)).status_code == 400
    ok = client.post("/tickets/bulk", json={**body, "params": {"confirm": "تأیید"}}, headers=_auth(a)).json()
    assert ok["results"][0]["status"] == "done"
    again = client.post("/tickets/bulk", json={"action": "resolve", "ids": [ticket.id]}, headers=_auth(a)).json()
    assert again["results"][0]["status"] == "invalid"
    assert client.post("/tickets/bulk", json={"action": "resolve", "ids": [ticket.id]},
                       headers=_auth(world["alpha"]["driver"])).status_code == 403
