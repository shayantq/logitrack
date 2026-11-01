"""
مدرک تحویل و تلاش‌های تحویل هر سفارش (docs/productivity.md، B2).

عکس مدرک آدرس عمومی ندارد: فقط کارکنان همان سازمان و راننده همان تلاش آن را می‌بینند و مشاهده کارکنان
در گزارش فعالیت ثبت می‌شود. صفحه رهگیری مشتری هیچ‌کدام از این‌ها را نشان نمی‌دهد.
"""
from sqlalchemy.orm import Session

from app.core import storage
from app.models import Order, User, Vehicle
from app.models_productivity import DeliveryAttempt
from app.services import audit_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

MAX_PHOTO_BYTES = 5 * 1024 * 1024
RECIPIENT_ROLE_LABELS = {"self": "خود گیرنده", "family": "خانواده", "colleague": "همکار", "guard": "نگهبان", "other": "دیگر"}
FAILURE_REASON_LABELS = {
    "recipient_absent": "گیرنده در دسترس نبود", "wrong_address": "نشانی نادرست", "refused": "گیرنده تحویل نگرفت",
    "damaged": "کالا آسیب دیده بود", "access_issue": "دسترسی به محل ممکن نبود", "vehicle_issue": "مشکل خودرو", "other": "سایر",
}
RESOLUTION_LABELS = {"redeliver": "تحویل دوباره", "return_to_warehouse": "برگشت به انبار", "dispute": "اختلاف"}


def _order(db: Session, user: User, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if order is None or user.role not in ("org_admin", "warehouse_manager", "driver"):
        raise NotFoundError("سفارش مورد نظر یافت نشد.")
    return order


def _attempt(db: Session, user: User, order_id: int, attempt_no: int) -> DeliveryAttempt:
    order = _order(db, user, order_id)
    attempt = db.query(DeliveryAttempt).filter(DeliveryAttempt.order_id == order.id, DeliveryAttempt.attempt_no == attempt_no).first()
    # راننده فقط تلاش خودش را می‌بیند؛ 404 تا وجود تلاش دیگران فاش نشود
    if attempt is None or (user.role == "driver" and attempt.driver_id != user.id):
        raise NotFoundError("این تلاش تحویل یافت نشد.")
    return attempt


def serialize(db: Session, attempt: DeliveryAttempt) -> dict:
    ids = {i for i in (attempt.driver_id, attempt.resolved_by_id) if i}
    people = {u.id: u.full_name or u.username for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}
    vehicle = db.get(Vehicle, attempt.vehicle_id) if attempt.vehicle_id else None
    return {
        "id": attempt.id, "attempt_no": attempt.attempt_no, "outcome": attempt.outcome, "at": attempt.at,
        "driver_name": people.get(attempt.driver_id), "vehicle_plate": vehicle.license_plate if vehicle else None,
        "recipient_name": attempt.recipient_name, "recipient_role_label": RECIPIENT_ROLE_LABELS.get(attempt.recipient_role),
        "exception_note": attempt.exception_note, "failure_reason": attempt.failure_reason,
        "failure_reason_label": FAILURE_REASON_LABELS.get(attempt.failure_reason), "note": attempt.note,
        "next_attempt_at": attempt.next_attempt_at, "resolution": attempt.resolution,
        "resolution_label": RESOLUTION_LABELS.get(attempt.resolution), "resolved_by_name": people.get(attempt.resolved_by_id),
        "resolved_at": attempt.resolved_at, "has_photo": bool(attempt.photo_path), "photo_type": attempt.photo_type,
    }


def attempts(db: Session, user: User, order_id: int) -> list[dict]:
    order = _order(db, user, order_id)
    query = db.query(DeliveryAttempt).filter(DeliveryAttempt.order_id == order.id)
    if user.role == "driver":
        query = query.filter(DeliveryAttempt.driver_id == user.id)
    return [serialize(db, a) for a in query.order_by(DeliveryAttempt.attempt_no).all()]


def save_photo(db: Session, user: User, order_id: int, attempt_no: int, data: bytes, photo_type: str) -> dict:
    attempt = _attempt(db, user, order_id, attempt_no)
    if user.role not in ("driver", "org_admin"):
        raise ForbiddenError("عکس مدرک را راننده همان تلاش یا ادمین سازمان ثبت می‌کند.")
    if not data:
        raise ConflictError("فایل خالی است.")
    if len(data) > MAX_PHOTO_BYTES:
        raise ConflictError("حجم تصویر نباید بیشتر از ۵ مگابایت باشد.")
    try:
        ext = storage.detect_image(data)
    except storage.InvalidFileError as e:
        raise ConflictError(str(e))
    previous = attempt.photo_path
    attempt.photo_path = storage.save(f"deliveries/{attempt.organization_id}/{order_id}/{attempt_no}.{ext}", data)
    attempt.photo_type = photo_type
    db.commit()
    if previous and previous != attempt.photo_path:
        storage.delete(previous)
    return serialize(db, attempt)


def photo_file(db: Session, user: User, order_id: int, attempt_no: int):
    attempt = _attempt(db, user, order_id, attempt_no)
    path = storage.path_of(attempt.photo_path) if attempt.photo_path else None
    if path is None:
        raise NotFoundError("برای این تلاش عکسی ثبت نشده است.")
    if user.role != "driver":
        order = db.get(Order, order_id)
        audit_service.record(db, user, "order.delivery_photo_view", f"عکس تلاش {attempt_no} سفارش {order.tracking_code} مشاهده شد",
                             target_type="order", target_id=order_id, target_label=order.tracking_code)
    return path, storage.MEDIA_TYPES[path.suffix.lstrip(".")]
