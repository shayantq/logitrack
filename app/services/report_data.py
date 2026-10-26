"""
داده گزارش‌ها (مرحله ۱۴): موجودی، سفارش‌ها، دفتر گردش و مالی حمل‌ونقل — برای اکسل/PDF با برند سازمان
و داشبورد مالی روی صفحه. همه بازه‌ها روز محلی ایران‌اند (هر دو سر شامل).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.iran import fa_digits, gregorian_to_jalali, jalali_to_gregorian
from app.core.wms import AVAILABLE, STOCK_STATUS_LABELS
from app.models import Inventory, Order, Organization, StockMovement, User, Warehouse
from app.services import catalog_service, dispatch_service
from app.services.exceptions import ConflictError, ForbiddenError
from app.services.order_service import STATUS_LABELS
from app.services.report_builder import Col, Report, Section, jalali

REPORTS = ("inventory", "orders", "ledger", "finance", "reorder", "capital", "kpi", "valuation", "health", "audit")
TITLES = {"inventory": "گزارش موجودی انبار", "orders": "گزارش سفارش‌ها", "ledger": "گزارش دفتر گردش کالا",
          "finance": "گزارش مالی حمل‌ونقل", "reorder": "گزارش نقطه سفارش و پیشنهاد خرید",
          "capital": "برآورد سرمایه خرید ماه‌های آینده", "kpi": "داشبورد شاخص‌های عملکرد انبار و ارسال",
          "valuation": "ارزش‌گذاری موجودی", "health": "کالای کم‌گردش، راکد و نزدیک به انقضا",
          "audit": "گزارش فعالیت و ممیزی"}
MOVEMENT_LABELS = {
    "initial": "موجودی اولیه", "receipt": "ورود کالا", "order_out": "خروج سفارش", "order_return": "برگشت از سفارش",
    "adjustment": "اصلاح موجودی", "damage": "ضایعات", "transfer_out": "انتقال (خروج)", "transfer_in": "انتقال (ورود)",
    "stocktake": "انبارگردانی",
}
MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


# مجوز ریز لازم برای گزارش‌های فصل‌های ۱۷، ۲۶ و ۲۸ (app/core/permissions.py)
REPORT_PERMISSIONS = {"kpi": "analytics.view", "valuation": "valuation.view", "health": "valuation.view", "audit": "audit.view"}


def check_access(user: User, report: str, db: Session | None = None) -> None:
    role = _role(user)
    if role not in ("org_admin", "warehouse_manager"):
        raise ForbiddenError("گزارش‌ها فقط برای ادمین سازمان و مدیر انبار است.")
    if report in ("finance", "capital") and role != "org_admin":
        raise ForbiddenError("گزارش مالی و برآورد سرمایه فقط برای ادمین سازمان است.")
    if report not in REPORTS:
        raise ConflictError("نوع گزارش معتبر نیست.")
    if report in REPORT_PERMISSIONS and db is not None:
        from app.services import permission_service
        permission_service.ensure(db, user, REPORT_PERMISSIONS[report])


def _range(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    today = catalog_service.today_local()
    if date_from is None:                                    # پیش‌فرض: از اول ماه شمسی جاری
        jy, jm, _ = gregorian_to_jalali(today.year, today.month, today.day)
        date_from = date(*jalali_to_gregorian(jy, jm, 1))
    start = date_from
    end = date_to or today
    if end < start:
        raise ConflictError("تاریخ پایان باید بعد از تاریخ شروع باشد.")
    if (end - start).days > 1100:
        raise ConflictError("بازه گزارش حداکثر سه سال است.")
    return start, end


def _utc_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return (dispatch_service.local_to_utc(datetime.combine(start, time.min)),
            dispatch_service.local_to_utc(datetime.combine(end + timedelta(days=1), time.min)))


def _local(dt: datetime | None) -> datetime | None:
    return dispatch_service.to_local(dispatch_service.to_utc_naive(dt)) if dt else None


def period_text(start: date, end: date) -> str:
    return f"از {jalali(start)} تا {jalali(end)}"


def _warehouse_scope(user: User, warehouse_id: int | None) -> int | None:
    return user.warehouse_id if _role(user) == "warehouse_manager" else warehouse_id


def _money(v) -> str:
    return f"{round(v or 0):,} ریال"


# ---------------------------------------------------------------------------
def inventory(db: Session, user: User, warehouse_id: int | None = None, **_) -> Report:
    wid = _warehouse_scope(user, warehouse_id)
    warehouses = {w.id: w.name for w in db.query(Warehouse).all()}
    query = db.query(Inventory).options(joinedload(Inventory.product))
    if wid:
        query = query.filter(Inventory.warehouse_id == wid)
    rows, low, value_total = [], 0, 0.0
    for inv in sorted(query.all(), key=lambda i: ((i.product.category or "") if i.product else "", i.product.name if i.product else "")):
        p = inv.product
        held = inv.stock_status != AVAILABLE
        if p is None or (held and not inv.quantity):
            continue
        qty = inv.quantity or 0
        if held:
            # موجودی قرنطینه/توقیف/معیوب: جدا نشان داده می‌شود و قابل فروش نیست
            status = STOCK_STATUS_LABELS.get(inv.stock_status, inv.stock_status)
        else:
            status = "ناموجود" if qty == 0 else ("زیر نقطه سفارش" if qty <= (inv.reorder_point or 0) else "عادی")
            low += status != "عادی"
        value = qty * (p.price or 0)
        value_total += value
        rows.append({"sku": p.sku, "name": p.name + (f" ({p.variant_label})" if p.variant_label else ""), "category": p.category or "—",
                     "origin": "وارداتی" if p.origin == "imported" else "داخلی", "warehouse": warehouses.get(inv.warehouse_id, "—"),
                     "qty": qty, "unit": p.unit or "عدد", "reorder": None if held else inv.reorder_point, "status": status,
                     "price": p.price or 0, "value": value})
    cols = [Col("sku", "کد کالا", width=12), Col("name", "نام کالا", width=28), Col("category", "گروه", width=14),
            Col("origin", "مبدأ", width=9), Col("warehouse", "انبار", width=16), Col("qty", "موجودی", "number", 10, True),
            Col("unit", "واحد", width=8), Col("reorder", "نقطه سفارش", "number", 10), Col("status", "وضعیت", width=14),
            Col("price", "قیمت فروش (ریال)", "money", 15), Col("value", "ارزش موجودی (ریال)", "money", 18, True)]
    kpis = [("ردیف موجودی", f"{len(rows):,}"), ("کل موجودی", f"{sum(r['qty'] for r in rows):,}"),
            ("ارزش کل موجودی", _money(value_total)), ("ناموجود یا زیر نقطه سفارش", f"{low:,}")]
    scope = f"انبار {warehouses.get(wid)}" if wid else "همه انبارها"
    return Report(title=TITLES["inventory"], period=f"{scope} — در تاریخ {jalali(catalog_service.today_local())}",
                  sections=[Section("موجودی کالاها", cols, rows)], kpis=kpis, landscape=True, filename="Pasineh_Inventory")


def orders(db: Session, user: User, date_from: date | None = None, date_to: date | None = None, status: str | None = None, **_) -> Report:
    start, end = _range(date_from, date_to)
    lo, hi = _utc_bounds(start, end)
    query = db.query(Order).options(joinedload(Order.vehicle), joinedload(Order.customer), selectinload(Order.items)) \
        .filter(Order.delivery_window_start >= lo, Order.delivery_window_start < hi)
    if status:
        query = query.filter(Order.status == status)
    drivers = {u.id: u.full_name or u.username for u in db.query(User).all()}
    rows = []
    for o in query.order_by(Order.delivery_window_start).all():
        rows.append({
            "code": o.tracking_code, "day": jalali(_local(o.delivery_window_start)), "customer": o.customer.name if o.customer else (o.recipient_name or "—"),
            "dest": " / ".join(x for x in (o.destination_province, o.destination_city) if x),
            "items": "، ".join(f"{i.product_name} ×{i.quantity}" for i in o.items), "qty": o.total_quantity, "weight": o.total_weight_kg,
            "goods": o.total_price, "fee": o.delivery_fee or 0, "driver": drivers.get(o.driver_id, "—"),
            "plate": o.vehicle.license_plate if o.vehicle else "—", "status": STATUS_LABELS.get(o.status, o.status),
        })
    cols = [Col("code", "کد پیگیری", width=13), Col("day", "روز تحویل", "date", 11), Col("customer", "مشتری", width=16),
            Col("dest", "مقصد", width=16), Col("items", "اقلام", width=28), Col("qty", "تعداد", "number", 8, True),
            Col("weight", "وزن (کیلو)", "number", 10, True), Col("goods", "مبلغ کالا (ریال)", "money", 16, True),
            Col("fee", "کرایه (ریال)", "money", 13, True), Col("driver", "راننده", width=14), Col("plate", "پلاک", width=14),
            Col("status", "وضعیت", width=12)]
    statuses = defaultdict(int)
    for r in rows:
        statuses[r["status"]] += 1
    kpis = [("سفارش‌ها", f"{len(rows):,}"), ("تحویل‌شده", f"{statuses.get(STATUS_LABELS['delivered'], 0):,}"),
            ("مبلغ کالا", _money(sum(r["goods"] for r in rows))), ("کرایه", _money(sum(r["fee"] for r in rows)))]
    title = TITLES["orders"] + (f" ({STATUS_LABELS.get(status, status)})" if status else "")
    return Report(title=title, period=period_text(start, end), sections=[Section("سفارش‌ها", cols, rows)], kpis=kpis,
                  landscape=True, filename="Pasineh_Orders")


def ledger(db: Session, user: User, date_from: date | None = None, date_to: date | None = None, warehouse_id: int | None = None, **_) -> Report:
    start, end = _range(date_from, date_to)
    lo, hi = _utc_bounds(start, end)
    wid = _warehouse_scope(user, warehouse_id)
    query = db.query(StockMovement).options(joinedload(StockMovement.product), joinedload(StockMovement.warehouse)) \
        .filter(StockMovement.created_at >= lo, StockMovement.created_at < hi)
    if wid:
        query = query.filter(StockMovement.warehouse_id == wid)
    users = {u.id: u.full_name or u.username for u in db.query(User).all()}
    rows = []
    for m in query.order_by(StockMovement.created_at, StockMovement.id).all():
        rows.append({"at": jalali(_local(m.created_at), True), "product": m.product.name if m.product else "—", "sku": m.product.sku if m.product else "",
                     "warehouse": m.warehouse.name if m.warehouse else "—", "type": MOVEMENT_LABELS.get(m.movement_type, m.movement_type),
                     "in": m.quantity_change if m.quantity_change > 0 else None, "out": -m.quantity_change if m.quantity_change < 0 else None,
                     "balance": m.balance_after, "reason": m.reason or "", "user": users.get(m.created_by_id, "سیستم")})
    cols = [Col("at", "زمان", "date", 15), Col("product", "کالا", width=24), Col("sku", "کد", width=11), Col("warehouse", "انبار", width=14),
            Col("type", "نوع گردش", width=14), Col("in", "ورود", "number", 9, True), Col("out", "خروج", "number", 9, True),
            Col("balance", "مانده", "number", 9), Col("reason", "شرح", width=30), Col("user", "ثبت‌کننده", width=14)]
    kpis = [("گردش‌ها", f"{len(rows):,}"), ("کل ورود", f"{sum(r['in'] or 0 for r in rows):,}"),
            ("کل خروج", f"{sum(r['out'] or 0 for r in rows):,}")]
    return Report(title=TITLES["ledger"], period=period_text(start, end), sections=[Section("گردش کالا", cols, rows)], kpis=kpis,
                  landscape=True, filename="Pasineh_Ledger")


# ---------------------------------------------------------------------------
# مالی حمل‌ونقل
# ---------------------------------------------------------------------------
def finance_data(db: Session, user: User, date_from: date | None = None, date_to: date | None = None) -> dict:
    """داده مالی سفارش‌های تحویل‌شده در بازه (بر اساس زمان تحویل)؛ برای داشبورد و فایل."""
    start, end = _range(date_from, date_to)
    lo, hi = _utc_bounds(start, end)
    delivered = db.query(Order).options(joinedload(Order.vehicle)).filter(
        Order.status == "delivered", Order.delivered_at >= lo, Order.delivered_at < hi).order_by(Order.delivered_at).all()
    failed = db.query(Order).filter(Order.status.in_(("failed", "canceled", "expired")),
                                    Order.delivery_window_start >= lo, Order.delivery_window_start < hi).count()
    users = {u.id: u.full_name or u.username for u in db.query(User).all()}
    by_driver: dict = defaultdict(lambda: {"trips": 0, "km": 0, "weight": 0.0, "fare": 0.0, "company": 0.0, "driver_share": 0.0})
    by_province: dict = defaultdict(lambda: {"trips": 0, "km": 0, "fare": 0.0, "company": 0.0})
    by_month: dict = defaultdict(lambda: {"trips": 0, "fare": 0.0, "company": 0.0, "driver_share": 0.0})
    details = []
    for o in delivered:
        fare = o.delivery_fee or 0
        company = o.commission_amount or 0
        driver_share = o.driver_earning if o.driver_earning is not None else fare - company
        km = (o.route or {}).get("total_km") or 0
        local = _local(o.delivered_at)
        jy, jm, _ = gregorian_to_jalali(local.year, local.month, local.day)
        name = users.get(o.driver_id, "بدون راننده")
        for bucket, key in ((by_driver, name), (by_province, o.destination_province or "—")):
            b = bucket[key]
            b["trips"] += 1
            b["km"] += km
            b["fare"] += fare
            b["company"] += company
            if "driver_share" in b:
                b["driver_share"] += driver_share
                b["weight"] += o.total_weight_kg or 0
        m = by_month[(jy, jm)]
        m["trips"] += 1
        m["fare"] += fare
        m["company"] += company
        m["driver_share"] += driver_share
        details.append({"day": jalali(local), "code": o.tracking_code, "driver": name, "plate": o.vehicle.license_plate if o.vehicle else "—",
                        "dest": " / ".join(x for x in (o.destination_province, o.destination_city) if x), "km": km or None,
                        "level": o.commission_level or "—", "trip": o.day_trip_number, "percent": o.commission_percent,
                        "fare": fare, "company": company, "driver_share": driver_share, "goods": o.total_price})
    total_fare = sum(d["fare"] for d in details)
    total_company = sum(d["company"] for d in details)
    total_km = sum(d["km"] or 0 for d in details)
    return {
        "start": start, "end": end,
        "kpis": {"trips": len(details), "fare": round(total_fare), "company": round(total_company),
                 "driver": round(sum(d["driver_share"] for d in details)), "km": round(total_km),
                 "avg_fare": round(total_fare / len(details)) if details else 0,
                 "fare_per_km": round(total_fare / total_km) if total_km else 0,
                 "take_rate": round(100 * total_company / total_fare, 1) if total_fare else 0, "failed": failed},
        "by_driver": sorted(({"driver": k, **{x: round(y) if isinstance(y, float) else y for x, y in v.items()}} for k, v in by_driver.items()),
                            key=lambda r: -r["fare"]),
        "by_province": sorted(({"province": k, **{x: round(y) if isinstance(y, float) else y for x, y in v.items()}} for k, v in by_province.items()),
                              key=lambda r: -r["fare"]),
        "by_month": [{"month": f"{MONTHS[jm - 1]} {fa_digits(str(jy))}", **{x: round(y) if isinstance(y, float) else y for x, y in v.items()}}
                     for (jy, jm), v in sorted(by_month.items())],
        "details": details,
    }


def finance(db: Session, user: User, date_from: date | None = None, date_to: date | None = None, **_) -> Report:
    d = finance_data(db, user, date_from, date_to)
    k = d["kpis"]
    kpis = [("سفرهای تحویل‌شده", f"{k['trips']:,}"), ("مجموع کرایه", _money(k["fare"])), ("سهم سازمان (پورسانت)", _money(k["company"])),
            ("پرداختی رانندگان", _money(k["driver"])), ("کیلومتر پیمایش", f"{k['km']:,}"), ("میانگین کرایه هر سفر", _money(k["avg_fare"])),
            ("کرایه هر کیلومتر", _money(k["fare_per_km"])), ("ناموفق / لغو", f"{k['failed']:,}")]
    sections = [
        Section("خلاصه رانندگان", [Col("driver", "راننده", width=20), Col("trips", "سفر", "number", 8, True), Col("km", "کیلومتر", "number", 10, True),
                                   Col("weight", "وزن (کیلو)", "number", 11, True), Col("fare", "کرایه (ریال)", "money", 16, True),
                                   Col("company", "سهم سازمان", "money", 16, True), Col("driver_share", "سهم راننده", "money", 16, True)],
                d["by_driver"]),
        Section("خلاصه استان مقصد", [Col("province", "استان", width=20), Col("trips", "سفر", "number", 8, True), Col("km", "کیلومتر", "number", 10, True),
                                     Col("fare", "کرایه (ریال)", "money", 16, True), Col("company", "سهم سازمان", "money", 16, True)], d["by_province"]),
        Section("روند ماهانه", [Col("month", "ماه", width=16), Col("trips", "سفر", "number", 8, True), Col("fare", "کرایه (ریال)", "money", 16, True),
                               Col("company", "سهم سازمان", "money", 16, True), Col("driver_share", "سهم رانندگان", "money", 16, True)], d["by_month"]),
        Section("جزئیات سفرها", [Col("day", "روز تحویل", "date", 11), Col("code", "کد پیگیری", width=13), Col("driver", "راننده", width=15),
                                 Col("plate", "پلاک", width=13), Col("dest", "مقصد", width=15), Col("km", "کیلومتر", "number", 9, True),
                                 Col("level", "سطح", width=6), Col("trip", "سفر روز", "number", 7), Col("percent", "درصد", "percent", 7),
                                 Col("fare", "کرایه", "money", 13, True), Col("company", "سهم سازمان", "money", 13, True),
                                 Col("driver_share", "سهم راننده", "money", 13, True)], d["details"]),
    ]
    return Report(title=TITLES["finance"], period=period_text(d["start"], d["end"]), sections=sections, kpis=kpis, landscape=True,
                  filename="Pasineh_Transport_Finance")


# ---------------------------------------------------------------------------
# نقطه سفارش و برآورد سرمایه (app/services/replenishment_service.py)
# ---------------------------------------------------------------------------
ROP_STATUS = {"out": "ناموجود", "critical": "زیر موجودی اطمینان", "reorder": "زمان سفارش", "ok": "عادی"}


def reorder(db: Session, user: User, warehouse_id: int | None = None, **_) -> Report:
    from app.services import replenishment_service
    data = replenishment_service.list_items(db, user, warehouse_id)
    pol = data["policy"]
    rows = []
    for i in data["items"]:
        c = i["calc"]
        rows.append({
            "sku": i["sku"], "name": i["name"], "warehouse": i["warehouse"] or "—", "qty": i["quantity"],
            "mode": "خودکار" if i["rop_mode"] == "auto" else "دستی", "rop": i["reorder_point"], "formula_rop": c["rop"],
            "safety": c["safety_stock"], "avg": round(c["avg_daily_demand"], 1), "std": round(c["demand_std"], 1),
            "lead": i["effective"]["lead_time_days"], "service": i["effective"]["service_level"] * 100,
            "order_qty": c["order_qty"], "cover": i["days_of_cover"] if i["days_of_cover"] is not None else "—",
            "status": ROP_STATUS[i["status"]] + ("" if c["sufficient"] else " (سابقه ناکافی)"), "buy": i["suggested_purchase"],
        })
    cols = [Col("sku", "کد کالا", width=11), Col("name", "نام کالا", width=24), Col("warehouse", "انبار", width=14),
            Col("qty", "موجودی", "number", 9, True), Col("mode", "حالت", width=8), Col("rop", "نقطه سفارش فعلی", "number", 11),
            Col("formula_rop", "نقطه سفارش فرمول", "number", 10), Col("safety", "موجودی اطمینان", "number", 10),
            Col("avg", "فروش روزانه", width=10), Col("std", "نوسان فروش", width=9),
            Col("lead", "زمان تأمین (روز)", width=10), Col("service", "سطح خدمت", "percent", 9),
            Col("order_qty", "مقدار سفارش", "number", 10), Col("cover", "روز پوشش", width=9), Col("status", "وضعیت", width=18),
            Col("buy", "پیشنهاد خرید", "number", 10, True)]
    s = data["summary"]
    kpis = [("ناموجود", f"{s['out']:,}"), ("زیر موجودی اطمینان", f"{s['critical']:,}"), ("زمان سفارش", f"{s['reorder']:,}"),
            ("خودکار", f"{s['auto']:,} از {s['total']:,}")]
    note = (f"نقطه سفارش = تقاضای دوره تأمین + موجودی اطمینان — پیش‌فرض‌ها: زمان تأمین {pol['lead_time_days']:g} روز، "
            f"سطح خدمت {pol['service_level'] * 100:g}٪، تاریخچه {pol['history_days']} روز")
    return Report(title=TITLES["reorder"], period=f"در تاریخ {jalali(catalog_service.today_local())} — {note}",
                  sections=[Section("اقلام به ترتیب اولویت خرید", cols, rows)], kpis=kpis, landscape=True,
                  filename="Pasineh_Reorder_Points")


def capital(db: Session, user: User, warehouse_id: int | None = None, months: int | None = None, **_) -> Report:
    from app.services import replenishment_service
    plan = replenishment_service.plan(db, user, months or 6, warehouse_id)
    a, s = plan["assumptions"], plan["summary"]
    month_cols = [Col("label", "ماه", width=16), Col("capital", "سرمایه خرید (ریال)", "money", 18, True),
                  Col("cumulative", "تجمعی (ریال)", "money", 18), Col("orders", "تعداد سفارش خرید", "number", 12, True),
                  Col("units", "واحد خرید", "number", 11, True), Col("demand", "تقاضای پیش‌بینی", "number", 12, True),
                  Col("stock", "ارزش موجودی پایان ماه (ریال)", "money", 20), Col("risk", "اقلام در خطر کمبود", "number", 12)]
    month_rows = [{"label": m["label"] + (" (باقی‌مانده)" if m["partial"] else ""), "capital": m["capital"], "cumulative": m["cumulative"],
                   "orders": m["orders"], "units": m["units"], "demand": m["demand_units"], "stock": m["stock_value_end"],
                   "risk": m["stockout_items"]} for m in plan["months"]]
    item_cols = [Col("sku", "کد کالا", width=11), Col("name", "نام کالا", width=24), Col("warehouse", "انبار", width=14),
                 Col("qty", "موجودی فعلی", "number", 10), Col("daily", "تقاضای روزانه پیش‌بینی", width=12),
                 Col("method", "روش پیش‌بینی", width=12), Col("cost", "بهای خرید فعلی (ریال)", "money", 15),
                 Col("units", "واحد خرید", "number", 10, True), Col("capital", "سرمایه لازم (ریال)", "money", 18, True)]
    item_rows = [{"sku": i["sku"], "name": i["name"] + (" *" if i["cost_estimated"] else ""), "warehouse": i["warehouse"] or "—",
                  "qty": i["quantity"], "daily": i["avg_daily_forecast"],
                  "method": "روند ماهانه (Holt)" if i["forecast_method"] == "holt" else "میانگین روزانه",
                  "cost": i["unit_cost_now"], "units": i["total_units"], "capital": i["total_capital"]}
                 for i in plan["items"] if i["total_capital"] > 0]
    kpis = [("کل سرمایه لازم", _money(s["total_capital"])), ("پرهزینه‌ترین ماه", s["peak_month"] or "—"),
            ("میانگین ماهانه", _money(s["average_monthly"])), ("ارزش موجودی فعلی", _money(s["current_stock_value"]))]
    period = (f"{len(plan['months'])} ماه از {jalali(catalog_service.today_local())} — تورم ماهانه بها {a['price_growth_monthly'] * 100:g}٪، "
              f"رشد ماهانه تقاضا {a['demand_growth_monthly'] * 100:g}٪ — * بهای خرید ثبت نشده؛ قیمت فروش مبنا قرار گرفت")
    return Report(title=TITLES["capital"], period=period,
                  sections=[Section("سرمایه لازم به تفکیک ماه", month_cols, month_rows),
                            Section("سرمایه لازم به تفکیک کالا", item_cols, item_rows)],
                  kpis=kpis, landscape=True, filename="Pasineh_Purchase_Capital_Plan")


def kpi(db: Session, user: User, date_from: date | None = None, date_to: date | None = None, warehouse_id: int | None = None, **_) -> Report:
    from app.services import analytics_service
    data = analytics_service.kpis(db, user, date_from=date_from, date_to=date_to, warehouse_id=warehouse_id)
    status = {"good": "در هدف", "warn": "نزدیک هدف", "bad": "دور از هدف", "none": "بدون داده"}
    rows = [{"label": k["label"], "value": "—" if k["value"] is None else f"{k['value']:g}", "unit": k["unit"],
             "target": f"{'≥' if k['higher_better'] else '≤'} {k['target']:g}", "status": status[k["status"]],
             "detail": k["detail"] or "", "hint": k["hint"]} for k in data["kpis"]]
    cols = [Col("label", "شاخص", width=20), Col("value", "مقدار", width=10), Col("unit", "واحد", width=8),
            Col("target", "هدف", width=10), Col("status", "وضعیت", width=12), Col("detail", "جزئیات", width=30),
            Col("hint", "تعریف", width=40)]
    trend = [{"day": jalali(t["day"]), "orders": t["orders"], "delivered": t["delivered"], "shipped": t["shipped_units"],
              "received": t["received_units"]} for t in data["trend"]]
    tcols = [Col("day", "روز", width=12), Col("orders", "سفارش ثبت‌شده", "number", 12, True),
             Col("delivered", "تحویل‌شده", "number", 12, True), Col("shipped", "واحد خارج‌شده", "number", 12, True),
             Col("received", "واحد واردشده", "number", 12, True)]
    snap = data["snapshot"]
    kpis = [("سفارش باز", f"{snap['open_orders']:,}"), ("واحد معوق", f"{snap['backorder_units']:,}"),
            ("جانمایی باز", f"{snap['open_putaway']:,}"), ("در انتظار بازرسی", f"{snap['pending_inspection']:,}")]
    return Report(title=TITLES["kpi"], period=period_text(data["date_from"], data["date_to"]),
                  sections=[Section("شاخص‌ها", cols, rows, totals=False), Section("روند روزانه", tcols, trend)],
                  kpis=kpis, landscape=True, filename="Pasineh_KPI")


def valuation(db: Session, user: User, date_from: date | None = None, date_to: date | None = None, warehouse_id: int | None = None, **_) -> Report:
    from app.services import valuation_service
    data = valuation_service.valuation(db, user, warehouse_id=warehouse_id, date_from=date_from, date_to=date_to)
    rows = [{"sku": r["sku"], "name": r["product_name"], "abc": r["abc_class"] or "—", "qty": r["quantity"],
             "fifo_unit": r["unit_cost"]["fifo"], "avg_unit": r["unit_cost"]["weighted_average"],
             "fifo": r["value"]["fifo"], "avg": r["value"]["weighted_average"], "std": r["value"]["standard"],
             "est": "تخمینی" if r["estimated"] else ""} for r in data["items"]]
    cols = [Col("sku", "کد کالا", width=11), Col("name", "نام کالا", width=24), Col("abc", "ABC", width=5),
            Col("qty", "مقدار", "number", 9, True), Col("fifo_unit", "بهای واحد FIFO", "money", 12),
            Col("avg_unit", "بهای واحد میانگین", "money", 12), Col("fifo", "ارزش FIFO", "money", 14, True),
            Col("avg", "ارزش میانگین موزون", "money", 14, True), Col("std", "ارزش استاندارد", "money", 14, True),
            Col("est", "بها", width=8)]
    c = data["cogs"]
    kpis = [("روش جاری", data["method_label"]), ("ارزش (روش جاری)", _money(data["selected_total"])),
            ("بهای فروش رفته FIFO", _money(c["fifo"])), ("بهای فروش رفته میانگین", _money(c["weighted_average"]))]
    return Report(title=TITLES["valuation"], period=period_text(data["date_from"], data["date_to"]),
                  sections=[Section("ارزش هر کالا به سه روش", cols, rows)], kpis=kpis, landscape=True,
                  filename="Pasineh_Inventory_Valuation")


def health(db: Session, user: User, warehouse_id: int | None = None, **_) -> Report:
    from app.services import valuation_service
    data = valuation_service.health(db, user, warehouse_id=warehouse_id)
    labels = {"slow": "کم‌گردش", "dead": "راکد", "no_sales": "بی‌فروش", "active": "فعال"}
    rows = [{"sku": i["sku"], "name": i["product_name"], "status": labels[i["status"]], "qty": i["quantity"], "value": i["value"],
             "idle": i["idle_days"] if i["idle_days"] is not None else "—",
             "last": jalali(_local(i["last_sale_at"])) if i["last_sale_at"] else "—"} for i in data["items"]]
    cols = [Col("sku", "کد کالا", width=11), Col("name", "نام کالا", width=26), Col("status", "وضعیت", width=10),
            Col("qty", "مقدار", "number", 9, True), Col("value", "ارزش", "money", 14, True), Col("idle", "روز بی‌گردشی", width=10),
            Col("last", "آخرین فروش", width=12)]
    exp = [{"sku": e["sku"] or "", "name": e["product_name"], "wh": e["warehouse_name"], "loc": e["location_code"] or "—",
            "lot": e["lot_number"] or "—", "expiry": jalali(e["expiry_date"]), "days": e["days_left"], "qty": e["quantity"],
            "value": e["value"]} for e in data["expiring"]]
    ecols = [Col("sku", "کد کالا", width=11), Col("name", "نام کالا", width=22), Col("wh", "انبار", width=14),
             Col("loc", "محل", width=10), Col("lot", "بچ", width=10), Col("expiry", "انقضا", width=11),
             Col("days", "روز مانده", "number", 9), Col("qty", "مقدار", "number", 9, True), Col("value", "ارزش", "money", 13, True)]
    kpis = [(labels[b["status"]], f"{b['count']:,} کالا — {_money(b['value'])}") for b in data["buckets"] if b["status"] != "active"]
    return Report(title=TITLES["health"], period=f"در تاریخ {jalali(catalog_service.today_local())}",
                  sections=[Section("کالای کم‌گردش، راکد و بی‌فروش", cols, rows), Section("نزدیک به انقضا و منقضی", ecols, exp)],
                  kpis=kpis, landscape=True, filename="Pasineh_Inventory_Health")


def audit(db: Session, user: User, date_from: date | None = None, date_to: date | None = None, **_) -> Report:
    from app.services import audit_service
    start, end = _range(date_from, date_to)
    rows, offset = [], 0
    while offset < 5000:
        data = audit_service.list_logs(db, user, date_from=start, date_to=end, limit=200, offset=offset)
        for r in data["items"]:
            rows.append({"at": jalali(_local(r["at"]), with_time=True), "actor": r["actor_name"] or "سیستم",
                         "category": data["categories"].get(r["category"], r["category"]), "summary": r["summary"],
                         "reason": r["reason"] or "", "ip": r["ip"] or ""})
        offset += len(data["items"])
        if offset >= data["total"] or not data["items"]:
            break
    cols = [Col("at", "زمان", width=16), Col("actor", "انجام‌دهنده", width=16), Col("category", "بخش", width=14),
            Col("summary", "چه شد", width=44), Col("reason", "چرا", width=24), Col("ip", "IP", width=13)]
    return Report(title=TITLES["audit"], period=period_text(start, end), sections=[Section("رویدادها", cols, rows, totals=False)],
                  kpis=[("تعداد رویداد", f"{len(rows):,}")], landscape=True, filename="Pasineh_Audit_Log")


BUILDERS = {"inventory": inventory, "orders": orders, "ledger": ledger, "finance": finance, "reorder": reorder, "capital": capital,
            "kpi": kpi, "valuation": valuation, "health": health, "audit": audit}


def organization(db: Session, organization_id: int) -> Organization:
    return db.get(Organization, organization_id)


def now_local() -> datetime:
    return dispatch_service.to_local(datetime.now(timezone.utc).replace(tzinfo=None))
