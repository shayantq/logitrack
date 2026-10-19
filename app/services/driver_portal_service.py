"""
پنل راننده (پیش از مرحله ۸):
- برنامه و کارنامه: سفارش‌های هر روز (آینده و گذشته) با شیفت و مرخصی همان روز
- پروفایل: مشاهده و ویرایش اطلاعات تماس و سکونت
- درخواست مرخصی فوری/عادی ← تأیید ادمین ← ثبت مرخصی و آزاد شدن سفارش‌های بارگیری‌نشده
- درخواست تغییر خودرو با مدارک جدید ← تأیید ادمین ← خودروی جدید در ناوگان (خودروی قبلی با سابقه‌اش غیرفعال می‌ماند)
"""
import re
import secrets
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.core import storage
from app.core.iran import fa_digits
from app.core.tenancy import SKIP_TENANT_FILTER
from app.models import (
    ACTIVE_ORDER_STATUSES, DriverDocument, DriverProfile, DriverRequest, DriverRequestDocument, DriverShift, DriverTimeOff,
    Order, OrderStatusHistory, User, Vehicle,
)
from app.schemas.driver import CAR_PLATE
from app.schemas.driver_portal import DriverProfileUpdate, LeaveRequestCreate, VehicleChangeCreate
from app.services import driver_service, notification_service
from app.services.dispatch_service import local_to_utc, to_local, to_utc_naive
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

VEHICLE_DOCUMENTS = ("vehicle_photo", "vehicle_card", "technical_inspection")
CATEGORY_LABELS = {"sickness": "بیماری", "family": "امور خانوادگی", "personal": "کار شخصی",
                   "vehicle_repair": "تعمیر خودرو", "other": "سایر"}
NORMAL_LEAVE_NOTICE = timedelta(hours=24)
MAX_AGENDA_DAYS = 31


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _require_driver(user: User) -> None:
    if user.role != "driver":
        raise ForbiddenError("این بخش مخصوص رانندگان است.")


def _require_approved_driver(user: User) -> None:
    _require_driver(user)
    if user.driver_status != "approved":
        raise ConflictError("ابتدا باید احراز هویت شما توسط سازمان تأیید شود.")


def _require_admin(user: User) -> None:
    if user.role != "org_admin":
        raise ForbiddenError("فقط ادمین سازمان درخواست‌های رانندگان را بررسی می‌کند.")


def driver_vehicle_ids(db: Session, driver_id: int) -> list[int]:
    """همه خودروهای راننده — شامل خودروهای قبلی، تا سابقه سفارش‌هایش حفظ شود."""
    return [v.id for v in db.query(Vehicle.id).filter(Vehicle.driver_id == driver_id).all()]


def current_vehicle(db: Session, driver: User) -> Vehicle | None:
    """خودروی فعلی: آخرین خودروی راننده که بازنشسته (غیرفعال پس از تغییر خودرو) نشده است."""
    profile = db.query(DriverProfile).filter(DriverProfile.user_id == driver.id).first()
    if profile and profile.vehicle_id:
        vehicle = db.get(Vehicle, profile.vehicle_id)
        if vehicle and vehicle.driver_id == driver.id:
            return vehicle
    return db.query(Vehicle).filter(Vehicle.driver_id == driver.id).order_by(Vehicle.id.desc()).first()


def _vehicle_dict(v: Vehicle | None) -> dict | None:
    if v is None:
        return None
    return {"id": v.id, "license_plate": v.license_plate, "type": v.type, "model": v.model,
            "capacity_kg": v.capacity_kg, "status": v.status}


# ---------------------------------------------------------------------------
# برنامه و کارنامه
# ---------------------------------------------------------------------------
def agenda(db: Session, user: User, start: date, days: int) -> dict:
    _require_driver(user)
    days = max(1, min(days, MAX_AGENDA_DAYS))
    range_start = local_to_utc(datetime.combine(start, time.min))
    range_end = local_to_utc(datetime.combine(start + timedelta(days=days), time.min))
    vehicle_ids = driver_vehicle_ids(db, user.id)
    orders = db.query(Order).filter(
        Order.vehicle_id.in_(vehicle_ids), Order.delivery_window_start >= range_start, Order.delivery_window_start < range_end,
    ).order_by(Order.delivery_window_start).all() if vehicle_ids else []
    shifts = db.query(DriverShift).filter(DriverShift.user_id == user.id).order_by(DriverShift.start_time).all()
    offs = db.query(DriverTimeOff).filter(DriverTimeOff.user_id == user.id, DriverTimeOff.starts_at < range_end,
                                          DriverTimeOff.ends_at > range_start).all()

    by_day: dict[date, list[Order]] = {}
    for o in orders:
        by_day.setdefault(to_local(o.delivery_window_start).date(), []).append(o)
    result = []
    for i in range(days):
        day = start + timedelta(days=i)
        d0 = local_to_utc(datetime.combine(day, time.min))
        d1 = d0 + timedelta(days=1)
        off = next((t for t in offs if t.starts_at < d1 and t.ends_at > d0), None)
        result.append({
            "date": day,
            "shifts": [f"{s.start_time:%H:%M}–{s.end_time:%H:%M}" for s in shifts if s.weekday == day.weekday()],
            "off": off is not None, "off_reason": off.reason if off else None,
            "orders": [{c: getattr(o, c) for c in (
                "id", "tracking_code", "status", "priority", "delivery_window_start", "delivery_window_end",
                "destination_city", "destination_address", "recipient_name", "total_weight_kg")} for o in by_day.get(day, [])],
        })
    count = lambda *statuses: sum(1 for o in orders if o.status in statuses)  # noqa: E731
    return {"days": result, "summary": {
        "delivered": count("delivered"), "failed": count("failed"), "active": count(*ACTIVE_ORDER_STATUSES),
        "canceled": count("canceled", "expired"),
        "delivered_kg": round(sum(o.total_weight_kg or 0 for o in orders if o.status == "delivered"), 2),
    }}


# ---------------------------------------------------------------------------
# پروفایل
# ---------------------------------------------------------------------------
def my_profile(db: Session, user: User) -> dict:
    _require_driver(user)
    data = driver_service.application_dict(db, user)
    data["email"] = user.email
    data["current_vehicle"] = _vehicle_dict(current_vehicle(db, user))
    db.commit()
    return data


def update_my_profile(db: Session, user: User, data: DriverProfileUpdate) -> dict:
    _require_driver(user)
    values = data.model_dump(exclude_unset=True)
    if "email" in values and values["email"] and values["email"] != user.email:
        taken = db.query(User).filter(User.email == values["email"], User.id != user.id) \
            .execution_options(**SKIP_TENANT_FILTER).first()
        if taken:
            raise ConflictError("این ایمیل برای کاربر دیگری ثبت شده است.")
    if "email" in values:
        user.email = values.pop("email")
    profile = driver_service._profile_of(db, user)
    for key, value in values.items():
        setattr(profile, key, value)
    if values.get("city") and user.driver_status == "approved":
        user.city = values["city"]
    db.commit()
    return my_profile(db, user)


# ---------------------------------------------------------------------------
# درخواست‌ها — مشترک
# ---------------------------------------------------------------------------
def _documents(db: Session, request_id: int) -> list[DriverRequestDocument]:
    return db.query(DriverRequestDocument).filter(DriverRequestDocument.request_id == request_id) \
        .order_by(DriverRequestDocument.id).all()


def _required_vehicle_docs(vehicle_type: str | None) -> list[str]:
    return [k for k in VEHICLE_DOCUMENTS if k != "technical_inspection" or vehicle_type != "motorcycle"]


def _affected_orders(db: Session, driver_id: int, start: datetime, end: datetime) -> list[Order]:
    ids = driver_vehicle_ids(db, driver_id)
    if not ids:
        return []
    return db.query(Order).filter(Order.vehicle_id.in_(ids), Order.status.in_(ACTIVE_ORDER_STATUSES),
                                  Order.delivery_window_start < end, Order.delivery_window_end > start) \
        .order_by(Order.delivery_window_start).all()


def request_dict(db: Session, req: DriverRequest, driver: User | None = None) -> dict:
    driver = driver or db.get(User, req.user_id)
    data = {c: getattr(req, c) for c in (
        "id", "kind", "status", "created_at", "submitted_at", "leave_type", "category", "starts_at", "ends_at", "reason",
        "vehicle_data", "reviewed_at", "review_note")}
    data.update(driver_id=driver.id, driver_name=driver.full_name or driver.username, driver_code=driver.driver_code)
    if req.kind == "leave":
        if req.status in ("pending", "draft"):
            data["affected_orders"] = [{c: getattr(o, c) for c in ("id", "tracking_code", "status", "delivery_window_start",
                                                                    "destination_city")}
                                       for o in _affected_orders(db, driver.id, req.starts_at, req.ends_at)]
    else:
        docs = _documents(db, req.id)
        required = _required_vehicle_docs((req.vehicle_data or {}).get("vehicle_type"))
        # پس از تأیید، «خودروی فعلی» دیگر خودروی جدید است؛ عکس فوری خودروی قبلی نمایش داده می‌شود
        previous = (req.vehicle_data or {}).get("previous") if req.status == "approved" else None
        data.update(documents=docs, required_documents=required, missing=[k for k in required if k not in {d.kind for d in docs}],
                    current_vehicle=previous or _vehicle_dict(current_vehicle(db, driver)))
        if data["vehicle_data"]:
            data["vehicle_data"] = {k: v for k, v in data["vehicle_data"].items() if k != "previous"}
    return data


def _own_request(db: Session, user: User, request_id: int) -> DriverRequest:
    req = db.query(DriverRequest).filter(DriverRequest.id == request_id, DriverRequest.user_id == user.id).first()
    if req is None:
        raise NotFoundError("درخواست یافت نشد.")
    return req


def my_requests(db: Session, user: User) -> list[dict]:
    _require_driver(user)
    rows = db.query(DriverRequest).filter(DriverRequest.user_id == user.id).order_by(DriverRequest.id.desc()).all()
    return [request_dict(db, r, user) for r in rows]


def cancel_my_request(db: Session, user: User, request_id: int) -> dict:
    _require_driver(user)
    req = _own_request(db, user, request_id)
    if req.status in ("draft", "pending"):
        req.status = "canceled"
    elif req.status == "approved" and req.kind == "leave" and req.starts_at > _now():
        # مرخصی تأییدشده‌ای که هنوز شروع نشده قابل لغو است
        if req.time_off_id:
            off = db.get(DriverTimeOff, req.time_off_id)
            if off:
                db.delete(off)
        req.status = "canceled"
    else:
        raise ConflictError("این درخواست دیگر قابل لغو نیست.")
    db.commit()
    return request_dict(db, req, user)


# ---------------------------------------------------------------------------
# مرخصی
# ---------------------------------------------------------------------------
def create_leave(db: Session, user: User, data: LeaveRequestCreate) -> dict:
    _require_approved_driver(user)
    start, end = to_utc_naive(data.starts_at), to_utc_naive(data.ends_at)
    now = _now()
    if end <= now:
        raise ConflictError("بازه مرخصی گذشته است.")
    if data.leave_type == "normal" and start < now + NORMAL_LEAVE_NOTICE:
        raise ConflictError("مرخصی عادی باید دست‌کم ۲۴ ساعت زودتر درخواست شود؛ برای امروز و فردا «مرخصی فوری» بفرستید.")
    if data.leave_type == "urgent" and start > now + timedelta(days=2):
        raise ConflictError("مرخصی فوری فقط برای امروز و دو روز آینده است؛ برای بعد از آن «مرخصی عادی» بفرستید.")
    overlap = db.query(DriverRequest).filter(
        DriverRequest.user_id == user.id, DriverRequest.kind == "leave", DriverRequest.status.in_(("pending", "approved")),
        DriverRequest.starts_at < end, DriverRequest.ends_at > start,
    ).first()
    if overlap:
        raise ConflictError("برای این بازه قبلاً درخواست مرخصی ثبت کرده‌اید.")
    req = DriverRequest(user_id=user.id, organization_id=user.organization_id, kind="leave", status="pending",
                        submitted_at=now, leave_type=data.leave_type, category=data.category,
                        starts_at=max(start, now - timedelta(hours=1)), ends_at=end, reason=data.reason)
    db.add(req)
    db.flush()
    notification_service.driver_request(db, req, user)
    db.commit()
    return request_dict(db, req, user)


def _approve_leave(db: Session, admin: User, req: DriverRequest, driver: User) -> None:
    off = DriverTimeOff(user_id=driver.id, organization_id=driver.organization_id, created_by_id=admin.id,
                        starts_at=req.starts_at, ends_at=req.ends_at,
                        reason=f"{'مرخصی فوری' if req.leave_type == 'urgent' else 'مرخصی'} — {CATEGORY_LABELS.get(req.category, '')}: {req.reason}"[:200])
    db.add(off)
    db.flush()
    req.time_off_id = off.id
    # سفارش‌هایی که هنوز بارگیری نشده‌اند از راننده آزاد و «در انتظار تخصیص» می‌شوند؛
    # سفارش‌هایی که بار را گرفته (در مسیر) دست نمی‌خورند.
    for order in _affected_orders(db, driver.id, req.starts_at, req.ends_at):
        if order.status != "assigned":
            continue
        order.vehicle_id = None
        order.driver_id = None
        order.status = "pending"
        db.add(OrderStatusHistory(order_id=order.id, organization_id=order.organization_id, from_status="assigned",
                                  to_status="pending", changed_by_id=admin.id,
                                  note=f"آزاد شدن از راننده به‌دلیل مرخصی ({driver.full_name or driver.username})"))


# ---------------------------------------------------------------------------
# تغییر خودرو
# ---------------------------------------------------------------------------
def create_vehicle_change(db: Session, user: User, data: VehicleChangeCreate) -> dict:
    _require_approved_driver(user)
    open_request = db.query(DriverRequest).filter(DriverRequest.user_id == user.id, DriverRequest.kind == "vehicle_change",
                                                  DriverRequest.status.in_(("draft", "pending"))).first()
    if open_request:
        raise ConflictError("یک درخواست تغییر خودروی باز دارید؛ آن را تکمیل یا لغو کنید.")
    payload = data.model_dump(mode="json")
    note = payload.pop("note", None)
    req = DriverRequest(user_id=user.id, organization_id=user.organization_id, kind="vehicle_change", status="draft",
                        vehicle_data=payload, reason=note)
    db.add(req)
    db.commit()
    return request_dict(db, req, user)


def upload_request_document(db: Session, user: User, request_id: int, kind: str, data: bytes) -> dict:
    _require_driver(user)
    req = _own_request(db, user, request_id)
    if req.kind != "vehicle_change" or req.status != "draft":
        raise ConflictError("مدارک فقط برای درخواست تغییر خودروی ارسال‌نشده قابل بارگذاری است.")
    if kind not in VEHICLE_DOCUMENTS:
        raise ConflictError("این نوع مدرک برای تغییر خودرو لازم نیست.")
    if not data:
        raise ConflictError("فایل خالی است.")
    if len(data) > driver_service.MAX_IMAGE_BYTES:
        raise ConflictError("حجم فایل نباید بیشتر از ۵ مگابایت باشد.")
    try:
        ext = storage.detect_image(data)
    except storage.InvalidFileError as e:
        raise ConflictError(str(e))
    path = f"drivers/{user.organization_id}/{user.id}/requests/{req.id}/{kind}-{secrets.token_hex(6)}.{ext}"
    storage.save(path, data)
    doc = db.query(DriverRequestDocument).filter(DriverRequestDocument.request_id == req.id, DriverRequestDocument.kind == kind).first()
    old_path = doc.file_path if doc else None
    if doc is None:
        doc = DriverRequestDocument(request_id=req.id, organization_id=req.organization_id, kind=kind)
        db.add(doc)
    doc.file_path, doc.content_type, doc.size_bytes, doc.uploaded_at = path, storage.MEDIA_TYPES[ext], len(data), _now()
    db.commit()
    storage.delete(old_path)
    return request_dict(db, req, user)


def submit_vehicle_change(db: Session, user: User, request_id: int) -> dict:
    _require_driver(user)
    req = _own_request(db, user, request_id)
    if req.kind != "vehicle_change" or req.status != "draft":
        raise ConflictError("این درخواست قبلاً ارسال شده است.")
    v = req.vehicle_data or {}
    errors = []
    missing = [k for k in _required_vehicle_docs(v.get("vehicle_type")) if k not in {d.kind for d in _documents(db, req.id)}]
    if missing:
        errors.append("مدارک خودروی جدید کامل نیست.")
    limit = driver_service.WEIGHT_LIMITS.get(v.get("vehicle_type"))
    if limit and v.get("max_weight_kg", 0) > limit:
        errors.append(f"سقف بار {driver_service.VEHICLE_LABELS[v['vehicle_type']]} حداکثر {limit:,} کیلوگرم است.")
    if (v.get("vehicle_type") == "motorcycle") == bool(re.match(CAR_PLATE, v.get("license_plate", ""))):
        errors.append("قالب پلاک با نوع وسیله مطابقت ندارد.")
    if v.get("vehicle_type") != "motorcycle":
        expiry = v.get("inspection_expiry")
        if not expiry:
            errors.append("تاریخ اعتبار معاینه فنی را وارد کنید.")
        elif date.fromisoformat(expiry) < date.today():
            errors.append("اعتبار معاینه فنی خودروی جدید به پایان رسیده است.")
    if errors:
        raise ConflictError(fa_digits(" ".join(errors)))
    req.status, req.submitted_at = "pending", _now()
    notification_service.driver_request(db, req, user)
    db.commit()
    return request_dict(db, req, user)


def _approve_vehicle_change(db: Session, admin: User, req: DriverRequest, driver: User) -> None:
    v = req.vehicle_data or {}
    profile = driver_service._profile_of(db, driver)
    old = current_vehicle(db, driver)
    req.vehicle_data = {**v, "previous": _vehicle_dict(old)}   # برای نمایش «قبل/بعد» پس از تأیید
    same_plate = old is not None and old.license_plate == v["license_plate"]
    if not same_plate:
        clash = db.query(Vehicle).filter(Vehicle.license_plate == v["license_plate"]).first()
        if clash:
            raise ConflictError("خودرویی با این پلاک در ناوگان سازمان وجود دارد.")
        if old is not None:
            active = db.query(Order).filter(Order.vehicle_id == old.id, Order.status.in_(ACTIVE_ORDER_STATUSES)).count()
            if active:
                raise ConflictError(fa_digits(f"خودروی فعلی راننده {active} سفارش فعال دارد؛ ابتدا آن‌ها را تکمیل یا به راننده دیگری بدهید."))
    if same_plate:
        vehicle = old
    else:
        vehicle = Vehicle(driver_id=driver.id, license_plate=v["license_plate"], status="available",
                          city=(old.city if old else None) or profile.city or driver.city)
        db.add(vehicle)
        if old is not None:
            old.status = "inactive"   # خودروی قبلی با سابقه سفارش‌هایش نزد همین راننده می‌ماند
    vehicle.type, vehicle.model, vehicle.capacity_kg = v["vehicle_type"], v["vehicle_model"], v["max_weight_kg"]
    db.flush()

    profile.vehicle_type, profile.vehicle_model, profile.vehicle_color = v["vehicle_type"], v["vehicle_model"], v.get("vehicle_color")
    profile.license_plate, profile.max_weight_kg = v["license_plate"], v["max_weight_kg"]
    profile.inspection_expiry = date.fromisoformat(v["inspection_expiry"]) if v.get("inspection_expiry") else None
    profile.vehicle_id = vehicle.id
    # مدارک جدید جایگزین مدارک خودروی قبلی می‌شوند
    for doc in _documents(db, req.id):
        current = db.query(DriverDocument).filter(DriverDocument.user_id == driver.id, DriverDocument.kind == doc.kind).first()
        if current is None:
            current = DriverDocument(user_id=driver.id, organization_id=driver.organization_id, kind=doc.kind)
            db.add(current)
        current.file_path, current.content_type = doc.file_path, doc.content_type
        current.size_bytes, current.uploaded_at = doc.size_bytes, doc.uploaded_at
    if v.get("vehicle_type") == "motorcycle":
        db.query(DriverDocument).filter(DriverDocument.user_id == driver.id, DriverDocument.kind == "technical_inspection").delete()


# ---------------------------------------------------------------------------
# بررسی ادمین
# ---------------------------------------------------------------------------
def list_requests(db: Session, user: User, status: str | None = None, kind: str | None = None) -> list[dict]:
    _require_admin(user)
    query = db.query(DriverRequest).filter(DriverRequest.status != "draft")
    if status:
        query = query.filter(DriverRequest.status == status)
    if kind:
        query = query.filter(DriverRequest.kind == kind)
    rows = query.order_by((DriverRequest.status == "pending").desc(), (DriverRequest.leave_type == "urgent").desc(),
                          DriverRequest.id.desc()).all()
    return [request_dict(db, r) for r in rows]


def pending_counts(db: Session, user: User) -> dict:
    _require_admin(user)
    rows = db.query(DriverRequest).filter(DriverRequest.status == "pending").all()
    return {"count": len(rows), "urgent": sum(1 for r in rows if r.leave_type == "urgent")}


def _pending_request(db: Session, request_id: int) -> tuple[DriverRequest, User]:
    req = db.query(DriverRequest).filter(DriverRequest.id == request_id).first()
    if req is None or req.status == "draft":
        raise NotFoundError("درخواست یافت نشد.")
    if req.status != "pending":
        raise ConflictError("این درخواست قبلاً بررسی شده است.")
    return req, db.get(User, req.user_id)


def approve_request(db: Session, user: User, request_id: int, note: str | None) -> dict:
    _require_admin(user)
    req, driver = _pending_request(db, request_id)
    try:
        if req.kind == "leave":
            _approve_leave(db, user, req, driver)
        else:
            _approve_vehicle_change(db, user, req, driver)
        req.status, req.reviewed_at, req.reviewed_by_id, req.review_note = "approved", _now(), user.id, note or None
        notification_service.request_result(db, req, driver, True, note, user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return request_dict(db, req, driver)


def reject_request(db: Session, user: User, request_id: int, note: str | None) -> dict:
    _require_admin(user)
    if not note or len(note.strip()) < 3:
        raise ConflictError("دلیل رد را بنویسید (برای راننده نمایش داده می‌شود).")
    req, driver = _pending_request(db, request_id)
    req.status, req.reviewed_at, req.reviewed_by_id, req.review_note = "rejected", _now(), user.id, note
    notification_service.request_result(db, req, driver, False, note, user)
    db.commit()
    return request_dict(db, req, driver)


def request_document_file(db: Session, viewer: User, request_id: int, kind: str):
    req = db.query(DriverRequest).filter(DriverRequest.id == request_id).first()
    if req is None or not (viewer.role == "org_admin" or (viewer.role == "driver" and req.user_id == viewer.id)):
        raise NotFoundError("مدرک یافت نشد.")
    doc = db.query(DriverRequestDocument).filter(DriverRequestDocument.request_id == req.id, DriverRequestDocument.kind == kind).first()
    path = storage.path_of(doc.file_path) if doc else None
    if path is None:
        raise NotFoundError("این مدرک بارگذاری نشده است.")
    return path, doc.content_type

