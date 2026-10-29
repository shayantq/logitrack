"""
لایه سرویس سفارشات (Order Service)

تمام منطق تجاری سفارش‌ها اینجاست:
  • ثبت سفارش چندقلمی: قفل ردیف‌های موجودی (جلوگیری از فروش بیش از موجودی)،
    انتخاب انبار مبدأ، «رزرو» موجودی آزاد، ذخیره قیمت/وزن لحظه ثبت
  • مشتری (بر اساس شماره همراه) و آدرس مقصد با استان/شهر
  • تخصیص خودرو: هنگام ثبت، یا بعداً برای سفارش «در انتظار تخصیص»
  • ماشین وضعیت و تاریخچه کامل تغییرات وضعیت
  • وضعیت کالای سفارش (stock_state) جدا از وضعیت حمل:
        ثبت ← رزرو | بارگیری ← حواله خروج (مصرف رزرو) | لغو/انقضا قبل از بارگیری ← آزادسازی رزرو
        عدم تحویل بعد از بارگیری ← سند برگشت از سفارش
  • کلید یکتایی (Idempotency-Key): تکرار درخواست ثبت، سفارش دوم نمی‌سازد

روتر (app/routers/orders.py) فقط این توابع را صدا می‌زند.
"""
import secrets
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import (
    ACTIVE_ORDER_STATUSES, Customer, Inventory, Order, OrderItem, OrderStatusHistory, Organization, Product, StockReservation, User,
    Vehicle, Warehouse,
)
from app.schemas.order import CustomerIn, OrderAssignRequest, OrderRequest, OrderStatusRequest
from app.core.iran import fa_date, fa_digits, latin_digits, normalize_digits, normalize_persian_text
from app.core.wms import AVAILABLE, PENDING
from app.services import (
    allocation_service, audit_service, catalog_service, commission_service, dispatch_service, messaging,
    notification_service, stock_document_service, stock_ledger, warehouse_service,
)
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

# انتقال‌های مجاز وضعیت (با endpoint تغییر وضعیت). pending → assigned فقط از مسیر تخصیص خودرو.
# «تحویل داده شد» فقط از «در مسیر مقصد» — راننده باید حرکت را ثبت کرده باشد (جلوی تحویل ساختگی و مسیر خالی روی نقشه)
ALLOWED_TRANSITIONS = {
    'pending': {'canceled'},
    'assigned': {'picking_up', 'picked_up', 'failed', 'canceled'},
    'picking_up': {'picked_up', 'failed', 'canceled'},
    'picked_up': {'in_transit', 'failed'},
    'in_transit': {'delivered', 'failed'},
    'delivered': set(), 'failed': set(), 'canceled': set(), 'expired': set(),
}
DRIVER_ALLOWED_STATUSES = {'picking_up', 'picked_up', 'in_transit', 'delivered', 'failed'}
MANAGER_ALLOWED_STATUSES = {'picked_up', 'canceled'}
# وضعیت‌هایی که «انجام کار» هستند و پیش از روز تحویل سفارش مجاز نیستند
WORK_STATUSES = {'picking_up', 'picked_up', 'in_transit', 'delivered', 'failed'}
# کالا تحویل نشده → به انبار برمی‌گردد (رزرو آزاد می‌شود یا کالای خارج‌شده با سند برگشت)
RESTOCK_STATUSES = {'failed', 'canceled', 'expired'}
# بارگیری = خروج فیزیکی کالا از انبار (حواله خروج و مصرف رزرو)
ISSUE_STATUSES = {'picked_up'}
# پایان کار خودرو برای این سفارش
RELEASE_VEHICLE_STATUSES = {'delivered', 'failed', 'canceled', 'expired'}
STATUS_LABELS = {
    'pending': 'در انتظار تخصیص', 'assigned': 'تخصیص‌یافته', 'picking_up': 'در راه انبار',
    'picked_up': 'بارگیری شد', 'in_transit': 'در مسیر مقصد', 'delivered': 'تحویل‌شده',
    'failed': 'ناموفق', 'canceled': 'لغوشده', 'expired': 'منقضی‌شده',
}

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # بدون O/0/I/1 برای خوانایی پشت تلفن


def _new_tracking_code(db: Session) -> str:
    while True:
        code = "LT-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        # یکتایی در کل پلتفرم (نه فقط سازمان جاری)
        exists = db.query(Order.id).filter(Order.tracking_code == code).execution_options(skip_tenant_filter=True).first()
        if not exists:
            return code


def _add_history(db: Session, order: Order, from_status: str | None, to_status: str, user: User | None, note: str | None):
    db.add(OrderStatusHistory(
        organization_id=order.organization_id, order=order, from_status=from_status, to_status=to_status,
        changed_by_id=user.id if user else None, note=note, changed_at=datetime.now(timezone.utc),
    ))


def _upsert_customer(db: Session, organization_id: int, data: CustomerIn) -> Customer:
    customer = db.query(Customer).filter(Customer.mobile == data.mobile).first()
    if customer is None:
        customer = Customer(organization_id=organization_id, name=data.name, mobile=data.mobile,
                            email=str(data.email) if data.email else None)
        db.add(customer)
        db.flush()
    elif data.email and not customer.email:
        customer.email = str(data.email)
    return customer


# ---------------------------------------------------------------------------
# ثبت سفارش
# ---------------------------------------------------------------------------
def _lock_inventories(db: Session, products: dict[int, Product], quantities: dict[int, int],
                      warehouse_id: int | None, *, partial: bool = False) -> tuple[int | None, dict[int, Inventory], dict[int, int]]:
    """
    ردیف‌های موجودی «سالم و آزاد» همه اقلام را قفل می‌کند (به ترتیب id — بدون deadlock بین درخواست‌های
    هم‌زمان) و انباری را برمی‌گرداند که برای «همه» اقلام موجودی آزاد (موجود − رزرو) کافی دارد.
    partial (سفارش با پذیرش معوق): انباری که بیشترین مقدار را پوشش می‌دهد، حتی اگر همه اقلام کامل نباشد.
    خروجی: (انبار، ردیف‌های موجودی هر کالا، موجودی قابل وعده هر کالا در همان انبار).
    فقط انبارهایی که سفارش ارسال می‌کنند (عمومی/محصول نهایی/توزیع و فعال) نامزدند.
    """
    shipping = warehouse_service.shipping_ids(db)
    if warehouse_id is not None and warehouse_id not in shipping:
        warehouse = db.get(Warehouse, warehouse_id)
        if warehouse is None:
            raise NotFoundError('انبار انتخاب‌شده یافت نشد.')
        raise ConflictError(f"از «{warehouse.name}» ({warehouse_service.type_of(warehouse).label}"
                            f"{'، غیرفعال' if warehouse.is_active is False else ''}) سفارش مشتری ارسال نمی‌شود.")
    query = db.query(Inventory).filter(Inventory.product_id.in_(list(quantities)), Inventory.stock_status == AVAILABLE,
                                       Inventory.warehouse_id.in_(shipping or {-1}))
    if warehouse_id is not None:
        query = query.filter(Inventory.warehouse_id == warehouse_id)
    rows = query.order_by(Inventory.id).with_for_update().all()
    # موجودی قابل وعده: قابل تخصیص (محل نگهداری/برداشت، منقضی‌نشده، مال سازمان) منهای رزرو
    unallocatable = allocation_service.unallocatable_map(db, [inv.id for inv in rows])

    def free(inv: Inventory) -> int:
        return (inv.quantity or 0) - unallocatable.get(inv.id, 0) - (inv.reserved_quantity or 0)

    by_warehouse: dict[int | None, dict[int, Inventory]] = defaultdict(dict)
    for inv in rows:
        by_warehouse[inv.warehouse_id].setdefault(inv.product_id, inv)

    candidates = [warehouse_id] if warehouse_id is not None else sorted(by_warehouse, key=lambda w: (w is None, w or 0))

    def coverage(candidate) -> dict[int, int]:
        stock = by_warehouse.get(candidate, {})
        return {pid: max(free(stock[pid]), 0) if pid in stock else 0 for pid in quantities}

    for candidate in candidates:
        available = coverage(candidate)
        if all(available[pid] >= qty for pid, qty in quantities.items()):
            return candidate, by_warehouse.get(candidate, {}), available
    if partial and candidates:
        # بیشترین پوشش (اولویت با انبار با شناسه کمتر در تساوی)
        best = max(candidates, key=lambda c: (sum(min(q, coverage(c)[p]) for p, q in quantities.items()), -(c or 0)))
        available = coverage(best)
        if any(available.values()):
            return best, by_warehouse.get(best, {}), available

    # پیام دقیق: کدام کالا کم است (بر اساس بیشترین موجودی آزاد یک انبار)
    shortages = []
    for pid, qty in quantities.items():
        best = max((max(free(inv), 0) for inv in rows if inv.product_id == pid), default=0)
        if best < qty:
            shortages.append(f"«{products[pid].name}» (موجودی آزاد: {best}، درخواستی: {qty})")
    if shortages:
        raise ConflictError("موجودی کافی نیست: " + "، ".join(shortages))
    raise ConflictError("هیچ انباری به‌تنهایی موجودی کافی برای همه اقلام این سفارش ندارد؛ سفارش را تفکیک کنید.")


def _dispatch_args(weight: float, window_start, window_end, destination_city: str, destination_province: str | None,
                   exclude_order_id: int | None = None) -> dict:
    return dict(weight=weight, window_start=window_start, window_end=window_end, destination_city=destination_city,
                destination_province=destination_province, exclude_order_id=exclude_order_id)


def _auto_assign_vehicle(db: Session, **dispatch) -> Vehicle:
    """
    تخصیص خودکار = بهترین پیشنهاد موتور زمان‌بندی (dispatch_service).
    ردیف خودرو قفل و ارزیابی دوباره می‌شود تا دو سفارش هم‌زمان ظرفیت یک خودرو را بیش از حد پر نکنند.
    """
    evaluations = dispatch_service.evaluate(db, **dispatch)
    for candidate in (e for e in evaluations if e.eligible):
        db.query(Vehicle).filter(Vehicle.id == candidate.vehicle.id).with_for_update().first()
        fresh = dispatch_service.check_vehicle(db, candidate.vehicle.id, **dispatch)
        if fresh is not None and fresh.eligible:
            return fresh.vehicle
    excluded = [e for e in evaluations if not e.eligible]
    detail = "؛ ".join(sorted({e.reason for e in excluded if e.reason}))[:400]
    raise ConflictError(fa_digits(
        f"هیچ راننده‌ای برای این سفارش ({dispatch['weight']:g} کیلوگرم، {dispatch['destination_city']}) در دسترس نیست."
        + (f" دلایل: {detail}" if detail else "")
    ))


def _validate_manual_vehicle(db: Session, vehicle_id: int, **dispatch) -> Vehicle:
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).with_for_update().first()
    if vehicle is None:
        raise NotFoundError('خودروی مشخص‌شده یافت نشد.')
    evaluation = dispatch_service.check_vehicle(db, vehicle_id, **dispatch)
    if evaluation is None or not evaluation.eligible:
        raise ConflictError(fa_digits(f"این خودرو برای این سفارش مناسب نیست: {evaluation.reason if evaluation else 'یافت نشد'}."))
    return vehicle


def create_order(db: Session, user: User, order_request: OrderRequest, idempotency_key: str | None = None) -> Order:
    if user.role not in ['org_admin', 'warehouse_manager']:
        raise ForbiddenError()
    order, _ = stock_document_service.idempotent(
        db, Order, idempotency_key, "order", order_request.model_dump(mode="json"),
        lambda key, digest: _create_order(db, user, order_request, key, digest))
    return get_order(db, user, order.id)


def _create_order(db: Session, user: User, order_request: OrderRequest, idempotency_key: str | None,
                  request_hash: str | None) -> Order:
    source_warehouse_id = order_request.warehouse_id
    if user.role == 'warehouse_manager':
        if not user.warehouse_id:
            raise ConflictError("حساب کاربری شما به هیچ انباری متصل نشده است.")
        # مدیر انبار فقط از موجودی انبار خودش می‌تواند سفارش ثبت کند
        source_warehouse_id = user.warehouse_id

    try:
        quantities = {item.product_id: item.quantity for item in order_request.items}
        products = {p.id: p for p in db.query(Product).filter(Product.id.in_(list(quantities))).all()}
        if set(quantities) - set(products):
            raise NotFoundError('کالای انتخاب‌شده یافت نشد.')

        # 🔒 قفل ردیف‌های موجودی (SELECT ... FOR UPDATE)
        warehouse_id, inventories, available = _lock_inventories(
            db, products, quantities, source_warehouse_id, partial=order_request.allow_backorder)
        # تأمین جزئی: آنچه موجود است رزرو و ارسال می‌شود، باقی‌مانده «سفارش معوق» ثبت می‌شود (دور ریخته نمی‌شود)
        backordered = {pid: qty - min(qty, available.get(pid, 0)) for pid, qty in quantities.items()}
        quantities = {pid: qty - backordered[pid] for pid, qty in quantities.items() if qty - backordered[pid] > 0}

        total_weight = sum((products[pid].weight_kg or 0) * qty for pid, qty in quantities.items())
        dispatch = _dispatch_args(total_weight, order_request.delivery_window_start, order_request.delivery_window_end,
                                  order_request.destination_city, order_request.destination_province)
        vehicle = None
        if order_request.vehicle_id is not None:
            vehicle = _validate_manual_vehicle(db, order_request.vehicle_id, **dispatch)
        elif order_request.auto_assign:
            vehicle = _auto_assign_vehicle(db, **dispatch)

        customer = _upsert_customer(db, user.organization_id, order_request.customer)
        status = 'assigned' if vehicle else 'pending'
        # قیمت کالا در «روز تحویل» از تاریخچه قیمت (مرحله ۱۳)؛ روی اقلام ثبت می‌شود و بعداً تغییر نمی‌کند
        delivery_day = dispatch_service.to_local(dispatch_service.to_utc_naive(order_request.delivery_window_start)).date()
        unit_prices = {pid: catalog_service.unit_price_for_order(db, products[pid], delivery_day) for pid in quantities}
        if not quantities:
            raise ConflictError("هیچ‌کدام از اقلام این سفارش موجودی قابل وعده ندارد.")
        order = Order(
            organization_id=user.organization_id,
            tracking_code=_new_tracking_code(db),
            status=status,
            size=order_request.size,
            priority=order_request.priority,
            delivery_window_start=order_request.delivery_window_start,
            delivery_window_end=order_request.delivery_window_end,
            notes=order_request.notes,
            customer_id=customer.id,
            recipient_name=order_request.recipient_name or customer.name,
            recipient_mobile=order_request.recipient_mobile or customer.mobile,
            destination_province=order_request.destination_province,
            destination_city=order_request.destination_city,
            destination_address=order_request.destination_address,
            destination_postal_code=order_request.destination_postal_code,
            warehouse_id=warehouse_id,
            vehicle_id=vehicle.id if vehicle else None,
            driver_id=vehicle.driver_id if vehicle else None,
            delivery_fee=(order_request.delivery_fee if order_request.delivery_fee is not None
                          else commission_service.default_fee(commission_service.get_plan(db), total_weight)),
            total_quantity=sum(quantities.values()),
            total_weight_kg=total_weight,
            total_price=sum(unit_prices[pid] * qty for pid, qty in quantities.items()),
            stock_state="reserved", idempotency_key=idempotency_key, request_hash=request_hash,
        )
        db.add(order)
        for item in order_request.items:
            if item.product_id not in quantities:
                continue
            product = products[item.product_id]
            order.items.append(OrderItem(
                organization_id=user.organization_id, product_id=product.id, product_name=product.name,
                product_sku=product.sku, quantity=quantities[product.id],
                unit_price=unit_prices[product.id], unit_weight_kg=product.weight_kg or 0,
            ))
        db.flush()  # گرفتن شناسه سفارش برای مرجع رزرو

        # رزرو (نه خروج): کالا تا بارگیری در انبار می‌ماند ولی برای سفارش دیگری آزاد نیست
        for product_id, quantity in quantities.items():
            allocation_service.reserve(db, inventories[product_id], quantity,
                                       reference_type="order", reference_id=order.id, user=user)
        from app.services import backorder_service
        for product_id, quantity in backordered.items():
            if quantity > 0:
                backorder_service.open_backorder(db, user, order, products[product_id], quantity,
                                                 catalog_service.unit_price_for_order(db, products[product_id], delivery_day))
        _add_history(db, order, None, status, user,
                     "ثبت سفارش" + (f" و تخصیص خودرو {vehicle.license_plate or vehicle.id}" if vehicle else ""))
        notification_service.order_assigned(db, order)
        db.commit()
        messaging.order_created(order, _organization_name(db, order))
        return order
    except Exception:
        db.rollback()
        raise


def new_tracking_code(db: Session) -> str:
    return _new_tracking_code(db)


def record_history(db: Session, order: Order, from_status: str | None, to_status: str, user: User | None, note: str | None) -> None:
    _add_history(db, order, from_status, to_status, user, note)


def _organization_name(db: Session, order: Order) -> str:
    org = db.get(Organization, order.organization_id)
    return org.name if org else "پسینه"


# ---------------------------------------------------------------------------
# خواندن
# ---------------------------------------------------------------------------
def _driver_owns_order(db: Session, user: User, order: Order) -> bool:
    vehicle = db.get(Vehicle, order.vehicle_id) if order.vehicle_id else None
    return vehicle is not None and vehicle.driver_id == user.id


def _with_details(query):
    return query.options(
        selectinload(Order.items), joinedload(Order.customer),
        selectinload(Order.history).joinedload(OrderStatusHistory.changed_by),
    )


def get_order(db: Session, user: User, order_id: int) -> Order:
    order = _with_details(db.query(Order)).filter(Order.id == order_id).first()
    if order is None:
        raise NotFoundError('سفارش مورد نظر یافت نشد.')
    if user.role == 'driver' and not _driver_owns_order(db, user, order):
        # 404 به‌جای 403 تا وجود سفارش‌های دیگران فاش نشود
        raise NotFoundError('سفارش مورد نظر یافت نشد.')
    return order


def _plate_key(value: str | None) -> str:
    """کلید مقایسه پلاک: ارقام لاتین، بدون فاصله/خط تیره/«ایران» (پلاک‌ها با قالب‌های مختلف ذخیره شده‌اند)."""
    if not value:
        return ""
    return normalize_persian_text(normalize_digits(value)).replace("ایران", "").replace(" ", "").replace("الف", "ا")


def _matching_vehicle_ids(db: Session, plate: str) -> list[int]:
    key = _plate_key(plate)
    if not key:
        return []
    # تعداد خودروهای یک سازمان کم است؛ مقایسه در پایتون، مستقل از نوع دیتابیس
    return [v.id for v in db.query(Vehicle.id, Vehicle.license_plate).all() if key in _plate_key(v.license_plate)]


def _matching_driver_ids(db: Session, name: str) -> list[int]:
    like = f"%{normalize_persian_text(name.strip())}%"
    return [u.id for u in db.query(User.id).filter(User.role == 'driver', or_(
        User.full_name.ilike(like), User.username.ilike(like), User.driver_code.ilike(like))).all()]


def _driver_filter(db: Session, driver_ids: list[int]):
    """سفارش‌های این رانندگان — با driver_id سفارش، یا (برای سفارش‌های قدیمی بدون آن) با خودروی راننده."""
    ids = driver_ids or [-1]
    vehicle_ids = [v.id for v in db.query(Vehicle.id).filter(Vehicle.driver_id.in_(ids)).all()] or [-1]
    return or_(Order.driver_id.in_(ids), and_(Order.driver_id.is_(None), Order.vehicle_id.in_(vehicle_ids)))


# نماهای نام‌دار فهرست سفارش‌ها: مرکز اقدام و صفحه سفارش‌ها هر دو از همین تعریف استفاده می‌کنند
ORDER_VIEWS = {
    "late": "از بازه تحویل گذشته و هنوز تحویل نشده",
    "today": "سفارش‌های فعال امروز",
    "needs_update": "زمان شروع کار رسیده و هنوز حرکت ثبت نشده",
}


def _view_filter(view: str):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if view == "late":
        return and_(Order.status.in_(ACTIVE_ORDER_STATUSES), Order.delivery_window_end < now)
    if view == "today":
        today = dispatch_service.to_local(now).date()
        start = dispatch_service.local_to_utc(datetime.combine(today, time.min))
        return and_(Order.status.in_(ACTIVE_ORDER_STATUSES), Order.delivery_window_start >= start,
                    Order.delivery_window_start < start + timedelta(days=1))
    if view == "needs_update":
        return and_(Order.status.in_(("assigned", "picking_up")), Order.delivery_window_start <= now)
    raise ConflictError("نمای سفارش نامعتبر است.")


def _orders_query(db: Session, user: User, order_status: str | None = None, province: str | None = None,
                  city: str | None = None, q: str | None = None, vehicle_id: int | None = None,
                  date_from: datetime | None = None, date_to: datetime | None = None, *,
                  tracking_code: str | None = None, product: str | None = None,
                  driver_id: int | None = None, driver: str | None = None, plate: str | None = None,
                  delivery_from: date | None = None, delivery_to: date | None = None,
                  priority: bool | None = None, view: str | None = None, ids: list[int] | None = None):
    query = db.query(Order)

    if view:
        query = query.filter(_view_filter(view))
    if ids is not None:
        query = query.filter(Order.id.in_(ids or [-1]))

    if user.role == 'driver':
        driver_vehicle_ids = [v.id for v in db.query(Vehicle).filter(Vehicle.driver_id == user.id).all()]
        query = query.filter(Order.vehicle_id.in_(driver_vehicle_ids)) if driver_vehicle_ids else query.filter(False)

    if order_status:
        query = query.filter(Order.status == order_status)
    if province:
        query = query.filter(Order.destination_province == province)
    if city:
        query = query.filter(Order.destination_city == city)
    if vehicle_id:
        query = query.filter(Order.vehicle_id == vehicle_id)
    if date_from:
        query = query.filter(Order.created_at >= date_from)
    if date_to:
        query = query.filter(Order.created_at < date_to)
    if tracking_code:
        query = query.filter(Order.tracking_code.ilike(f"%{latin_digits(tracking_code.strip()).upper()}%"))
    if product:
        like = f"%{normalize_persian_text(product.strip())}%"
        query = query.filter(Order.items.any(or_(OrderItem.product_name.ilike(like), OrderItem.product_sku.ilike(like))))
    if driver_id:
        query = query.filter(_driver_filter(db, [driver_id]))
    if driver:
        query = query.filter(_driver_filter(db, _matching_driver_ids(db, driver)))
    if plate:
        query = query.filter(Order.vehicle_id.in_(_matching_vehicle_ids(db, plate) or [-1]))
    if delivery_from:
        query = query.filter(Order.delivery_window_start >= dispatch_service.local_to_utc(datetime.combine(delivery_from, time.min)))
    if delivery_to:
        query = query.filter(Order.delivery_window_start < dispatch_service.local_to_utc(datetime.combine(delivery_to + timedelta(days=1), time.min)))
    if priority is not None:
        query = query.filter(Order.priority == priority)
    if q:
        term = normalize_persian_text(q.strip())
        like = f"%{term}%"
        digits_like = f"%{normalize_digits(term)}%"
        query = query.outerjoin(Customer, Order.customer_id == Customer.id).filter(or_(
            Order.tracking_code.ilike(f"%{latin_digits(term).upper()}%"), Customer.name.ilike(like),
            Customer.mobile.like(digits_like), Order.recipient_name.ilike(like), Order.recipient_mobile.like(digits_like),
            Order.destination_city.ilike(like), Order.destination_address.ilike(like),
            Order.items.any(or_(OrderItem.product_name.ilike(like), OrderItem.product_sku.ilike(like))),
            _driver_filter(db, _matching_driver_ids(db, term)),
            Order.vehicle_id.in_(_matching_vehicle_ids(db, term) or [-1]),
        ))
    return query


def list_orders(db: Session, user: User, order_status: str | None = None, province: str | None = None,
                city: str | None = None, q: str | None = None, vehicle_id: int | None = None,
                date_from: datetime | None = None, date_to: datetime | None = None,
                skip: int = 0, limit: int = 100, **filters) -> list[Order]:
    """
    جستجوی پیشرفته (مرحله ۹). همه فیلترها با AND ترکیب می‌شوند؛ q یک جستجوی سراسری است که
    کد سفارش، مشتری/تحویل‌گیرنده، کالا، راننده و پلاک را با OR می‌گردد.
    delivery_from/delivery_to: روز تحویل به وقت ایران (هر دو شامل). view: یکی از ORDER_VIEWS.
    """
    query = _orders_query(db, user, order_status, province, city, q, vehicle_id, date_from, date_to, **filters)
    return query.options(selectinload(Order.items), joinedload(Order.customer))         .order_by(Order.id.desc()).offset(skip).limit(limit).all()


def count_orders(db: Session, user: User, **filters) -> int:
    """شمار همان فهرست list_orders با همان فیلترها (برای شمارنده‌های مرکز اقدام)."""
    return _orders_query(db, user, **filters).order_by(None).count()


# ---------------------------------------------------------------------------
# تخصیص خودرو و تغییر وضعیت
# ---------------------------------------------------------------------------
def assign_vehicle(db: Session, user: User, order_id: int, request: OrderAssignRequest) -> Order:
    if user.role not in ['org_admin', 'warehouse_manager']:
        raise ForbiddenError()
    try:
        order = db.query(Order).filter(Order.id == order_id).with_for_update().first()
        if order is None:
            raise NotFoundError('سفارش مورد نظر یافت نشد.')
        if user.role == 'warehouse_manager' and order.warehouse_id != user.warehouse_id:
            raise ForbiddenError('این سفارش از انبار شما ارسال نمی‌شود.')
        if order.status != 'pending':
            raise ConflictError('فقط به سفارش «در انتظار تخصیص» می‌توان خودرو اختصاص داد.')

        dispatch = _dispatch_args(order.total_weight_kg, order.delivery_window_start, order.delivery_window_end,
                                  order.destination_city, order.destination_province, exclude_order_id=order.id)
        vehicle = (_validate_manual_vehicle(db, request.vehicle_id, **dispatch) if request.vehicle_id
                   else _auto_assign_vehicle(db, **dispatch))
        order.vehicle_id = vehicle.id
        order.driver_id = vehicle.driver_id
        order.status = 'assigned'
        _add_history(db, order, 'pending', 'assigned', user, f"تخصیص خودرو {vehicle.license_plate or vehicle.id}")
        notification_service.order_assigned(db, order)
        db.commit()
        return get_order(db, user, order.id)
    except Exception:
        db.rollback()
        raise


def set_priority(db: Session, user: User, order_id: int, priority: bool) -> Order:
    """فوری/عادی کردن سفارش فعال (فقط ادمین)؛ در تاریخچه سفارش ثبت می‌شود."""
    if user.role != 'org_admin':
        raise ForbiddenError('فقط ادمین سازمان اولویت سفارش را تغییر می‌دهد.')
    try:
        order = db.query(Order).filter(Order.id == order_id).with_for_update().first()
        if order is None:
            raise NotFoundError('سفارش مورد نظر یافت نشد.')
        if order.status not in ACTIVE_ORDER_STATUSES:
            raise ConflictError('اولویت سفارش پایان‌یافته را نمی‌توان تغییر داد.')
        if order.priority == priority:
            raise ConflictError('اولویت سفارش از قبل همین است.')
        order.priority = priority
        _add_history(db, order, order.status, order.status, user, "فوری شد" if priority else "از حالت فوری خارج شد")
        db.commit()
        return get_order(db, user, order.id)
    except Exception:
        db.rollback()
        raise


def _issue_stock(db: Session, order: Order, user: User | None) -> None:
    """بارگیری: رزروهای سفارش مصرف و کالا با یک «حواله خروج سفارش» از موجودی کم می‌شود."""
    if order.stock_state != "reserved":
        return          # سفارش‌های قدیمی که موجودی‌شان هنگام ثبت کم شده بود
    reservations = allocation_service.active_for(db, "order", order.id)
    from app.services import picking_service
    picked = picking_service.issue_lines(db, order, reservations)
    if reservations:
        document = stock_ledger.new_document(
            db, "order_issue", organization_id=order.organization_id, user=user, warehouse_id=order.warehouse_id,
            reference_type="order", reference_id=order.id, note=f"حواله خروج سفارش {order.tracking_code}",
        )
        for reservation in reservations:
            allocation_service.consume(db, reservation, document, user=user, reason=f"خروج بابت سفارش {order.tracking_code}",
                                       lines=picked.get(reservation.id))
    picking_service.mark_issued(db, order)
    order.stock_state = "issued"
    order.fulfillment_state = "shipped"


def _restore_stock(db: Session, order: Order, user: User | None, reason: str) -> None:
    """
    کالای سفارشی که تحویل نشد: اگر هنوز بارگیری نشده، رزروش آزاد می‌شود (و کالای برداشت‌شده به قفسه برمی‌گردد)؛
    اگر از انبار خارج شده بود، با «سند برگشت از سفارش» و وضعیت «در انتظار بازرسی» به انبار مبدأ برمی‌گردد —
    کالای برگشتی پیش از بازرسی کیفی قابل تخصیص نیست (فصل ۱۵).
    """
    if order.stock_state == "reserved":
        for reservation in allocation_service.active_for(db, "order", order.id):
            allocation_service.release(db, reservation, user=user, reason=reason)
        from app.services import picking_service
        picking_service.cancel_for_order(db, user, order)
        order.stock_state = "released"
        return
    if order.stock_state != "issued":
        return
    items = [item for item in order.items if item.product_id]
    # کالای برگشتی همان بچ/سریال/انقضای حواله خروج را دارد (بدون محل؛ جانمایی دوباره با وظیفه جانمایی)
    issued = {r.product_id: r.movement for r in db.query(StockReservation).filter(
        StockReservation.reference_type == "order", StockReservation.reference_id == order.id,
        StockReservation.status == "consumed").all() if r.movement is not None}
    document = None
    for item in sorted(items, key=lambda i: i.product_id):
        if order.warehouse_id is None:
            break
        inventory = stock_ledger.lock_bucket(db, item.product_id, order.warehouse_id, PENDING, organization_id=order.organization_id)
        if document is None:
            document = stock_ledger.new_document(
                db, "order_return", organization_id=order.organization_id, user=user, warehouse_id=order.warehouse_id,
                reference_type="order", reference_id=order.id, note=reason,
            )
        issue = issued.get(item.product_id)
        lines = stock_ledger.mirror(issue, location_id=None) if issue is not None and -issue.quantity_change == item.quantity else None
        stock_ledger.record(db, inventory, item.quantity, "order_return", document=document, user=user, reason=reason,
                            reference_type="order", reference_id=order.id, lines=lines)
    order.stock_state = "returned"


def _release_vehicle(db: Session, order: Order) -> None:
    """
    از مرحله ۷ ظرفیت خودرو از روی بازه زمانی سفارش‌ها حساب می‌شود و تخصیص وضعیت خودرو را عوض نمی‌کند.
    فقط اگر راننده «در مسیر» زده بود (یا وضعیت قدیمی «مشغول» مانده بود) و سفارش فعال دیگری ندارد، «در دسترس» می‌شود.
    """
    if not order.vehicle_id:
        return
    vehicle = db.query(Vehicle).filter(Vehicle.id == order.vehicle_id).with_for_update().first()
    if vehicle is None or vehicle.status not in ('busy', 'on_route'):
        return
    other_active = db.query(Order).filter(
        Order.vehicle_id == vehicle.id, Order.id != order.id, Order.status.in_(ACTIVE_ORDER_STATUSES),
    ).first()
    if other_active is None:
        vehicle.status = 'available'


def _apply_status(db: Session, order: Order, new_status: str, user: User | None, note: str | None) -> None:
    old_status = order.status
    order.status = new_status
    if new_status in ISSUE_STATUSES:
        _issue_stock(db, order, user)
    if new_status in RESTOCK_STATUSES:
        _restore_stock(db, order, user, f"برگشت به انبار: سفارش {order.tracking_code} {STATUS_LABELS[new_status]}")
    if new_status in ('canceled', 'expired'):
        from app.services import backorder_service
        backorder_service.cancel_for_order(db, user, order, f"سفارش {order.tracking_code} {STATUS_LABELS[new_status]}")
    if new_status in RELEASE_VEHICLE_STATUSES:
        _release_vehicle(db, order)
    if new_status == 'delivered':
        commission_service.settle_delivery(db, order)
    if new_status == 'in_transit':
        # مسیر شهربه‌شهر با شروع حرکت ثابت می‌شود (مرحله ۱۰)
        from app.services import route_service
        route_service.freeze_route(db, order)
    _add_history(db, order, old_status, new_status, user, note)
    notification_service.order_event(db, order, new_status, user, note)


def apply_status(db: Session, order: Order, new_status: str, user: User | None, note: str | None) -> None:
    """تغییر وضعیت از مسیرهای داخلی (مثلاً تحویل محموله به راننده) با همان اثرهای انبار، خودرو و اعلان."""
    _apply_status(db, order, new_status, user, note)


def update_order_status(db: Session, user: User, order_id: int, status_request: OrderStatusRequest) -> Order:
    target_order = db.get(Order, order_id)
    if target_order is None:
        raise NotFoundError('سفارش یافت نشد.')

    new_status = status_request.order_status

    if user.role == 'org_admin':
        pass
    elif user.role == 'driver':
        if not _driver_owns_order(db, user, target_order):
            raise ForbiddenError('این سفارش به شما اختصاص داده نشده است.')
        if new_status not in DRIVER_ALLOWED_STATUSES:
            raise ConflictError('راننده فقط می‌تواند وضعیت را به «در راه انبار»، «بارگیری شد»، «در مسیر»، «تحویل‌شده» یا «ناموفق» تغییر دهد.')
    elif user.role == 'warehouse_manager':
        if target_order.warehouse_id != user.warehouse_id:
            raise ForbiddenError('این سفارش از انبار شما ارسال نمی‌شود.')
        if new_status not in MANAGER_ALLOWED_STATUSES:
            raise ConflictError('مدیر انبار فقط می‌تواند سفارش را «بارگیری شد» یا «لغو» کند.')
    else:
        raise ForbiddenError()

    if target_order.status == new_status:
        raise ConflictError('وضعیت سفارش از قبل روی این حالت تنظیم شده است.')
    if new_status not in ALLOWED_TRANSITIONS.get(target_order.status, set()):
        raise ConflictError(
            f'تغییر وضعیت از «{STATUS_LABELS.get(target_order.status, target_order.status)}» '
            f'به «{STATUS_LABELS.get(new_status, new_status)}» مجاز نیست.'
        )

    # سفارش روزهای آینده را نمی‌توان از امروز بارگیری/تحویل کرد (ممکن است کالا هنوز آماده نباشد)
    if new_status in WORK_STATUSES:
        delivery_day = dispatch_service.to_local(dispatch_service.to_utc_naive(target_order.delivery_window_start)).date()
        today = dispatch_service.to_local(datetime.now(timezone.utc).replace(tzinfo=None)).date()
        if today < delivery_day:
            raise ConflictError(f"این سفارش برای تحویل در تاریخ {fa_date(delivery_day)} است؛ "
                                "تا آن روز نمی‌توان آن را بارگیری یا تحویل کرد.")

    try:
        _apply_status(db, target_order, new_status, user, status_request.note)
        db.commit()
        if new_status == 'delivered':
            messaging.order_delivered(target_order, _organization_name(db, target_order))
        return get_order(db, user, target_order.id)
    except Exception:
        db.rollback()
        raise


def delete_order(db: Session, user: User, order_id: int) -> None:
    if user.role != 'org_admin':
        raise ForbiddenError()

    try:
        target_order = db.get(Order, order_id)
        if target_order is None:
            raise NotFoundError('سفارش یافت نشد.')

        # سفارشی که کالایش از انبار خارج شده (یا برگشته) سند انبار دارد و برای حفظ سوابق حذف نمی‌شود؛ لغو کنید.
        if target_order.stock_state in ("issued", "returned"):
            raise ConflictError("کالای این سفارش از انبار خارج شده و سند انبار دارد؛ به‌جای حذف، سفارش را لغو کنید.")
        if target_order.status in ACTIVE_ORDER_STATUSES:
            _restore_stock(db, target_order, user, f"آزادسازی رزرو: سفارش {target_order.tracking_code} حذف شد")
            _release_vehicle(db, target_order)

        audit_service.log(db, user, "order.delete", f"سفارش {target_order.tracking_code} حذف شد", target_type="order",
                          target_id=target_order.id, target_label=target_order.tracking_code)
        db.delete(target_order)
        db.commit()
    except Exception:
        db.rollback()
        raise


def expire_overdue_orders(db: Session, now: datetime | None = None) -> int:
    """
    سفارش‌هایی که هنوز بارگیری نشده‌اند (در انتظار/تخصیص‌یافته) و بازه تحویلشان
    گذشته، «منقضی» می‌شوند: موجودی برمی‌گردد و خودرو آزاد می‌شود. (Celery Beat، هر ساعت)
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now.replace(tzinfo=None) if now.tzinfo else now  # ستون‌ها بدون منطقه زمانی (UTC) ذخیره می‌شوند
    overdue = db.query(Order).options(selectinload(Order.items)).filter(
        Order.status.in_(('pending', 'assigned')), Order.delivery_window_end < cutoff,
    ).order_by(Order.id).with_for_update().all()
    for order in overdue:
        _apply_status(db, order, 'expired', None, "انقضای خودکار: بازه تحویل گذشت و سفارش ارسال نشد")
    db.commit()
    return len(overdue)
