"""
دریافت کالای بچ‌دار، تاریخ‌دار و سریالی از صف کار اپراتور: همان check_tracking سرویس دریافت برای اپراتور هم اجرا می‌شود
و صف اپراتور این سطرها را دارد (frontend/src/pages/warehouse/MyTasksPage.tsx).
"""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import Organization, Partner, Product, RoleEnum, StockMovement, User
from tests.factories import default_warehouse


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    org = Organization(name="آلفا", slug="alpha")
    db.add(org)
    db.commit()
    set_tenant(db, org.id)
    warehouse = default_warehouse(db, org.id)
    admin = User(username="adm", email="a@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    operator = User(username="op", email="o@x.io", role=RoleEnum.WAREHOUSE_OPERATOR, hashed_password="x", warehouse_id=warehouse.id)
    products = {
        "lot": Product(name="دارو", sku="MED-1", barcode="62610001", price=1, weight_kg=1, lot_tracked=True),
        # کالای تاریخ‌دار همیشه بچ‌دار هم هست (ck_products_expiry_needs_lot)
        "expiry": Product(name="شیر", sku="MILK-1", barcode="62610002", price=1, weight_kg=1, lot_tracked=True, expiry_tracked=True),
        "serial": Product(name="گوشی", sku="PHONE-1", barcode="62610003", price=1, weight_kg=1, serial_tracked=True),
    }
    partner = Partner(code="SUP-1", name="تأمین", is_supplier=True)
    db.add_all([admin, operator, partner, *products.values()])
    db.commit()
    res = client.post("/inbound/receipts", headers=_auth(admin), json={
        "receipt_type": "purchase", "warehouse_id": warehouse.id, "partner_id": partner.id, "external_ref": "BL-T",
        "lines": [{"product_id": p.id, "expected_quantity": 10} for p in products.values()]})
    assert res.status_code == 201, res.text
    receipt = res.json()
    lines = {kind: next(ln["id"] for ln in receipt["lines"] if ln["product_id"] == p.id) for kind, p in products.items()}
    yield SimpleNamespace(client=client, db=db, operator=operator, products=products, receipt=receipt, lines=lines)
    db.close()


def _receive(env, kind, quantity=2, **line):
    body = {"lines": [{"line_id": env.lines[kind], "quantity": quantity, "entry_mode": "scan", "product_scan": env.products[kind].sku, **line}]}
    return env.client.post(f"/inbound/receipts/{env.receipt['id']}/receive", headers=_auth(env.operator), json=body)


def _received(env) -> int:
    return env.db.query(StockMovement).filter(StockMovement.movement_type == "receipt").count()


def test_operator_queue_source_lists_tracked_lines_with_their_flags(env):
    res = env.client.get("/inbound/receipts", headers=_auth(env.operator), params={"with_lines": True})
    assert res.status_code == 200, res.text
    lines = {ln["product_sku"]: ln for r in res.json() for ln in r["lines"]}
    assert lines["MED-1"]["lot_tracked"] and lines["MILK-1"]["expiry_tracked"] and lines["PHONE-1"]["serial_tracked"]


def test_lot_is_required_for_the_operator_too(env):
    assert _receive(env, "lot").status_code == 400
    assert _received(env) == 0
    assert _receive(env, "lot", lot_number="L-2026-01").status_code == 201
    assert _received(env) == 1


def test_expiry_is_required_and_past_dates_are_rejected(env):
    assert _receive(env, "expiry", lot_number="L-1").status_code == 400
    assert _receive(env, "expiry", lot_number="L-1", expiry_date=(date.today() - timedelta(days=3)).isoformat()).status_code == 400
    assert _received(env) == 0
    assert _receive(env, "expiry", lot_number="L-1", expiry_date=(date.today() + timedelta(days=90)).isoformat()).status_code == 201


@pytest.mark.parametrize("serials", [["SN-1"], ["SN-1", "SN-1"], ["SN-1", "SN-2", "SN-3"]])
def test_serial_count_must_match_and_be_unique(env, serials):
    # سریال تکراری را خود schema رد می‌کند (۴۲۲) و شمار نادرست را check_tracking (۴۰۰)
    assert _receive(env, "serial", serial_numbers=serials).status_code in (400, 422)
    assert _received(env) == 0


def test_matching_serials_are_received(env):
    assert _receive(env, "serial", serial_numbers=["SN-1", "SN-2"]).status_code == 201
    assert _received(env) >= 1


def test_tracking_fields_on_untracked_goods_are_rejected(env):
    assert _receive(env, "serial", serial_numbers=["SN-1", "SN-2"], lot_number="L-1").status_code == 400
