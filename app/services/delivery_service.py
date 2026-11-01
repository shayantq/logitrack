"""
مدرک تحویل و تلاش‌های تحویل هر سفارش (docs/productivity.md، B2).

عکس مدرک آدرس عمومی ندارد: فقط کارکنان همان سازمان و راننده همان تلاش آن را می‌بینند و مشاهده کارکنان
در گزارش فعالیت ثبت می‌شود. صفحه رهگیری مشتری هیچ‌کدام از این‌ها را نشان نمی‌دهد.
"""
import hashlib
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core import storage
from app.models import Order, User, Vehicle
from app.models_productivity import DeliveryAttempt, DeliveryEvidence, DeliveryEvidenceEvent, DeliveryEvidenceNote
from app.services import audit_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

logger = logging.getLogger("pasineh")
MAX_PHOTO_BYTES = 5 * 1024 * 1024
DELIVERY_METHOD_LABELS = {"handed_to_recipient": "تحویل به گیرنده", "left_at_door": "گذاشتن پشت در", "other": "سایر", "unrecorded": "ثبت نشده (داده قدیمی)"}
RECIPIENT_ROLE_LABELS = {"self": "خود گیرنده", "family": "خانواده", "colleague": "همکار", "guard": "نگهبان", "other": "دیگر"}
FAILURE_REASON_LABELS = {
    "recipient_absent": "گیرنده در دسترس نبود", "wrong_address": "نشانی نادرست", "refused": "گیرنده تحویل نگرفت",
    "damaged": "کالا آسیب دیده بود", "access_issue": "دسترسی به محل ممکن نبود", "vehicle_issue": "مشکل خودرو", "other": "سایر",
}
RESOLUTION_LABELS = {"redeliver": "تحویل دوباره", "return_to_warehouse": "برگشت به انبار", "dispute": "اختلاف"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
        "resolved_at": attempt.resolved_at, "has_photo": bool(attempt.photo_path), "photo_type": attempt.photo_type, "evidence": _evidence(db, attempt),
        "partial": bool(attempt.partial), "lines": list(attempt.lines),
    }


def attempts(db: Session, user: User, order_id: int) -> list[dict]:
    order = _order(db, user, order_id)
    query = db.query(DeliveryAttempt).filter(DeliveryAttempt.order_id == order.id)
    if user.role == "driver":
        query = query.filter(DeliveryAttempt.driver_id == user.id)
    return [serialize(db, a) for a in query.order_by(DeliveryAttempt.attempt_no).all()]


def _evidence_out(row: DeliveryEvidence, note: str | None, deleted_at, names: dict) -> dict:
    return {"id": row.id, "photo_type": row.photo_type, "delivery_method": row.delivery_method,
            "delivery_method_label": DELIVERY_METHOD_LABELS[row.delivery_method], "method_note": note, "media_type": row.media_type,
            "size_bytes": row.size_bytes, "sha256": row.sha256, "uploaded_at": row.uploaded_at, "uploaded_by_name": names.get(row.uploaded_by_id),
            "file_deleted": deleted_at is not None, "file_deleted_at": deleted_at}


def _evidence(db: Session, attempt: DeliveryAttempt) -> list[dict]:
    rows = db.query(DeliveryEvidence).filter(DeliveryEvidence.attempt_id == attempt.id).order_by(DeliveryEvidence.id).all()
    if not rows:
        return []
    ids = [r.id for r in rows]
    notes = dict(db.query(DeliveryEvidenceNote.evidence_id, DeliveryEvidenceNote.note).filter(DeliveryEvidenceNote.evidence_id.in_(ids)).all())
    deleted = dict(db.query(DeliveryEvidenceEvent.evidence_id, DeliveryEvidenceEvent.at).filter(
        DeliveryEvidenceEvent.evidence_id.in_(ids), DeliveryEvidenceEvent.event_type == "file_deleted").all())
    uploaders = {r.uploaded_by_id for r in rows if r.uploaded_by_id}
    names = {u.id: u.full_name or u.username for u in db.query(User).filter(User.id.in_(uploaders)).all()} if uploaders else {}
    return [_evidence_out(r, notes.get(r.id), deleted.get(r.id), names) for r in rows]


def save_photo(db: Session, user: User, order_id: int, attempt_no: int, data: bytes, photo_type: str, delivery_method: str,
               method_note: str | None = None) -> dict:
    attempt = _attempt(db, user, order_id, attempt_no)
    if user.role not in ("driver", "org_admin"):
        raise ForbiddenError("عکس مدرک را راننده همان تلاش یا ادمین سازمان ثبت می‌کند.")
    if not data:
        raise ConflictError("فایل خالی است.")
    if len(data) > MAX_PHOTO_BYTES:
        raise ConflictError("حجم تصویر نباید بیشتر از ۵ مگابایت باشد.")
    note = (method_note or "").strip()
    if delivery_method == "other" and len(note) < 3:
        raise ConflictError("برای روش «سایر» توضیح بنویسید.")
    if delivery_method != "other" and note:
        raise ConflictError("توضیح فقط برای روش «سایر» ثبت می‌شود.")
    try:
        ext = storage.detect_image(data)
    except storage.InvalidFileError as e:
        raise ConflictError(str(e))
    # کلید تازه برای هر آپلود: فایل قبلی هرگز بازنویسی یا پاک نمی‌شود
    key = storage.save_new(f"deliveries/{attempt.organization_id}/{order_id}/{attempt_no}/{uuid.uuid4().hex}.{ext}", data)
    try:
        row = DeliveryEvidence(attempt_id=attempt.id, storage_key=key, photo_type=photo_type, delivery_method=delivery_method,
                               media_type=storage.MEDIA_TYPES[ext], size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                               uploaded_by_id=user.id, uploaded_at=_now())
        db.add(row)
        db.flush()
        if note:
            db.add(DeliveryEvidenceNote(evidence_id=row.id, note=note))
        attempt.photo_path, attempt.photo_type = key, photo_type
        audit_service.log(db, user, "order.delivery_evidence_upload", f"مدرک تحویل تلاش {attempt_no} ثبت شد",
                          target_type="order", target_id=order_id, details={"evidence_id": row.id, "sha256": row.sha256})
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(key)
        raise
    return serialize(db, attempt)


def evidence_list(db: Session, user: User, order_id: int, attempt_no: int) -> list[dict]:
    return _evidence(db, _attempt(db, user, order_id, attempt_no))


def _serve(db: Session, user: User, order_id: int, attempt_no: int, row: DeliveryEvidence):
    path = storage.path_of(row.storage_key)
    if path is None:
        deleted = db.query(DeliveryEvidenceEvent.id).filter(DeliveryEvidenceEvent.evidence_id == row.id, DeliveryEvidenceEvent.event_type == "file_deleted").first()
        raise NotFoundError("فایل این مدرک طبق سیاست نگهداری پاک شده است." if deleted else "فایل این مدرک پیدا نشد.")
    if row.sha256 and hashlib.sha256(path.read_bytes()).hexdigest() != row.sha256:
        logger.error("hash فایل مدرک تحویل نمی‌خواند: evidence_id=%s", row.id)
        raise ConflictError("فایل با hash ثبت‌شده نمی‌خواند و نمایش داده نمی‌شود.")
    if user.role != "driver":
        order = db.get(Order, order_id)
        audit_service.record(db, user, "order.delivery_photo_view", f"عکس تلاش {attempt_no} سفارش {order.tracking_code} دیده شد",
                             target_type="order", target_id=order_id, target_label=order.tracking_code)
    return path, storage.MEDIA_TYPES[path.suffix.lstrip(".")]


def evidence_file(db: Session, user: User, order_id: int, attempt_no: int, evidence_id: int):
    attempt = _attempt(db, user, order_id, attempt_no)
    row = db.query(DeliveryEvidence).filter(DeliveryEvidence.id == evidence_id, DeliveryEvidence.attempt_id == attempt.id).first()
    if row is None:
        raise NotFoundError("این مدرک یافت نشد.")
    return _serve(db, user, order_id, attempt_no, row)


def photo_file(db: Session, user: User, order_id: int, attempt_no: int):
    """مسیر قدیمی: تازه‌ترین مدرک همان تلاش."""
    attempt = _attempt(db, user, order_id, attempt_no)
    row = db.query(DeliveryEvidence).filter(DeliveryEvidence.attempt_id == attempt.id).order_by(DeliveryEvidence.id.desc()).first()
    if row is None:
        raise NotFoundError("برای این تلاش عکسی ثبت نشده است.")
    return _serve(db, user, order_id, attempt_no, row)
