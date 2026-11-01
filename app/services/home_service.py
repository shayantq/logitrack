"""
صفحه خانه هر نقش (docs/operations-guide.md، مرحله ۶).

مدیرعامل: سلامت کسب‌وکار با ریزش تا فهرست مقصد. مدیر انبار: کار امروز انبار. هیچ عددی این‌جا محاسبه تازه‌ای از موجودی، کمیسیون
یا کرایه نیست و همه از همان سرویس‌هایی می‌آید که فهرست مقصد از آن‌ها می‌خواند.
سودآوری فقط از کرایه، قیمت فروش و بهای تمام‌شده موجود است و برچسب «برآورد» دارد (تصمیم ت۱۰): هزینه واقعی و فاکتور در سامانه نیست.
"""
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ACTIVE_ORDER_STATUSES, Inventory, Order, OrderItem, Product, ProductPrice, Stocktake, User, Vehicle, Warehouse
from app.models_fulfillment import Backorder, PickLine, PickList, Shipment
from app.models_operations import InboundReceipt, PutawayTask
from app.models_productivity import ACTIVE_EXCEPTION_STATUSES, OperationException
from app.services import analytics_service, dispatch_service, eta_service, location_service, report_data
from app.services.exceptions import ForbiddenError
from app.services.stock_position_service import OPEN_RECEIPT_STATUSES

WINDOW_DAYS = 30
BUSINESS_KPIS = {
    "on_time_delivery": "/app/orders?view=late",
    "order_fulfillment": "/app/analytics",
    "fill_rate": "/app/backorders",
    "failed_attempt_rate": "/app/orders?view=awaiting_resolution",
    "inventory_accuracy": "/app/stocktakes",
}
MARGIN_PRODUCTS = 5


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def _today() -> date:
    return dispatch_service.to_local(eta_service._now()).date()


def _kpis(db: Session, user: User, today: date) -> list[dict]:
    """شاخص‌های این ۳۰ روز در برابر ۳۰ روز پیش از آن."""
    start = today - timedelta(days=WINDOW_DAYS - 1)
    current = analytics_service.kpis(db, user, date_from=start, date_to=today)["kpis"]
    previous = {k["key"]: k for k in analytics_service.kpis(
        db, user, date_from=start - timedelta(days=WINDOW_DAYS), date_to=start - timedelta(days=1))["kpis"]}
    return [{"key": k["key"], "label": k["label"], "value": k["value"], "unit": k["unit"], "target": k["target"],
             "status": k["status"], "hint": k["hint"], "higher_better": k["higher_better"],
             "previous": previous[k["key"]]["value"], "link": BUSINESS_KPIS[k["key"]]}
            for k in current if k["key"] in BUSINESS_KPIS]


def _delay_causes(db: Session) -> dict:
    """هر سفارش دیرکرده یا در خطر فقط یک علت می‌گیرد؛ ترتیب همان ترتیب مانع‌های صفحه سفارش است."""
    now = eta_service._now()
    risk_ids = set(eta_service.at_risk_ids(db, now))
    late = db.query(Order).filter(Order.status.in_(ACTIVE_ORDER_STATUSES), Order.delivery_window_end < now).all()
    risky = db.query(Order).filter(Order.id.in_(risk_ids or {-1})).all()
    orders = {o.id: o for o in (*late, *risky)}
    short = {oid for (oid,) in db.query(Backorder.order_id).filter(Backorder.status.in_(("open", "allocated")), Backorder.order_id.in_(orders or {-1})).all()}
    causes = {"stock": ("کمبود موجودی", "/app/backorders", 0), "driver": ("منتظر پاسخ راننده", "/app/orders?order_status=assigned", 0),
              "vehicle": ("بدون خودرو", "/app/orders?order_status=pending", 0), "transit": ("عقب از برنامه در مسیر", "/app/map", 0),
              "other": ("سایر", "/app/orders?view=late", 0)}

    def cause(order) -> str:
        if order.id in short:
            return "stock"
        if order.assignment_state == "pending":
            return "driver"
        if order.status == "pending" and not order.vehicle_id:
            return "vehicle"
        if order.status == "in_transit":
            return "transit"
        return "other"
    counts: dict[str, int] = {}
    for order in orders.values():
        key = cause(order)
        counts[key] = counts.get(key, 0) + 1
    return {"late": len(late), "at_risk": len(risk_ids),
            "causes": [{"key": k, "label": causes[k][0], "count": n, "link": causes[k][1]}
                       for k, n in sorted(counts.items(), key=lambda kv: -kv[1])]}


def _money(db: Session, user: User, today: date) -> dict:
    start = today - timedelta(days=WINDOW_DAYS - 1)
    transport = report_data.finance_data(db, user, start, today)["kpis"]
    lo, hi = report_data._utc_bounds(start, today)
    delivered = db.query(Order.id).filter(Order.status == "delivered", Order.delivered_at >= lo, Order.delivered_at < hi)
    costs: dict[int, float] = {}
    for price in db.query(ProductPrice).filter(ProductPrice.cost_price.is_not(None)).order_by(ProductPrice.effective_from, ProductPrice.id).all():
        costs[price.product_id] = float(price.cost_price)
    margin, sales, covered, total = 0.0, 0.0, 0, 0
    by_product: dict[int, float] = {}
    for item in db.query(OrderItem).filter(OrderItem.order_id.in_(delivered)).all():
        total += 1
        if item.product_id not in costs:
            continue
        covered += 1
        line_sales, line_margin = float(item.unit_price or 0) * item.quantity, (float(item.unit_price or 0) - costs[item.product_id]) * item.quantity
        sales += line_sales
        margin += line_margin
        by_product[item.product_id] = by_product.get(item.product_id, 0) + line_margin
    top = sorted(by_product.items(), key=lambda kv: -kv[1])[:MARGIN_PRODUCTS]
    names = dict(db.query(Product.id, Product.name).filter(Product.id.in_([pid for pid, _ in top] or [-1])).all())
    return {"estimated": True, "window_days": WINDOW_DAYS, "trips": transport["trips"], "fare": transport["fare"], "driver_share": transport["driver"],
            "company_share": transport["company"], "goods_sales": round(sales), "goods_margin": round(margin),
            "cost_coverage_lines": covered, "total_lines": total,
            "top_products": [{"product_id": pid, "name": names.get(pid, "—"), "margin": round(value)} for pid, value in top]}


def _setup(db: Session) -> list[dict]:
    """قدم‌های ضروری سازمان تازه؛ جزئیات راه‌اندازی در صفحه آمادگی است."""
    steps = [
        ("warehouse", "اولین انبار را بسازید", db.query(Warehouse.id).first() is not None, "/app/warehouses"),
        ("product", "کالاها را تعریف کنید", db.query(Product.id).first() is not None, "/app/inventory"),
        ("vehicle", "خودروها را ثبت کنید", db.query(Vehicle.id).first() is not None, "/app/vehicles"),
        ("driver", "راننده دعوت و تأیید کنید", db.query(User.id).filter(User.role == "driver", User.driver_status == "approved").first() is not None, "/app/drivers"),
        ("order", "اولین سفارش را ثبت کنید", db.query(Order.id).first() is not None, "/app/orders"),
    ]
    return [{"key": k, "label": label, "done": done, "link": link} for k, label, done, link in steps]


def business(db: Session, user: User) -> dict:
    if _role(user) != "org_admin":
        raise ForbiddenError("این نما فقط برای ادمین سازمان است.")
    today = _today()
    severity = dict(db.query(OperationException.severity, func.count()).filter(OperationException.status.in_(ACTIVE_EXCEPTION_STATUSES))
                    .group_by(OperationException.severity).all())
    below = db.query(Inventory).filter(Inventory.stock_status == "available", Inventory.quantity <= Inventory.reorder_point)
    out = below.filter(Inventory.quantity == 0).count()
    return {
        "generated_at": eta_service._now(),
        "kpis": _kpis(db, user, today),
        "delays": _delay_causes(db),
        "exceptions": {"critical": severity.get("critical", 0), "high": severity.get("high", 0),
                       "link": "/app/exceptions?status=active&urgent=true"},
        "stock": {"out": out, "low": below.count() - out, "link": "/app/reorder"},
        "money": _money(db, user, today),
        "setup": _setup(db),
    }


def warehouse_today(db: Session, user: User) -> dict:
    warehouse_id = location_service.scope_warehouse(user, None)

    def scoped(query, column):
        return query.filter(column == warehouse_id) if warehouse_id else query
    items = [
        ("receipts", "رسیدهای باز", scoped(db.query(InboundReceipt).filter(InboundReceipt.status.in_(OPEN_RECEIPT_STATUSES)), InboundReceipt.warehouse_id).count(), "/app/receipts"),
        ("putaway", "جانمایی منتظر", scoped(db.query(PutawayTask).filter(PutawayTask.status.in_(("open", "partial"))), PutawayTask.warehouse_id).count(), "/app/putaway"),
        ("picks", "برداشت آماده", scoped(db.query(PickLine).join(PickList, PickLine.pick_list_id == PickList.id)
                                         .filter(PickLine.status == "open", PickList.status.in_(("open", "in_progress"))), PickList.warehouse_id).count(), "/app/my-tasks"),
        ("shipments", "محموله منتظر خروج", scoped(db.query(Shipment).filter(Shipment.status == "open"), Shipment.warehouse_id).count(), "/app/shipping"),
        ("shortages", "کمبود و معوق", scoped(db.query(Backorder).filter(Backorder.status.in_(("open", "allocated"))), Backorder.warehouse_id).count(), "/app/backorders"),
        ("counts", "انبارگردانی باز", scoped(db.query(Stocktake).filter(Stocktake.status.in_(("counting", "review"))), Stocktake.warehouse_id).count(), "/app/stocktakes"),
        ("exceptions", "استثنای انبار", scoped(db.query(OperationException).filter(OperationException.team == "warehouse", OperationException.status.in_(ACTIVE_EXCEPTION_STATUSES)),
                                               OperationException.warehouse_id).count(), "/app/exceptions?status=active&team=warehouse"),
    ]
    return {"generated_at": eta_service._now(), "warehouse_id": warehouse_id,
            "items": [{"key": k, "label": label, "count": count, "link": link} for k, label, count, link in items]}
