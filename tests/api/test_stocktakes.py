"""
مرحله ۱۲: انبارگردانی — شمارش کور، اصلاح بر مبنای موجودی لحظه شمارش (عملیات متوقف نمی‌شود)،
شمارش مجدد، تأیید ادمین با گردش «انبارگردانی»، دوره و سررسید.
"""
from datetime import timedelta

import pytest

from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import Inventory, Organization, Product, RoleEnum, StockMovement, User, Warehouse
from app.services import stock_ledger


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


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
        tehran = Warehouse(name="انبار تهران", province="تهران", city="تهران")
        tabriz = Warehouse(name="انبار تبریز", province="آذربایجان شرقی", city="تبریز")
        db.add_all([tehran, tabriz])
        db.commit()
        admin = User(username=f"{slug}_admin", email=f"{slug}@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x", full_name="ادمین")
        mgr = User(username=f"{slug}_mgr", email=f"{slug}m@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password="x",
                   warehouse_id=tehran.id, full_name="مدیر تهران")
        mgr2 = User(username=f"{slug}_mgr2", email=f"{slug}m2@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password="x", warehouse_id=tabriz.id)
        products = {name: Product(name=name, sku=f"{slug}-{i}", price=100_000 * (i + 1), weight_kg=1)
                    for i, name in enumerate(("برنج", "روغن", "شکر", "چای"))}
        db.add_all([admin, mgr, mgr2, *products.values()])
        db.commit()
        inv = {}
        for name, qty in (("برنج", 50), ("روغن", 20), ("شکر", 0)):
            inv[name] = Inventory(product_id=products[name].id, warehouse_id=tehran.id, quantity=qty)
            db.add(inv[name])
        db.commit()
        world[slug] = dict(org=org, tehran=tehran, tabriz=tabriz, admin=admin, mgr=mgr, mgr2=mgr2, products=products, inv=inv)
        set_tenant(db, None)
    try:
        yield client, db, world
    finally:
        db.close()


def _line(detail, name):
    return next(l for l in detail["lines"] if l["product_name"] == name)


def _count(client, user, st, name, qty):
    res = client.put(f"/stocktakes/{st['id']}/lines/{_line(st, name)['id']}", json={"counted_qty": qty}, headers=_auth(user))
    assert res.status_code == 200, res.text
    return res.json()


def _ship(db, org, inventory, qty):
    """خروج کالا بعد از شمارش (مثل ارسال سفارش) — عملیات انبار در طول انبارگردانی ادامه دارد."""
    set_tenant(db, org.id)
    inv = db.get(Inventory, inventory.id)
    stock_ledger.record(db, inv, -qty, "order_out", reason="سفارش آزمون")
    db.commit()
    set_tenant(db, None)


def test_full_flow_blind_count_recount_and_approval(env):
    client, db, w = env
    a = w["alpha"]
    res = client.post("/stocktakes/", json={"warehouse_id": a["tehran"].id}, headers=_auth(a["mgr"]))
    assert res.status_code == 201, res.text
    st = res.json()
    assert st["code"].startswith("ST-") and st["lines_total"] == 3 and st["status"] == "counting"
    # یک انبارگردانی فعال در هر انبار؛ مدیر انبار دیگر دسترسی ندارد
    assert client.post("/stocktakes/", json={"warehouse_id": a["tehran"].id}, headers=_auth(a["admin"])).status_code == 400
    assert client.post("/stocktakes/", json={"warehouse_id": a["tehran"].id}, headers=_auth(a["mgr2"])).status_code == 403
    assert client.get(f"/stocktakes/{st['id']}", headers=_auth(a["mgr2"])).status_code == 404

    # شمارش کور: عدد سیستم برای هیچ‌کس نمایش داده نمی‌شود
    st = _count(client, a["mgr"], st, "برنج", 47)
    assert all(l["expected_qty"] is None for l in st["lines"]) and st["revealed"] is False
    admin_view = client.get(f"/stocktakes/{st['id']}", headers=_auth(a["admin"])).json()
    assert all(l["expected_qty"] is None for l in admin_view["lines"])
    assert client.post(f"/stocktakes/{st['id']}/submit", headers=_auth(a["mgr"])).status_code == 400   # همه شمرده نشده

    st = _count(client, a["mgr"], st, "روغن", 20)
    st = _count(client, a["mgr"], st, "شکر", 0)
    # کالای پیداشده خارج از فهرست
    found = client.post(f"/stocktakes/{st['id']}/lines", json={"product_id": a["products"]["چای"].id, "counted_qty": 4}, headers=_auth(a["mgr"]))
    assert found.status_code == 200 and _line(found.json(), "چای")["added_during_count"] is True
    assert client.post(f"/stocktakes/{st['id']}/lines", json={"product_id": a["products"]["چای"].id, "counted_qty": 4},
                       headers=_auth(a["mgr"])).status_code == 400
    # بعد از شمارش برنج، ۵ کیسه ارسال شد (عملیات متوقف نیست)
    _ship(db, a["org"], a["inv"]["برنج"], 5)

    sub = client.post(f"/stocktakes/{st['id']}/submit", headers=_auth(a["mgr"])).json()
    assert sub["status"] == "review" and sub["can_count"] is False
    assert client.post(f"/stocktakes/{st['id']}/approve", json={}, headers=_auth(a["mgr"])).status_code == 403
    assert all(l["expected_qty"] is None for l in client.get(f"/stocktakes/{st['id']}", headers=_auth(a["mgr"])).json()["lines"])

    review = client.get(f"/stocktakes/{st['id']}", headers=_auth(a["admin"])).json()
    rice = _line(review, "برنج")
    assert review["revealed"] and (rice["expected_qty"], rice["variance"], rice["variance_value"]) == (50, -3, -300000)
    assert review["variance_lines"] == 2 and review["shortage_qty"] == 3 and review["surplus_qty"] == 4 and review["accuracy"] == 50.0

    # شمارش مجدد برنج ← برمی‌گردد به شمارش، شمارش قبلی نگه داشته می‌شود
    again = client.post(f"/stocktakes/{st['id']}/recount", json={"line_ids": [rice["id"]], "note": "قفسه پشتی را هم بشمارید"},
                        headers=_auth(a["admin"])).json()
    assert again["status"] == "counting"
    assert (_line(again, "برنج")["previous_count"], _line(again, "برنج")["counted_qty"]) == (47, None)
    st = _count(client, a["mgr"], again, "برنج", 43)            # موجودی سیستم الان ۴۵ است
    client.post(f"/stocktakes/{st['id']}/submit", headers=_auth(a["mgr"]))

    done = client.post(f"/stocktakes/{st['id']}/approve", json={"reasons": {str(rice["id"]): "loss"}}, headers=_auth(a["admin"])).json()
    assert done["status"] == "approved"
    assert (_line(done, "برنج")["adjustment"], _line(done, "برنج")["variance_reason"]) == (-2, "loss")
    assert _line(done, "چای")["adjustment"] == 4 and _line(done, "روغن")["adjustment"] == 0

    set_tenant(db, a["org"].id)
    db.expire_all()
    stock = {inv.product_id: inv.quantity for inv in db.query(Inventory).filter(Inventory.warehouse_id == a["tehran"].id).all()}
    assert stock[a["products"]["برنج"].id] == 43 and stock[a["products"]["چای"].id] == 4
    moves = db.query(StockMovement).filter(StockMovement.movement_type == "stocktake").all()
    assert len(moves) == 2 and all(m.reference_type == "stocktake" for m in moves) and any("مفقودی" in m.reason for m in moves)
    set_tenant(db, None)
    # بعد از تأیید، دیگر قابل تغییر نیست
    assert client.post(f"/stocktakes/{st['id']}/cancel", headers=_auth(a["admin"])).status_code == 400


def test_adjustment_never_drives_stock_negative(env):
    client, db, w = env
    a = w["alpha"]
    st = client.post("/stocktakes/", json={"warehouse_id": a["tehran"].id, "scope": "partial",
                                           "product_ids": [a["products"]["روغن"].id]}, headers=_auth(a["admin"])).json()
    assert st["lines_total"] == 1 and st["scope"] == "partial"
    st = _count(client, a["admin"], st, "روغن", 15)              # سیستم ۲۰ ← کسری ۵
    _ship(db, a["org"], a["inv"]["روغن"], 18)                   # بعد از شمارش ۱۸ عدد خارج شد ← ۲ مانده
    client.post(f"/stocktakes/{st['id']}/submit", headers=_auth(a["admin"]))
    review = client.get(f"/stocktakes/{st['id']}", headers=_auth(a["admin"])).json()
    assert review["self_review"] is True                         # هشدار: تأییدکننده خودش شمرده
    done = client.post(f"/stocktakes/{st['id']}/approve", json={}, headers=_auth(a["admin"])).json()
    assert _line(done, "روغن")["adjustment"] == -2 and _line(done, "روغن")["variance_reason"] == "unknown"
    set_tenant(db, a["org"].id)
    db.expire_all()
    assert db.get(Inventory, a["inv"]["روغن"].id).quantity == 0
    set_tenant(db, None)


def test_overview_interval_cancel_and_isolation(env):
    client, db, w = env
    a, b = w["alpha"], w["beta"]
    assert client.put(f"/stocktakes/warehouses/{a['tehran'].id}/interval", json={"days": 30}, headers=_auth(a["mgr"])).status_code == 403
    assert client.put(f"/stocktakes/warehouses/{a['tehran'].id}/interval", json={"days": 3}, headers=_auth(a["admin"])).status_code == 422
    ov = client.put(f"/stocktakes/warehouses/{a['tehran'].id}/interval", json={"days": 30}, headers=_auth(a["admin"])).json()
    tehran = next(o for o in ov if o["warehouse_id"] == a["tehran"].id)
    assert tehran["interval_days"] == 30 and tehran["overdue"] is True and tehran["items"] == 3   # هرگز انبارگردانی نشده
    assert client.get("/stocktakes/summary", headers=_auth(a["admin"])).json()["count"] == 1
    # مدیر انبار فقط انبار خودش را می‌بیند
    assert [o["warehouse_id"] for o in client.get("/stocktakes/overview", headers=_auth(a["mgr"])).json()] == [a["tehran"].id]

    st = client.post("/stocktakes/", json={"warehouse_id": a["tehran"].id}, headers=_auth(a["mgr"])).json()
    assert client.get("/stocktakes/summary", headers=_auth(a["mgr"])).json()["count"] == 1
    ov = client.get("/stocktakes/overview", headers=_auth(a["admin"])).json()
    assert next(o for o in ov if o["warehouse_id"] == a["tehran"].id)["overdue"] is False      # انبارگردانی فعال دارد
    assert client.get(f"/stocktakes/{st['id']}", headers=_auth(b["admin"])).status_code == 404
    assert client.get("/stocktakes/", headers=_auth(b["admin"])).json() == []
    assert client.post(f"/stocktakes/{st['id']}/cancel", headers=_auth(a["mgr"])).status_code == 403
    assert client.post(f"/stocktakes/{st['id']}/cancel", headers=_auth(a["admin"])).json()["status"] == "canceled"
    # انبار خالی قابل انبارگردانی کامل نیست
    assert client.post("/stocktakes/", json={"warehouse_id": a["tabriz"].id}, headers=_auth(a["admin"])).status_code == 400
