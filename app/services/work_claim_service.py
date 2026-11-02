"""
برداشتن کار انبار (ت۱۸): تخصیص دائمی نفر به کار نداریم. اپراتور کار را برای مدت کوتاهی برمی‌دارد و اگر برگردد یا مهلت بگذرد، کار به صف برمی‌گردد.
برداشتن یک UPDATE شرطی است، پس از چند درخواست همزمان فقط یکی موفق می‌شود. مدیر و ادمین برای نظارت به برداشتن نیاز ندارند.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import User
from app.services import location_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

CLAIM_DURATION = timedelta(minutes=15)
OPERATOR = "warehouse_operator"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def _get(db: Session, user: User, model, row_id: int):
    row = db.query(model).filter(model.id == row_id).first()
    if row is None:
        raise NotFoundError("این کار یافت نشد.")
    location_service.scope_warehouse_work(user, row.warehouse_id)
    return row


def claim(db: Session, user: User, model, row_id: int, statuses: tuple[str, ...]) -> dict:
    _get(db, user, model, row_id)
    now = _now()
    until = now + CLAIM_DURATION
    claimed = db.query(model).filter(
        model.id == row_id, model.status.in_(statuses),
        or_(model.claimed_by_id.is_(None), model.claimed_until < now, model.claimed_by_id == user.id),
    ).update({model.claimed_by_id: user.id, model.claimed_until: until}, synchronize_session=False)
    db.commit()
    if not claimed:
        raise ConflictError("این کار بسته شده یا همکار دیگری آن را برداشته است.")
    return {"claimed_by_id": user.id, "claimed_until": until}


def release(db: Session, user: User, model, row_id: int) -> dict:
    row = _get(db, user, model, row_id)
    if row.claimed_by_id != user.id and _role(user) == OPERATOR:
        raise ForbiddenError("فقط کسی که این کار را برداشته می‌تواند آن را برگرداند.")
    db.query(model).filter(model.id == row_id).update({model.claimed_by_id: None, model.claimed_until: None}, synchronize_session=False)
    db.commit()
    return {"claimed_by_id": None, "claimed_until": None}


def ensure_holder(row, user: User) -> None:
    """صدا زده می‌شود وقتی ردیف قفل است، پس مهلت و دارنده در همان تراکنش سنجیده می‌شوند."""
    if _role(user) != OPERATOR:
        return
    if row.claimed_by_id != user.id or row.claimed_until is None or row.claimed_until < _now():
        raise ConflictError("اول این کار را از صف بردارید؛ مهلت شما گذشته یا همکار دیگری آن را برداشته است.")


def clear(row) -> None:
    row.claimed_by_id, row.claimed_until = None, None
