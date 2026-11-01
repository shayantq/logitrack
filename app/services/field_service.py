"""
عملیات میدانی تحویل (docs/operations-guide.md، مرحله ۲):
  • برگشت کالا از راننده: کالا با شمارش واقعی انبار برمی‌گردد و کسری دلیل و استثنا دارد
  • ثبت تماس با گیرنده
  • قبول و رد مأموریت (تنظیم سازمان، پیش‌فرض خاموش) با به‌روزرسانی اتمی
  • خودروی خارج از سرویس: سفارش‌های پیش از بارگیری جابه‌جا می‌شوند، سفارش بارگیری‌شده تحویل بین دو راننده لازم دارد
  • تحویل بین دو راننده با تأیید راننده مقصد
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, selectinload

from app.core.wms import PENDING
from app.models import ACTIVE_ORDER_STATUSES, Order, Shipment, StockReservation, User, Vehicle
from app.models_productivity import ContactAttempt, DriverReturn, DriverReturnLine, OrderHandover
from app.services import audit_service, capacity_service, control_settings, notification_service, order_service, stock_ledger
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

STAFF = ("org_admin", "warehouse_manager")
CONTACT_OUTCOMES = {"answered": "پاسخ داد", "no_answer": "پاسخ نداد", "busy": "مشغول بود", "wrong_number": "شماره اشتباه", "off": "خاموش بود"}
CONTACT_METHODS = {"call": "تماس", "sms": "پیامک", "door": "زنگ در"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _name(user: User | None) -> str | None:
    return (user.full_name or user.username) if user else None


def _order_for_staff(db: Session, user: User, order_id: int, *, lock: bool = False) -> Order:
    if user.role not in STAFF:
        raise ForbiddenError()
    query = db.query(Order).options(selectinload(Order.items)).filter(Order.id == order_id)
    order = (query.with_for_update() if lock else query).first()
    if order is None:
        raise NotFoundError("سفارش مورد نظر یافت نشد.")
    if user.role == "warehouse_manager" and order.warehouse_id != user.warehouse_id:
        raise ForbiddenError("این سفارش از انبار شما ارسال نمی‌شود.")
    return order


# ---------------------------------------------------------------------------
# برگشت کالا از راننده
# ---------------------------------------------------------------------------
def open_return(db: Session, user: User | None, order: Order, quantities: dict[int, int], reason: str, attempt_id: int | None = None) -> DriverReturn | None:
    """کالای بیرون‌رفته در انتظار برگشت ثبت می‌شود (بدون commit). موجودی فقط با رسیدن واقعی به انبار تغییر می‌کند."""
    names = {i.product_id: i.product_name for i in order.items}
    lines = [(pid, qty) for pid, qty in sorted(quantities.items()) if qty > 0]
    if not lines:
        return None
    row = DriverReturn(organization_id=order.organization_id, order_id=order.id, attempt_id=attempt_id, shipment_id=order.shipment_id,
                       driver_id=order.driver_id, status="open", reason=reason[:200], created_at=_now())
    for pid, qty in lines:
        row.lines.append(DriverReturnLine(organization_id=order.organization_id, product_id=pid, product_name=names.get(pid, ""), expected_quantity=qty))
    db.add(row)
    db.flush()
    return row


def _return_out(db: Session, row: DriverReturn) -> dict:
    receiver = db.get(User, row.received_by_id) if row.received_by_id else None
    return {"id": row.id, "order_id": row.order_id, "status": row.status, "reason": row.reason, "created_at": row.created_at,
            "received_at": row.received_at, "received_by": _name(receiver), "note": row.note,
            "lines": [{"product_id": line.product_id, "product_name": line.product_name, "expected_quantity": line.expected_quantity,
                       "received_quantity": line.received_quantity, "shortage_reason": line.shortage_reason} for line in row.lines]}


def list_returns(db: Session, user: User, order_id: int) -> list[dict]:
    order = _order_for_staff(db, user, order_id)
    rows = db.query(DriverReturn).options(selectinload(DriverReturn.lines)).filter(DriverReturn.order_id == order.id).order_by(DriverReturn.id).all()
    return [_return_out(db, r) for r in rows]


def receive_return(db: Session, user: User, order_id: int, return_id: int, data) -> dict:
    """شمارش انبار. مقدار رسیده با سند برگشت به «در انتظار بازرسی» می‌رود و بیشتر از مقدار مورد انتظار پذیرفته نمی‌شود."""
    from app.services import exception_service
    try:
        order = _order_for_staff(db, user, order_id, lock=True)
        row = db.query(DriverReturn).options(selectinload(DriverReturn.lines)).filter(
            DriverReturn.id == return_id, DriverReturn.order_id == order.id).with_for_update().first()
        if row is None:
            raise NotFoundError("این برگشت یافت نشد.")
        if row.status != "open":
            raise ConflictError("این برگشت قبلاً ثبت شده است.")
        counted = {entry.product_id: entry for entry in data.lines}
        if set(counted) != {line.product_id for line in row.lines}:
            raise ConflictError("برای همه اقلام برگشتی مقدار شمرده‌شده را وارد کنید.")
        issued = {r.product_id: r.movement for r in db.query(StockReservation).filter(
            StockReservation.reference_type == "order", StockReservation.reference_id == order.id,
            StockReservation.status == "consumed").all() if r.movement is not None}
        document = None
        shortages = []
        for line in sorted(row.lines, key=lambda x: x.product_id):
            entry = counted[line.product_id]
            if entry.received_quantity > line.expected_quantity:
                raise ConflictError(f"از «{line.product_name}» فقط {line.expected_quantity} عدد در انتظار برگشت است.")
            missing = line.expected_quantity - entry.received_quantity
            if missing and not (entry.shortage_reason or "").strip():
                raise ConflictError(f"کسری «{line.product_name}» ({missing} عدد) دلیل می‌خواهد.")
            line.received_quantity, line.shortage_reason = entry.received_quantity, (entry.shortage_reason or None) if missing else None
            if missing:
                shortages.append(f"{line.product_name}: {missing} عدد")
            if entry.received_quantity and order.warehouse_id is not None:
                inventory = stock_ledger.lock_bucket(db, line.product_id, order.warehouse_id, PENDING, organization_id=order.organization_id)
                if document is None:
                    document = stock_ledger.new_document(db, "order_return", organization_id=order.organization_id, user=user,
                                                         warehouse_id=order.warehouse_id, reference_type="order", reference_id=order.id,
                                                         note=f"برگشت سفارش {order.tracking_code}: {row.reason}"[:300])
                issue = issued.get(line.product_id)
                lines = (stock_ledger.mirror(issue, location_id=None)
                         if issue is not None and -issue.quantity_change == entry.received_quantity else None)
                stock_ledger.record(db, inventory, entry.received_quantity, "order_return", document=document, user=user,
                                    reason=f"برگشت از راننده: سفارش {order.tracking_code}", reference_type="order", reference_id=order.id, lines=lines)
        row.status, row.received_at, row.received_by_id, row.note = "received", _now(), user.id, data.note
        if order.stock_state == "returning" and not db.query(DriverReturn.id).filter(
                DriverReturn.order_id == order.id, DriverReturn.status == "open", DriverReturn.id != row.id).first():
            order.stock_state = "returned"
        order_service.record_history(db, order, order.status, order.status, user, "برگشت از راننده در انبار ثبت شد" + (" با کسری" if shortages else ""))
        if shortages:
            exception_service.record(db, "return_shortage", "driver_return", row.id, organization_id=order.organization_id,
                                     warehouse_id=order.warehouse_id, actor=user,
                                     reason=f"برگشت سفارش {order.tracking_code} کسری دارد: {'، '.join(shortages)}"[:300])
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _return_out(db, row)


# ---------------------------------------------------------------------------
# تماس با گیرنده
# ---------------------------------------------------------------------------
def _ensure_order_access(db: Session, user: User, order_id: int) -> Order:
    return order_service.get_order(db, user, order_id)


def add_contact(db: Session, user: User, order_id: int, data) -> dict:
    order = _ensure_order_access(db, user, order_id)
    if order.status not in ACTIVE_ORDER_STATUSES:
        raise ConflictError("این سفارش پایان یافته است.")
    row = ContactAttempt(organization_id=order.organization_id, order_id=order.id, user_id=user.id, method=data.method, outcome=data.outcome,
                         note=data.note, at=_now())
    db.add(row)
    db.commit()
    return _contact_out(row, _name(user))


def _contact_out(row: ContactAttempt, name: str | None) -> dict:
    return {"id": row.id, "at": row.at, "method": row.method, "method_label": CONTACT_METHODS[row.method], "outcome": row.outcome,
            "outcome_label": CONTACT_OUTCOMES[row.outcome], "note": row.note, "user_name": name}


def list_contacts(db: Session, user: User, order_id: int) -> list[dict]:
    order = _ensure_order_access(db, user, order_id)
    rows = db.query(ContactAttempt).filter(ContactAttempt.order_id == order.id).order_by(ContactAttempt.id).all()
    ids = {r.user_id for r in rows if r.user_id}
    names = {u.id: _name(u) for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}
    return [_contact_out(r, names.get(r.user_id)) for r in rows]


# ---------------------------------------------------------------------------
# قبول و رد مأموریت
# ---------------------------------------------------------------------------
def mark_assigned(db: Session, order: Order) -> None:
    """اگر سازمان قبول مأموریت را روشن کرده، سفارش تازه‌تخصیص‌یافته منتظر پاسخ راننده می‌ماند."""
    settings = control_settings.of(db, order.organization_id)
    if settings["mission_accept_required"] and order.driver_id:
        order.assignment_state = "pending"
        order.assignment_deadline = _now() + timedelta(minutes=settings["mission_deadline_minutes"])
    else:
        order.assignment_state, order.assignment_deadline = None, None


def respond_mission(db: Session, user: User, order_id: int, data) -> Order:
    """به‌روزرسانی شرطی: اگر سفارش همین لحظه عوض شده باشد هیچ سطری تغییر نمی‌کند و پاسخ رد می‌شود."""
    if user.role != "driver":
        raise ForbiddenError("فقط راننده سفارش به مأموریت پاسخ می‌دهد.")
    if not data.accept and not (data.reason or "").strip():
        raise ConflictError("برای رد مأموریت دلیل را بنویسید.")
    condition = (Order.id == order_id, Order.driver_id == user.id, Order.status == "assigned", Order.assignment_state == "pending")
    values = ({Order.assignment_state: "accepted", Order.assignment_deadline: None} if data.accept
              else {Order.assignment_state: None, Order.assignment_deadline: None, Order.vehicle_id: None, Order.driver_id: None, Order.status: "pending"})
    changed = db.query(Order).filter(*condition).update(values, synchronize_session=False)
    if not changed:
        db.rollback()
        raise ConflictError("این مأموریت دیگر منتظر پاسخ شما نیست.")
    db.expire_all()
    order = db.get(Order, order_id)
    if data.accept:
        order_service.record_history(db, order, "assigned", "assigned", user, "راننده مأموریت را پذیرفت")
    else:
        order_service.record_history(db, order, "assigned", "pending", user, f"راننده مأموریت را رد کرد: {data.reason.strip()}"[:500])
        notification_service.notify(db, organization_id=order.organization_id, kind="order_failed", title="راننده مأموریت را رد کرد",
                                    message=f"سفارش {order.tracking_code} دوباره منتظر تخصیص خودروست.", link=f"/app/orders?order={order.id}",
                                    severity="warning", warehouse_id=order.warehouse_id, actor=user, dedupe_key=f"order:{order.id}:mission_rejected")
    db.commit()
    return order_service.get_order(db, user, order.id) if data.accept else order


# ---------------------------------------------------------------------------
# خودروی خارج از سرویس
# ---------------------------------------------------------------------------
def out_of_service(db: Session, user: User, vehicle_id: int, data) -> dict:
    """سفارش‌های بارگیری‌نشده جابه‌جا یا بی‌خودرو می‌شوند. سفارش بارگیری‌شده خودکار جابه‌جا نمی‌شود چون کالا روی همین خودروست."""
    try:
        vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).with_for_update().first()
        if vehicle is None:
            raise NotFoundError("خودرو یافت نشد.")
        if user.role != "org_admin" and not (user.role == "driver" and vehicle.driver_id == user.id):
            raise ForbiddenError()
        vehicle.status = "maintenance"
        audit_service.log(db, user, "vehicle.out_of_service", f"خودرو {vehicle.license_plate} خارج از سرویس شد", target_type="vehicle",
                          target_id=vehicle.id, target_label=vehicle.license_plate, reason=data.reason)
        db.flush()
        orders = db.query(Order).options(selectinload(Order.items)).filter(
            Order.vehicle_id == vehicle.id, Order.status.in_(ACTIVE_ORDER_STATUSES)).order_by(Order.priority.desc(), Order.id).with_for_update().all()
        result = {"reassigned": [], "unassigned": [], "handover_needed": []}
        for order in orders:
            if order.status in ("picked_up", "in_transit"):
                result["handover_needed"].append(order.tracking_code)
                order_service.record_history(db, order, order.status, order.status, user, f"خودرو از سرویس خارج شد: {data.reason}"[:500])
                continue
            shipment = db.get(Shipment, order.shipment_id) if order.shipment_id else None
            if shipment is not None and shipment.status == "open":
                order.shipment_id = None
            previous = order.status
            target = order_service.try_assign(db, order)
            if target is not None:
                order.vehicle_id, order.driver_id, order.status = target.id, target.driver_id, "assigned"
                mark_assigned(db, order)
                note = f"جابه‌جایی به خودرو {target.license_plate}: {data.reason}"
                notification_service.order_assigned(db, order)
                result["reassigned"].append(order.tracking_code)
            else:
                order.vehicle_id, order.driver_id, order.status = None, None, "pending"
                order.assignment_state, order.assignment_deadline = None, None
                note = f"خودروی جایگزین پیدا نشد: {data.reason}"
                result["unassigned"].append(order.tracking_code)
            order_service.record_history(db, order, previous, order.status, user, note[:500])
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


# ---------------------------------------------------------------------------
# تحویل بین دو راننده
# ---------------------------------------------------------------------------
def _handover_out(db: Session, row: OrderHandover) -> dict:
    order = db.get(Order, row.order_id)
    plate = db.get(Vehicle, row.to_vehicle_id)
    people = {u.id: _name(u) for u in db.query(User).filter(User.id.in_({row.from_driver_id or -1, row.to_driver_id})).all()}
    return {"id": row.id, "order_id": row.order_id, "tracking_code": order.tracking_code if order else None, "status": row.status,
            "from_driver": people.get(row.from_driver_id), "to_driver": people.get(row.to_driver_id),
            "to_vehicle_plate": plate.license_plate if plate else None, "note": row.note, "response_note": row.response_note,
            "created_at": row.created_at, "responded_at": row.responded_at,
            "items": [{"name": i.product_name, "quantity": i.quantity} for i in order.items] if order else []}


def request_handover(db: Session, user: User, order_id: int, data) -> dict:
    try:
        order = db.query(Order).options(selectinload(Order.items)).filter(Order.id == order_id).with_for_update().first()
        if order is None:
            raise NotFoundError("سفارش مورد نظر یافت نشد.")
        if user.role == "driver":
            if order.driver_id != user.id:
                raise NotFoundError("سفارش مورد نظر یافت نشد.")
        elif user.role != "org_admin":
            raise ForbiddenError("تحویل بین دو راننده را ادمین سازمان یا راننده فعلی شروع می‌کند.")
        if order.status not in ("picked_up", "in_transit"):
            raise ConflictError("فقط سفارش بارگیری‌شده بین دو راننده تحویل می‌شود.")
        target = db.get(Vehicle, data.to_vehicle_id)
        if target is None or not target.driver_id:
            raise ConflictError("خودروی مقصد راننده ندارد.")
        if target.id == order.vehicle_id:
            raise ConflictError("این سفارش همین الان روی همین خودروست.")
        if target.status in ("maintenance", "inactive"):
            raise ConflictError("خودروی مقصد در سرویس نیست.")
        driver = db.get(User, target.driver_id)
        if driver is None or driver.is_active is False or driver.driver_status != "approved":
            raise ConflictError("راننده خودروی مقصد فعال و تأییدشده نیست.")
        if not capacity_service.check(target, order.total_weight_kg or 0).ok:
            raise ConflictError("ظرفیت خودروی مقصد برای این سفارش کافی نیست.")
        if db.query(OrderHandover.id).filter(OrderHandover.order_id == order.id, OrderHandover.status == "requested").first():
            raise ConflictError("برای این سفارش تحویل دیگری منتظر تأیید است.")
        row = OrderHandover(organization_id=order.organization_id, order_id=order.id, from_driver_id=order.driver_id, from_vehicle_id=order.vehicle_id,
                            to_driver_id=target.driver_id, to_vehicle_id=target.id, status="requested", note=data.note, requested_by_id=user.id, created_at=_now())
        db.add(row)
        order_service.record_history(db, order, order.status, order.status, user, f"درخواست تحویل به خودروی {target.license_plate}")
        notification_service.notify(db, organization_id=order.organization_id, kind="order_assigned", user_id=target.driver_id,
                                    title="درخواست تحویل گرفتن بار", message=f"سفارش {order.tracking_code} باید از راننده فعلی تحویل گرفته شود.",
                                    link="/app/driver", dedupe_key=f"order:{order.id}:handover:{target.driver_id}")
        db.commit()
        return _handover_out(db, row)
    except Exception:
        db.rollback()
        raise


def respond_handover(db: Session, user: User, handover_id: int, data) -> dict:
    """راننده مقصد با شمارش کالا تأیید می‌کند؛ سفارش فقط همان موقع به او می‌رسد."""
    try:
        row = db.query(OrderHandover).filter(OrderHandover.id == handover_id).with_for_update().first()
        if row is None:
            raise NotFoundError("این تحویل یافت نشد.")
        if user.role != "org_admin" and row.to_driver_id != user.id:
            raise NotFoundError("این تحویل یافت نشد.")
        if row.status != "requested":
            raise ConflictError("این تحویل قبلاً پاسخ گرفته است.")
        order = db.query(Order).options(selectinload(Order.items)).filter(Order.id == row.order_id).with_for_update().first()
        if data.accept:
            if order is None or order.status not in ("picked_up", "in_transit") or order.vehicle_id != row.from_vehicle_id:
                raise ConflictError("وضعیت این سفارش عوض شده و تحویل دیگر معتبر نیست.")
            order.vehicle_id, order.driver_id = row.to_vehicle_id, row.to_driver_id
            order_service.record_history(db, order, order.status, order.status, user, "بار تحویل راننده تازه شد" + (f": {data.note}" if data.note else ""))
        elif not (data.note or "").strip():
            raise ConflictError("برای رد تحویل دلیل را بنویسید.")
        row.status, row.responded_at, row.responded_by_id, row.response_note = "accepted" if data.accept else "rejected", _now(), user.id, data.note
        db.commit()
        return _handover_out(db, row)
    except Exception:
        db.rollback()
        raise


def my_handovers(db: Session, user: User) -> list[dict]:
    if user.role != "driver":
        raise ForbiddenError()
    rows = db.query(OrderHandover).filter(OrderHandover.to_driver_id == user.id, OrderHandover.status == "requested").order_by(OrderHandover.id).all()
    return [_handover_out(db, r) for r in rows]


def order_handovers(db: Session, user: User, order_id: int) -> list[dict]:
    order = order_service.get_order(db, user, order_id)
    return [_handover_out(db, r) for r in db.query(OrderHandover).filter(OrderHandover.order_id == order.id).order_by(OrderHandover.id).all()]
