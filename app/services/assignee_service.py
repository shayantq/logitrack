"""
مسئول پیشنهادی برای تیکت و استثنا (docs/productivity.md، C3): کم‌کارترین کاربر نقش مسئول، بر اساس شمار موارد باز.
فقط پیشنهاد است و چیزی خودکار تخصیص داده نمی‌شود.
"""
from collections import Counter

from sqlalchemy.orm import Session

from app.models import Ticket, User
from app.models_productivity import ACTIVE_EXCEPTION_STATUSES, OperationException


def _load(db: Session) -> Counter:
    counts: Counter = Counter()
    for (owner,) in db.query(OperationException.owner_id).filter(
            OperationException.owner_id.is_not(None), OperationException.status.in_(ACTIVE_EXCEPTION_STATUSES)).all():
        counts[owner] += 1
    for (owner,) in db.query(Ticket.assignee_id).filter(Ticket.assignee_id.is_not(None), Ticket.status == "open").all():
        counts[owner] += 1
    return counts


def _staff(db: Session) -> list[User]:
    return db.query(User).filter(User.role.in_(("org_admin", "warehouse_manager")), User.is_active.is_not(False)).order_by(User.id).all()


def _pick(people: list[User], load: Counter) -> dict | None:
    if not people:
        return None
    best = min(people, key=lambda u: (load[u.id], u.id))
    return {"id": best.id, "name": best.full_name or best.username, "open_count": load[best.id]}


def _for_warehouse(staff: list[User], warehouse_id: int | None, *, include_admins: bool) -> list[User]:
    managers = [u for u in staff if u.role == "warehouse_manager" and warehouse_id and u.warehouse_id == warehouse_id]
    admins = [u for u in staff if u.role == "org_admin"]
    if include_admins:
        return managers + admins
    return managers or admins


def exception_suggester(db: Session):
    """تابع پیشنهاد برای فهرست استثناها؛ بار کاری فقط یک بار و در صورت نیاز خوانده می‌شود."""
    cache: dict = {}

    def suggest(item: OperationException) -> dict | None:
        if not cache:
            cache.update(staff=_staff(db), load=_load(db))
        people = _for_warehouse(cache["staff"], item.warehouse_id, include_admins=False) if item.team == "warehouse" \
            else [u for u in cache["staff"] if u.role == "org_admin"]
        return _pick(people, cache["load"])
    return suggest


def for_ticket(db: Session, warehouse_id: int | None) -> dict | None:
    return _pick(_for_warehouse(_staff(db), warehouse_id, include_admins=True), _load(db))
