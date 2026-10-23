"""
نقطه سفارش با فرمول و برآورد سرمایه خرید:
  - فرمول‌ها با محاسبه دستی (z، موجودی اطمینان، ROP، EOQ، Holt، ماه‌های شمسی، بهای آینده و تورم)
  - تقاضا فقط از خروج/برگشت سفارش، روزهای بی‌فروش صفر، کالای تازه از اولین گردشش
  - حالت خودکار نقطه سفارش را عوض می‌کند؛ داده ناکافی ← عدد دستی می‌ماند
  - دسترسی: مدیر انبار فقط انبار خودش، سیاست و برنامه سرمایه فقط ادمین، جداسازی سازمان‌ها
  - شبیه‌سازی خرید: سفارش در ماه نیاز، بهای خرید ثبت‌شده و تورم
"""
import math
from datetime import date, datetime, time, timedelta

import pytest

from app.core.security import create_access_token
from app.core.tenancy import set_tenant
from app.models import Inventory, Organization, Product, ProductPrice, RoleEnum, User, Warehouse
from app.services import dispatch_service, replenishment_service as rs, stock_ledger


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.username, user.id, timedelta(minutes=5))}"}


# ---------------------------------------------------------------------------
# فرمول‌ها
# ---------------------------------------------------------------------------
def test_z_score_and_rop_formula_match_hand_calculation():
    assert rs.z_score(0.95) == pytest.approx(1.6449, abs=1e-3)
    assert rs.z_score(0.99) == pytest.approx(2.3263, abs=1e-3)
    series = [8.0, 12.0] * 30                           # میانگین ۱۰، انحراف معیار نمونه‌ای ≈ ۲٫۰۱۷
    policy = dict(rs.DEFAULT_POLICY)
    r = rs.compute_rop(series, lead_time=7, lead_time_std=2, service_level=0.95, policy=policy, unit_cost=None)
    std = math.sqrt(sum((x - 10) ** 2 for x in series) / 59)
    safety = 1.6449 * math.sqrt(7 * std ** 2 + 100 * 4)
    assert r.avg_daily == pytest.approx(10) and r.std_daily == pytest.approx(std)
    assert r.safety_stock == math.ceil(safety)
    assert r.rop == math.ceil(70 + safety)
    # بدون هزینه سفارش: ۳۰ روز پوشش
    assert (r.order_qty, r.order_qty_method, r.max_stock) == (300, "cover", r.rop + 300)
    assert r.sufficient


def test_eoq_when_ordering_cost_and_unit_cost_known():
    policy = {**rs.DEFAULT_POLICY, "ordering_cost": 2_000_000, "holding_rate": 0.25}
    r = rs.compute_rop([10.0] * 30, lead_time=5, lead_time_std=0, service_level=0.95, policy=policy, unit_cost=400_000)
    assert r.order_qty_method == "eoq"
    assert r.order_qty == math.ceil(math.sqrt(2 * 3650 * 2_000_000 / 100_000))
    # تقاضای ثابت و زمان تأمین قطعی ← موجودی اطمینان صفر
    assert r.safety_stock == 0 and r.rop == 50


def test_no_demand_and_short_history():
    r = rs.compute_rop([0.0] * 40, lead_time=7, lead_time_std=2, service_level=0.95, policy=dict(rs.DEFAULT_POLICY), unit_cost=1)
    assert (r.rop, r.safety_stock, r.order_qty) == (0, 0, 0)
    short = rs.compute_rop([5.0] * 5, lead_time=7, lead_time_std=2, service_level=0.95, policy=dict(rs.DEFAULT_POLICY), unit_cost=1)
    assert short.sufficient is False


def test_holt_follows_trend_but_damps_it():
    rising = rs.holt_forecast([10, 12, 14, 16, 18, 20], 3)
    assert rising[0] > 20 and rising[2] > rising[0]
    assert rising[2] - rising[1] < rising[1] - rising[0]            # روند میرا
    assert rs.holt_forecast([30, 20, 10, 0, 0], 4)[-1] >= 0         # منفی نمی‌شود
    assert rs.holt_forecast([7], 2) == [7, 7]


def test_future_months_are_jalali_and_first_is_partial():
    months = rs.future_months(date(2026, 10, 19), 3)                  # ۲۷ مهر ۱۴۰۵
    assert [m["key"] for m in months] == ["1405-07", "1405-08", "1405-09"]
    assert months[0]["days"] == 4 and months[0]["full_days"] == 30     # ۲۷ تا ۳۰ مهر
    assert months[1]["start"] == date(2026, 10, 23) and months[1]["days"] == 30


def test_cost_book_uses_scheduled_cost_and_inflation():
    today = date(2026, 10, 19)
    rows = {1: [ProductPrice(product_id=1, effective_from=date(2026, 1, 1), base_price=200, final_price=200, cost_price=150),
                ProductPrice(product_id=1, effective_from=date(2026, 12, 1), base_price=260, final_price=260, cost_price=180)],
            2: [ProductPrice(product_id=2, effective_from=date(2026, 1, 1), base_price=100, final_price=100, cost_price=None)]}
    book = rs.CostBook(rows=rows, fallback={1: 200, 2: 100, 3: 50}, today=today, growth=0.03)
    assert book.at(1, today) == pytest.approx(150)
    assert book.at(1, today + timedelta(days=30.44 * 1)) == pytest.approx(150 * 1.03, rel=1e-3)
    assert book.at(1, date(2026, 12, 1)) == pytest.approx(180)                        # قیمت آینده ثبت‌شده
    assert book.estimated(1) is False and book.estimated(2) is True and book.estimated(3) is True
    assert book.at(3, today) == 50                                                      # بدون ردیف قیمت: قیمت فروش


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def _backdate(db, inv, day: date, change: int, kind: str = "order_out"):
    """یک گردش با تاریخ روز محلی گذشته (ظهر به وقت ایران) — تاریخ پیش از ذخیره تعیین می‌شود (گردش ثبت‌شده تغییرناپذیر است)."""
    movement = stock_ledger.record(db, inv, change, kind, reason="آزمون")
    movement.created_at = dispatch_service.local_to_utc(datetime.combine(day, time(12)))
    db.flush()
    return movement


@pytest.fixture()
def env(api_env):
    client, Session = api_env
    db = Session()
    world = {}
    today = rs.today_local()
    for slug in ("alpha", "beta"):
        org = Organization(name=f"فروشگاه {slug}", slug=slug)
        db.add(org)
        db.commit()
        set_tenant(db, org.id)
        tehran = Warehouse(name="انبار تهران", province="تهران", city="تهران")
        tabriz = Warehouse(name="انبار تبریز", province="آذربایجان شرقی", city="تبریز")
        db.add_all([tehran, tabriz])
        db.commit()
        admin = User(username=f"{slug}_admin", email=f"{slug}@x.io", role=RoleEnum.ORG_ADMIN, hashed_password="x")
        mgr = User(username=f"{slug}_mgr", email=f"{slug}m@x.io", role=RoleEnum.WAREHOUSE_MANAGER, hashed_password="x", warehouse_id=tehran.id)
        rice = Product(name="برنج", sku=f"{slug}-RICE", price=500_000, weight_kg=10, category="غذایی")
        tea = Product(name="چای", sku=f"{slug}-TEA", price=300_000, weight_kg=1, category="غذایی")
        new = Product(name="کالای تازه", sku=f"{slug}-NEW", price=100_000, weight_kg=1)
        db.add_all([admin, mgr, rice, tea, new])
        db.commit()
        db.add(ProductPrice(product_id=rice.id, effective_from=today - timedelta(days=200), base_price=500_000, final_price=500_000, cost_price=400_000))
        inv_rice = Inventory(product_id=rice.id, warehouse_id=tehran.id, quantity=0)
        inv_tea = Inventory(product_id=tea.id, warehouse_id=tabriz.id, quantity=0)
        inv_new = Inventory(product_id=new.id, warehouse_id=tehran.id, quantity=0)
        db.add_all([inv_rice, inv_tea, inv_new])
        db.flush()
        # ۶۰ روز گذشته: برنج یک روز ۸ و یک روز ۱۲ (میانگین ۱۰)؛ موجودی اولیه کافی
        _backdate(db, inv_rice, today - timedelta(days=61), 2000, "receipt")
        for i in range(60, 0, -1):
            _backdate(db, inv_rice, today - timedelta(days=i), -(8 if i % 2 else 12))
        _backdate(db, inv_rice, today - timedelta(days=3), 5, "order_return")       # برگشت از تقاضا کم می‌شود
        _backdate(db, inv_rice, today - timedelta(days=2), -40, "transfer_out")     # انتقال تقاضا نیست
        # چای (انبار تبریز، بدون بهای خرید ثبت‌شده): ۳۰ روز، هر روز ۱
        _backdate(db, inv_tea, today - timedelta(days=31), 30, "receipt")
        for i in range(30, 0, -1):
            _backdate(db, inv_tea, today - timedelta(days=i), -1)
        # کالای تازه: فقط ۵ روز سابقه
        _backdate(db, inv_new, today - timedelta(days=6), 100, "receipt")
        for i in range(5, 0, -1):
            _backdate(db, inv_new, today - timedelta(days=i), -3)
        db.commit()
        world[slug] = dict(org=org, tehran=tehran, tabriz=tabriz, admin=admin, mgr=mgr, rice=inv_rice, tea=inv_tea, new=inv_new)
        set_tenant(db, None)
    try:
        yield client, db, world
    finally:
        db.close()


def _item(body, name, warehouse=None):
    return next(i for i in body["items"] if i["name"] == name and (warehouse is None or i["warehouse"] == warehouse))


def test_items_show_formula_from_ledger_demand(env):
    client, db, w = env
    a = w["alpha"]
    res = client.get("/replenishment/items", headers=_auth(a["admin"]))
    assert res.status_code == 200, res.text
    body = res.json()
    rice = _item(body, "برنج")
    calc = rice["calc"]
    # ۹۰ روز تاریخچه ولی کالا از ۶۱ روز پیش فعال است؛ دیروز آخرین روز کامل ← ۶۱ روز (روز ورود بی‌فروش)
    assert calc["data_days"] == 61 and calc["sufficient"] is True
    total = sum(8 if i % 2 else 12 for i in range(1, 61)) - 5
    assert calc["avg_daily_demand"] == pytest.approx(total / 61, abs=1e-3)
    assert rice["effective"]["source"]["lead_time_days"] == "policy" and rice["effective"]["lead_time_days"] == 7
    assert calc["rop"] > calc["safety_stock"] > 0
    assert rice["rop_mode"] == "manual" and rice["reorder_point"] == 10      # تا وقتی خودکار نشود، عدد دستی
    assert _item(body, "کالای تازه")["calc"]["sufficient"] is False
    assert body["summary"]["total"] == 3 and body["summary"]["insufficient"] == 1
    # جداسازی سازمان‌ها
    assert all(not i["sku"].startswith("beta") for i in body["items"])


def test_auto_mode_updates_reorder_point_and_alert_logic(env):
    client, db, w = env
    a = w["alpha"]
    res = client.put(f"/replenishment/items/{a['rice'].id}", json={"rop_mode": "auto", "lead_time_days": 10, "service_level": 0.99},
                     headers=_auth(a["admin"]))
    assert res.status_code == 200, res.text
    item = res.json()
    assert item["rop_mode"] == "auto" and item["reorder_point"] == item["calc"]["rop"]
    assert item["effective"]["source"]["lead_time_days"] == "item" and item["calc"]["z"] == pytest.approx(2.326, abs=1e-3)
    set_tenant(db, a["org"].id)
    db.expire_all()
    inv = db.get(Inventory, a["rice"].id)
    assert inv.reorder_point == item["calc"]["rop"] and inv.safety_stock == item["calc"]["safety_stock"]
    set_tenant(db, None)
    # عدد دستی در حالت خودکار پذیرفته نمی‌شود
    bad = client.put(f"/replenishment/items/{a['rice'].id}", json={"reorder_point": 5}, headers=_auth(a["admin"]))
    assert bad.status_code == 400
    # کالای کم‌سابقه نمی‌تواند خودکار شود
    short = client.put(f"/replenishment/items/{a['new'].id}", json={"rop_mode": "auto"}, headers=_auth(a["admin"]))
    assert short.status_code == 400 and "روز" in short.json()["detail"]
    # برگشت به دستی و عدد دلخواه
    manual = client.put(f"/replenishment/items/{a['rice'].id}", json={"rop_mode": "manual", "reorder_point": 77}, headers=_auth(a["admin"]))
    assert manual.status_code == 200 and manual.json()["reorder_point"] == 77


def test_apply_auto_skips_short_history_and_policy_recalculates(env):
    client, db, w = env
    a = w["alpha"]
    res = client.post("/replenishment/items/apply-auto", json={}, headers=_auth(a["admin"]))
    assert res.status_code == 200 and res.json() == {"switched": 2, "skipped": 1}
    before = _item(client.get("/replenishment/items", headers=_auth(a["admin"])).json(), "برنج")["reorder_point"]
    pol = client.put("/replenishment/policy", json={"lead_time_days": 20}, headers=_auth(a["admin"]))
    assert pol.status_code == 200 and pol.json()["lead_time_days"] == 20
    after = _item(client.get("/replenishment/items", headers=_auth(a["admin"])).json(), "برنج")["reorder_point"]
    assert after > before                                     # زمان تأمین بیشتر ← نقطه سفارش بالاتر
    bad = client.put("/replenishment/policy", json={"history_days": 20, "min_history_days": 30}, headers=_auth(a["admin"]))
    assert bad.status_code == 400


def test_manager_scope_and_permissions(env):
    client, db, w = env
    a = w["alpha"]
    body = client.get("/replenishment/items", headers=_auth(a["mgr"])).json()
    assert {i["warehouse"] for i in body["items"]} == {"انبار تهران"}
    # حتی با درخواست انبار دیگر، فقط انبار خودش
    other = client.get(f"/replenishment/items?warehouse_id={a['tabriz'].id}", headers=_auth(a["mgr"])).json()
    assert {i["warehouse"] for i in other["items"]} == {"انبار تهران"}
    assert client.put(f"/replenishment/items/{a['tea'].id}", json={"lead_time_days": 3}, headers=_auth(a["mgr"])).status_code == 403
    assert client.put(f"/replenishment/items/{a['rice'].id}", json={"lead_time_days": 3}, headers=_auth(a["mgr"])).status_code == 200
    assert client.put("/replenishment/policy", json={"lead_time_days": 3}, headers=_auth(a["mgr"])).status_code == 403
    assert client.get("/replenishment/capital-plan", headers=_auth(a["mgr"])).status_code == 403
    # ردیف سازمان دیگر پیدا نمی‌شود
    b = w["beta"]
    assert client.put(f"/replenishment/items/{b['rice'].id}", json={"lead_time_days": 3}, headers=_auth(a["admin"])).status_code == 404


def test_capital_plan_simulates_purchases_with_cost_and_inflation(env):
    client, db, w = env
    a = w["alpha"]
    res = client.get("/replenishment/capital-plan?months=8&price_growth=0", headers=_auth(a["admin"]))
    assert res.status_code == 200, res.text
    plan = res.json()
    assert len(plan["months"]) == 8 and plan["assumptions"]["price_growth_monthly"] == 0
    rice = next(i for i in plan["items"] if i["name"] == "برنج")
    assert rice["unit_cost_now"] == 400_000 and rice["cost_estimated"] is False
    # برنج: ۲۰۰۰ − ۵۹۵ − ۴۰ = ۱۳۶۵ موجود، ~۱۰ در روز ← در ۸ ماه خرید لازم می‌شود؛ هر واحد ۴۰۰ هزار ریال
    assert rice["total_units"] > 0 and rice["total_capital"] == rice["total_units"] * 400_000
    assert plan["summary"]["total_capital"] == sum(m["capital"] for m in plan["months"])
    assert plan["months"][-1]["cumulative"] == plan["summary"]["total_capital"]
    # چای قیمت خرید ثبت‌شده ندارد ← تخمین از قیمت فروش
    tea = next(i for i in plan["items"] if i["name"] == "چای")
    assert tea["cost_estimated"] is True and plan["summary"]["items_cost_estimated"] >= 1
    # تورم بیشتر ← سرمایه بیشتر
    inflated = client.get("/replenishment/capital-plan?months=8&price_growth=0.1", headers=_auth(a["admin"])).json()
    assert inflated["summary"]["total_capital"] >= plan["summary"]["total_capital"]
    # فیلتر انبار
    tabriz = client.get(f"/replenishment/capital-plan?months=2&warehouse_id={a['tabriz'].id}", headers=_auth(a["admin"])).json()
    assert {i["warehouse"] for i in tabriz["items"]} <= {"انبار تبریز"}
    assert client.get("/replenishment/capital-plan?months=13", headers=_auth(a["admin"])).status_code == 422
