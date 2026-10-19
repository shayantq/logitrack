"""
مرحله ۱۱: تیکت پشتیبانی — مشتری (لینک محرمانه) ← سازمان ← پشتیبانی پلتفرم؛ راننده ← سازمان؛ سازمان ← پلتفرم.
"""
import base64
from datetime import datetime, timedelta, timezone

import pytest

from app.core import storage
from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import Customer, Order, OrderItem, OrderStatusHistory, Organization, Product, RoleEnum, User, Vehicle
from app.routers.tickets import public_create_limiter, public_message_limiter

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MEDIA_ROOT", tmp_path / "media")
    public_create_limiter.reset()
    public_message_limiter.reset()
    yield
    public_create_limiter.reset()
    public_message_limiter.reset()


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    world = {}
    platform = User(username="root", email="root@x.io", role=RoleEnum.PLATFORM_ADMIN, hashed_password="x")
    helpdesk = User(username="helpdesk", email="help@x.io", role=RoleEnum.PLATFORM_SUPPORT, hashed_password="x", full_name="پشتیبان")
    db.add_all([platform, helpdesk])
    db.commit()
    for slug in ("alpha", "beta"):
        org = Organization(name=f"فروشگاه {slug}", slug=slug)
        db.add(org)
        db.commit()
        set_tenant(db, org.id)
        admin = User(username=f"{slug}_admin", email=f"{slug}@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x", full_name="ادمین")
        manager = User(username=f"{slug}_mgr", email=f"{slug}m@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password="x")
        ali = User(username=f"{slug}_ali", email=f"{slug}a@x.io", role=RoleEnum.DRIVER, hashed_password="x", full_name="علی رضایی", driver_code=f"D-{slug}-1")
        sara = User(username=f"{slug}_sara", email=f"{slug}s@x.io", role=RoleEnum.DRIVER, hashed_password="x", driver_code=f"D-{slug}-2")
        db.add_all([admin, manager, ali, sara])
        db.commit()
        vehicle = Vehicle(license_plate=f"12ب{345 + len(world)}-67", type="van", capacity_kg=900, driver_id=ali.id, status="available")
        product = Product(name="برنج", sku=f"R-{slug}", price=1, weight_kg=1)
        customer = Customer(name="مریم احمدی", mobile="09121112233")
        db.add_all([vehicle, product, customer])
        db.commit()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        order = Order(tracking_code=f"LT-{slug[:2].upper()}000001", status="in_transit", size="m", priority=False,
                      delivery_window_start=now, delivery_window_end=now + timedelta(hours=4), destination_province="تهران",
                      destination_city="تهران", destination_address="خیابان آزادی", recipient_name="مریم احمدی",
                      recipient_mobile="09121112233", customer_id=customer.id, vehicle_id=vehicle.id, driver_id=ali.id, total_weight_kg=1)
        order.items.append(OrderItem(product_id=product.id, product_name="برنج", product_sku=product.sku, quantity=1))
        db.add(order)
        db.flush()
        db.add(OrderStatusHistory(order_id=order.id, from_status=None, to_status="in_transit"))
        db.commit()
        world[slug] = dict(org=org, admin=admin, manager=manager, ali=ali, sara=sara, order=order)
        set_tenant(db, None)
    try:
        yield client, db, world, platform, helpdesk
    finally:
        db.close()


def _customer_ticket(client, order, phone="2233", category="damaged", body="کارتن برنج پاره رسیده است.", file=None):
    files = {"file": ("photo.png", file, "image/png")} if file else None
    return client.post(f"/public/track/{order.tracking_code}/tickets", data={"phone": phone, "category": category, "body": body}, files=files)


def _msg(client, user, tid, body, visibility="all", url="/tickets"):
    return client.post(f"{url}/{tid}/messages", data={"body": body, "visibility": visibility}, headers=_auth(user))


# ---------------------------------------------------------------------------
def test_customer_ticket_requires_phone_and_valid_category(env):
    client, db, w, *_ = env
    order = w["alpha"]["order"]
    assert _customer_ticket(client, order, phone="0000").status_code == 403
    assert _customer_ticket(client, order, category="technical").status_code == 400     # موضوع مخصوص سازمان‌ها
    assert client.post("/public/track/LT-NOPE0000/tickets", data={"phone": "2233", "category": "delay", "body": "سلام دوباره"}).status_code == 404
    res = _customer_ticket(client, order, file=PNG)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["code"].startswith("TK-") and body["access_token"] and body["priority"] == "high"   # آسیب‌دیدگی ← اولویت بالا
    assert body["messages"][0]["has_attachment"] is True and body["waiting_on"] == "org"
    # تصویر غیرمجاز
    assert _customer_ticket(client, order, file=b"not an image").status_code == 400
    # حداکثر ۳ درخواست باز برای یک سفارش
    for _ in range(2):
        assert _customer_ticket(client, order, category="delay").status_code == 201
    assert _customer_ticket(client, order, category="delay").status_code == 400


def test_full_flow_customer_org_platform_with_visibility(env):
    client, db, w, platform, helpdesk = env
    a = w["alpha"]
    created = _customer_ticket(client, a["order"]).json()
    token, tid = created["access_token"], created["id"]

    # سازمان: تیکت منتظر پاسخ من
    assert client.get("/tickets/summary", headers=_auth(a["manager"])).json()["needs_action"] == 1
    waiting = client.get("/tickets/", params={"waiting": True}, headers=_auth(a["admin"])).json()
    assert [t["id"] for t in waiting] == [tid] and waiting[0]["order_tracking_code"] == a["order"].tracking_code
    detail = client.get(f"/tickets/{tid}", headers=_auth(a["admin"])).json()
    assert detail["requester_mobile"] == "09121112233" and detail["can_escalate"] is True
    assert [o["visibility"] for o in detail["reply_options"]] == ["all", "side"]     # «پیام به پلتفرم» فقط پس از ارجاع
    assert _msg(client, a["admin"], tid, "پیام به پلتفرم", "staff").status_code == 400

    # یادداشت داخلی و پاسخ به مشتری
    _msg(client, a["admin"], tid, "یادداشت: عکس را بررسی کنیم", "side")
    replied = _msg(client, a["admin"], tid, "پوزش می‌خواهیم؛ کالای جایگزین ارسال می‌شود.").json()
    assert replied["waiting_on"] == "requester"
    public = client.get(f"/public/tickets/{token}").json()
    bodies = [m["body"] for m in public["messages"]]
    assert "پوزش می‌خواهیم؛ کالای جایگزین ارسال می‌شود." in bodies and not any("یادداشت" in b for b in bodies)
    assert public["requester_mobile"] is None

    # پلتفرم قبل از ارجاع تیکت را نمی‌بیند
    assert client.get(f"/platform/tickets/{tid}", headers=_auth(helpdesk)).status_code == 404
    assert client.get("/platform/tickets/", headers=_auth(helpdesk)).json() == []

    # ارجاع ← پلتفرم
    assert client.post(f"/tickets/{tid}/escalate", json={"reason": "مشکل"}, headers=_auth(a["admin"])).status_code == 422
    esc = client.post(f"/tickets/{tid}/escalate", json={"reason": "راننده مدعی است کالا سالم تحویل شده"}, headers=_auth(a["admin"])).json()
    assert esc["handler"] == "platform" and esc["waiting_on"] == "platform"
    plist = client.get("/platform/tickets/", params={"waiting": True}, headers=_auth(helpdesk)).json()
    assert [t["id"] for t in plist] == [tid] and plist[0]["organization_name"] == "فروشگاه alpha"
    pview = client.get(f"/platform/tickets/{tid}", headers=_auth(helpdesk)).json()
    assert not any("یادداشت" in m["body"] for m in pview["messages"])          # یادداشت داخلی سازمان پنهان است
    assert [o["visibility"] for o in pview["reply_options"]] == ["staff", "side"]
    assert _msg(client, helpdesk, tid, "به مشتری", "all", url="/platform/tickets").status_code == 400

    # پاسخ پلتفرم به سازمان — مشتری نمی‌بیند
    after = _msg(client, helpdesk, tid, "عکس تحویل راننده را بفرستید.", "staff", url="/platform/tickets").json()
    assert after["waiting_on"] == "org"
    assert "عکس تحویل راننده را بفرستید." not in [m["body"] for m in client.get(f"/public/tickets/{token}").json()["messages"]]
    assert "عکس تحویل راننده را بفرستید." in [m["body"] for m in client.get(f"/tickets/{tid}", headers=_auth(a["admin"])).json()["messages"]]

    # پایان بررسی پلتفرم ← برگشت به سازمان؛ سازمان حل‌شده اعلام می‌کند
    back = client.post(f"/platform/tickets/{tid}/resolve", headers=_auth(helpdesk)).json()
    assert back["handler"] == "org" and back["status"] == "open"
    done = client.post(f"/tickets/{tid}/resolve", headers=_auth(a["admin"])).json()
    assert done["status"] == "resolved" and done["waiting_on"] == "none"

    # پیام مشتری تیکت را دوباره باز می‌کند؛ بعد از بستن پیامی پذیرفته نمی‌شود
    reopened = client.post(f"/public/tickets/{token}/messages", data={"body": "هنوز جایگزین نرسیده"}).json()
    assert reopened["status"] == "open" and reopened["waiting_on"] == "org"
    assert client.post(f"/tickets/{tid}/close", headers=_auth(a["admin"])).json()["status"] == "closed"
    assert client.post(f"/public/tickets/{token}/messages", data={"body": "سلام"}).status_code == 400
    assert _msg(client, a["admin"], tid, "سلام").status_code == 400


def test_tenant_isolation_and_attachments(env):
    client, db, w, platform, helpdesk = env
    a, b = w["alpha"], w["beta"]
    created = _customer_ticket(client, a["order"], file=PNG).json()
    tid, token, mid = created["id"], created["access_token"], created["messages"][0]["id"]
    assert client.get(f"/tickets/{tid}", headers=_auth(b["admin"])).status_code == 404
    assert client.get("/tickets/", headers=_auth(b["admin"])).json() == []
    # پیوست: مشتری با لینک، سازمان خودش؛ نه سازمان دیگر
    assert client.get(f"/public/tickets/{token}/messages/{mid}/attachment").content == PNG
    assert client.get(f"/tickets/{tid}/messages/{mid}/attachment", headers=_auth(a["admin"])).status_code == 200
    assert client.get(f"/tickets/{tid}/messages/{mid}/attachment", headers=_auth(b["admin"])).status_code == 404
    # پیوست یادداشت داخلی برای مشتری قابل دریافت نیست
    note = client.post(f"/tickets/{tid}/messages", data={"body": "داخلی", "visibility": "side"},
                       files={"file": ("n.png", PNG, "image/png")}, headers=_auth(a["admin"])).json()
    note_id = note["messages"][-1]["id"]
    assert client.get(f"/public/tickets/{token}/messages/{note_id}/attachment").status_code == 404
    assert client.get("/public/tickets/not-a-token").status_code == 404


def test_driver_tickets_go_to_own_org_only(env):
    client, db, w, platform, helpdesk = env
    a = w["alpha"]
    res = client.post("/tickets/", data={"category": "payment", "body": "پورسانت دیروز ثبت نشده", "order_id": a["order"].id},
                      headers=_auth(a["ali"]))
    assert res.status_code == 201, res.text
    t = res.json()
    assert (t["source"], t["handler"], t["waiting_on"], t["subject"]) == ("driver", "org", "org", "پورسانت و تسویه")
    # راننده دیگر نه تیکت را می‌بیند و نه با سفارش دیگران تیکت می‌سازد
    assert client.get(f"/tickets/{t['id']}", headers=_auth(a["sara"])).status_code == 404
    assert client.get("/tickets/", headers=_auth(a["sara"])).json() == []
    assert client.post("/tickets/", data={"category": "order_issue", "body": "سفارش", "order_id": a["order"].id},
                       headers=_auth(a["sara"])).status_code == 404
    assert client.post("/tickets/", data={"category": "technical", "body": "خطا"}, headers=_auth(a["ali"])).status_code == 400
    # سازمان پاسخ می‌دهد ← نوبت راننده (نشان در پنل راننده)
    _msg(client, a["admin"], t["id"], "بررسی شد؛ فردا واریز می‌شود.")
    assert client.get("/tickets/summary", headers=_auth(a["ali"])).json()["needs_action"] == 1
    driver_view = client.get(f"/tickets/{t['id']}", headers=_auth(a["ali"])).json()
    assert driver_view["can_resolve"] is True and driver_view["can_escalate"] is False
    assert client.post(f"/tickets/{t['id']}/resolve", headers=_auth(a["ali"])).json()["status"] == "resolved"


def test_org_ticket_to_platform_and_management(env):
    client, db, w, platform, helpdesk = env
    a = w["alpha"]
    res = client.post("/tickets/", data={"category": "technical", "subject": "خروجی اکسل باز نمی‌شود", "body": "فایل خالی است",
                                         "priority": "urgent"}, headers=_auth(a["manager"]))
    assert res.status_code == 201, res.text
    t = res.json()
    assert (t["source"], t["handler"], t["waiting_on"], t["priority"]) == ("org", "platform", "platform", "urgent")
    assert client.get("/platform/tickets/summary", headers=_auth(platform)).json()["needs_action"] == 1
    assert client.post("/tickets/", data={"category": "other", "body": "x"}, headers=_auth(helpdesk)).status_code in (401, 403)
    reply = _msg(client, helpdesk, t["id"], "نسخه جدید منتشر شد؛ دوباره امتحان کنید.", "all", url="/platform/tickets").json()
    assert reply["waiting_on"] == "requester"
    assert "نسخه جدید منتشر شد؛ دوباره امتحان کنید." in [m["body"] for m in client.get(f"/tickets/{t['id']}", headers=_auth(a["admin"])).json()["messages"]]
    # سازمان تیکت خودش را حل‌شده اعلام می‌کند؛ اولویت/مسئول فقط برای تیکت‌های مشتری و راننده
    assert client.patch(f"/tickets/{t['id']}", json={"priority": "normal"}, headers=_auth(a["admin"])).status_code == 403
    assert client.post(f"/tickets/{t['id']}/resolve", headers=_auth(a["admin"])).json()["status"] == "resolved"

    customer = _customer_ticket(client, a["order"], category="delay", body="سفارش هنوز نرسیده است").json()
    assigned = client.patch(f"/tickets/{customer['id']}", json={"assignee_id": a["manager"].id, "priority": "urgent"},
                            headers=_auth(a["admin"])).json()
    assert assigned["assignee_id"] == a["manager"].id and assigned["priority"] == "urgent"
    assert client.patch(f"/tickets/{customer['id']}", json={"assignee_id": a["ali"].id}, headers=_auth(a["admin"])).status_code == 400
