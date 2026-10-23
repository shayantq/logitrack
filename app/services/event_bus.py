"""
رویدادهای دامنه (Transactional Outbox)

هر تغییر مهم یک DomainEvent غیرقابل‌تغییر می‌سازد که در «همان تراکنش» عملیات ذخیره می‌شود: اگر عملیات
rollback شود رویداد هم نیست و اگر commit شود حتماً هست — بدون شکستن اتمی بودن تغییر وضعیت.

رویدادهای انبار و کاتالوگ در after_flush پایین همین فایل به‌طور مرکزی ساخته می‌شوند (هر مسیر کدی که سند
ثبت کند یا رزرو بسازد، رویدادش را هم دارد)؛ رویدادهای دیگر با emit() از سرویس‌ها. مصرف‌کننده‌ها
(گزارش، وب‌هوک، یکپارچه‌سازی آینده) با GET /wms/events?after_id=... به ترتیب شناسه دنبالشان می‌کنند.
رویدادهایی که در after_flush اضافه می‌شوند در flush بعدیِ همان commit ذخیره می‌شوند.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.models import DomainEvent, Partner, Product, StockDocument, StockReservation, User, Warehouse

ACTOR_KEY = "actor"
# فیلدهایی که تغییرشان رویداد «ویرایش» نمی‌سازد (کش و زمان‌ها)
_QUIET_FIELDS = {"price", "updated_at", "created_at"}


def set_actor(db: Session, user: User | None) -> None:
    """کاربر درخواست جاری (برای ثبت «چه کسی» در رویدادها) — در get_current_user تنظیم می‌شود."""
    if user is None:
        db.info.pop(ACTOR_KEY, None)
    else:
        db.info[ACTOR_KEY] = (user.id, user.full_name or user.username)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def emit(db: Session, event_type: str, aggregate_type: str, aggregate_id: int, payload: dict | None = None, *,
         organization_id: int, actor: User | None = None) -> DomainEvent:
    actor_id, actor_name = (actor.id, actor.full_name or actor.username) if actor else db.info.get(ACTOR_KEY, (None, None))
    row = DomainEvent(organization_id=organization_id, occurred_at=_now(), event_type=event_type,
                      aggregate_type=aggregate_type, aggregate_id=aggregate_id, actor_id=actor_id,
                      actor_name=actor_name, payload=payload or {})
    db.add(row)
    return row


def _document_payload(doc: StockDocument) -> dict:
    return {
        "code": doc.code, "doc_type": doc.doc_type, "status": doc.status, "warehouse_id": doc.warehouse_id,
        "partner_id": doc.partner_id, "reference_type": doc.reference_type, "reference_id": doc.reference_id,
        "reversal_of_id": doc.reversal_of_id,
        "lines": [{"movement_id": m.id, "product_id": m.product_id, "warehouse_id": m.warehouse_id,
                   "stock_status": m.stock_status, "movement_type": m.movement_type,
                   "quantity_change": m.quantity_change, "balance_after": m.balance_after} for m in doc.movements],
    }


def _reservation_payload(r: StockReservation) -> dict:
    return {"product_id": r.product_id, "warehouse_id": r.warehouse_id, "inventory_id": r.inventory_id,
            "quantity": r.quantity, "reference_type": r.reference_type, "reference_id": r.reference_id,
            "movement_id": r.movement_id}


def _changed_fields(obj) -> list[str]:
    state = inspect(obj)
    return sorted(a.key for a in state.mapper.column_attrs
                  if a.key not in _QUIET_FIELDS and state.attrs[a.key].history.has_changes())


_MASTER = {Product: ("product", lambda p: {"sku": p.sku, "name": p.name}),
           Warehouse: ("warehouse", lambda w: {"code": w.code, "name": w.name, "type": w.type}),
           Partner: ("partner", lambda p: {"code": p.code, "name": p.name})}


@event.listens_for(Session, "after_flush")
def _collect_events(session, flush_context):
    for obj in list(session.new):
        if isinstance(obj, StockDocument) and obj.status == "posted":
            emit(session, "stock.document.posted", "stock_document", obj.id, _document_payload(obj),
                 organization_id=obj.organization_id)
        elif isinstance(obj, StockReservation):
            emit(session, "stock.reserved", "stock_reservation", obj.id, _reservation_payload(obj),
                 organization_id=obj.organization_id)
            if obj.status in ("released", "consumed"):        # رزرو و بستن در همان تراکنش
                emit(session, f"stock.reservation.{obj.status}", "stock_reservation", obj.id,
                     {**_reservation_payload(obj), "reason": obj.close_reason}, organization_id=obj.organization_id)
        elif type(obj) in _MASTER:
            name, payload = _MASTER[type(obj)]
            emit(session, f"{name}.created", name, obj.id, payload(obj), organization_id=obj.organization_id)

    for obj in list(session.dirty):
        if isinstance(obj, StockDocument):
            history = inspect(obj).attrs.status.history
            if history.has_changes() and obj.status == "reversed":
                emit(session, "stock.document.reversed", "stock_document", obj.id,
                     {"code": obj.code, "doc_type": obj.doc_type}, organization_id=obj.organization_id)
        elif isinstance(obj, StockReservation):
            history = inspect(obj).attrs.status.history
            if history.has_changes() and obj.status in ("released", "consumed"):
                emit(session, f"stock.reservation.{obj.status}", "stock_reservation", obj.id,
                     {**_reservation_payload(obj), "reason": obj.close_reason}, organization_id=obj.organization_id)
        elif type(obj) in _MASTER:
            fields = _changed_fields(obj)
            if fields:
                name, payload = _MASTER[type(obj)]
                emit(session, f"{name}.updated", name, obj.id, {**payload(obj), "fields": fields},
                     organization_id=obj.organization_id)
