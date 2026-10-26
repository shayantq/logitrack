"""
گزارش فعالیت (مرحله ۱۵).

`log()` فقط ردیف را به Session اضافه می‌کند تا با همان تراکنشِ عملیات ثبت شود؛ `record()` خودش commit می‌کند
(برای وقتی که عملیات اصلی قبلاً commit شده). IP و مرورگر از app/core/request_context می‌آید.

«فعالیت یک کاربر» ترکیبی است از این گزارش + تغییر وضعیت سفارش‌ها + گردش‌های انبار که او ثبت کرده؛
پس برای کارهایی که خودشان سابقه دارند (سفارش، دفتر گردش) ردیف تکراری ثبت نمی‌شود.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.core import request_context
from app.models import AuditLog, Order, OrderStatusHistory, StockMovement, User
from app.services import dispatch_service
from app.services.exceptions import ForbiddenError, NotFoundError

CATEGORIES = {
    "auth": "ورود و امنیت", "users": "کاربران", "settings": "تنظیمات سازمان", "catalog": "کاتالوگ و قیمت",
    "reports": "گزارش‌گیری", "drivers": "رانندگان", "partners": "طرف‌های تجاری", "orders": "سفارش‌ها",
    "inventory": "موجودی و انبارگردانی", "security": "مجوزها و امنیت", "labels": "برچسب و بارکد",
    "system": "راه‌اندازی و داده",
}
ACTION_CATEGORY = {
    "auth.login": "auth", "auth.login_failed": "auth", "auth.locked": "auth", "auth.password_changed": "auth",
    "auth.reset_requested": "auth", "auth.password_reset": "auth",
    "user.create": "users", "user.update": "users", "user.deactivate": "users", "user.activate": "users",
    "user.reset_password": "users", "user.unlock": "users", "user.delete": "users",
    "org.profile": "settings", "org.logo": "settings", "org.brand": "settings", "commission.plan": "settings",
    "warehouse.create": "settings", "warehouse.update": "settings", "warehouse.delete": "settings",
    "location.create": "settings", "location.update": "settings", "location.delete": "settings",
    "catalog.import": "catalog", "catalog.price": "catalog", "catalog.price_delete": "catalog", "catalog.update": "catalog",
    "report.generate": "reports",
    "inventory.policy": "settings", "inventory.rop": "catalog", "inventory.rop_auto": "catalog",
    "driver.invite": "drivers", "driver.approve": "drivers", "driver.reject": "drivers",
    "catalog.delete": "catalog", "catalog.uoms": "catalog", "catalog.suppliers": "catalog", "order.delete": "orders",
    "partner.create": "partners", "partner.update": "partners", "partner.archive": "partners",
    "partner.activate": "partners", "partner.delete": "partners",
    "stock.adjust": "inventory", "stock.reverse": "inventory", "stock.status_change": "inventory", "stock.disposition": "inventory",
    "stocktake.create": "inventory", "stocktake.approve": "inventory", "stocktake.cancel": "inventory",
    "stocktake.recount": "inventory", "location.lock": "inventory", "valuation.method": "settings",
    "permission.update": "security", "permission.reset": "security",
    "label.print": "labels", "label.reprint": "labels",
    "data.import": "system", "cutover.check": "system",
}


def actor_label(user: User | None) -> str | None:
    return (user.full_name or user.username) if user is not None else None


def log(db: Session, actor: User | None, action: str, summary: str, *, target: User | None = None,
        target_type: str | None = None, target_id: int | None = None, target_label: str | None = None,
        details: dict | None = None, organization_id: int | None = None, reason: str | None = None) -> AuditLog:
    if target is not None:
        target_type, target_id, target_label = "user", target.id, target_label or actor_label(target)
    org_id = organization_id
    if org_id is None:
        org_id = actor.organization_id if actor is not None else (target.organization_id if target is not None else None)
    row = AuditLog(organization_id=org_id, actor_id=actor.id if actor is not None else None, actor_name=actor_label(actor),
                   action=action, category=ACTION_CATEGORY.get(action, action.split(".")[0][:16]),
                   target_type=target_type, target_id=target_id, target_label=(target_label or None) and target_label[:200],
                   summary=summary[:500], reason=(reason or None) and reason[:500], details=details,
                   ip=request_context.client_ip.get(),
                   user_agent=request_context.user_agent.get())
    db.add(row)
    return row


def record(db: Session, actor: User | None, action: str, summary: str, **kwargs) -> None:
    """ثبت مستقل (commit جدا). خطای ثبت گزارش نباید عملیات اصلیِ انجام‌شده را خراب کند."""
    try:
        log(db, actor, action, summary, **kwargs)
        db.commit()
    except Exception:  # pragma: no cover - فقط محافظ
        db.rollback()


def _require_admin(user: User, db: Session | None = None) -> None:
    if db is not None:
        from app.services import permission_service
        permission_service.ensure(db, user, "audit.view", "گزارش فعالیت فقط برای ادمین سازمان است.")
        return
    if getattr(user.role, "value", user.role) != "org_admin":
        raise ForbiddenError("گزارش فعالیت فقط برای ادمین سازمان است.")


def _bounds(date_from: date | None, date_to: date | None):
    lo = dispatch_service.local_to_utc(datetime.combine(date_from, time.min)) if date_from else None
    hi = dispatch_service.local_to_utc(datetime.combine(date_to + timedelta(days=1), time.min)) if date_to else None
    return lo, hi


def _out(row: AuditLog) -> dict:
    return {"id": row.id, "at": row.created_at, "actor_id": row.actor_id, "actor_name": row.actor_name, "action": row.action,
            "category": row.category, "target_type": row.target_type, "target_id": row.target_id, "target_label": row.target_label,
            "summary": row.summary, "reason": row.reason, "details": row.details, "ip": row.ip, "user_agent": row.user_agent}


def _filtered(db: Session, *, actor_id: int | None = None, category: str | None = None, q: str | None = None,
              date_from: date | None = None, date_to: date | None = None, action: str | None = None,
              target_type: str | None = None, target_id: int | None = None):
    query = db.query(AuditLog)
    if actor_id:
        query = query.filter(or_(AuditLog.actor_id == actor_id, (AuditLog.target_type == "user") & (AuditLog.target_id == actor_id)))
    if category:
        query = query.filter(AuditLog.category == category)
    if action:
        query = query.filter(AuditLog.action == action)
    if target_type:
        query = query.filter(AuditLog.target_type == target_type)
    if target_id:
        query = query.filter(AuditLog.target_id == target_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(AuditLog.summary.ilike(like), AuditLog.actor_name.ilike(like), AuditLog.target_label.ilike(like),
                                 AuditLog.ip.ilike(like), AuditLog.reason.ilike(like)))
    return query


def list_logs(db: Session, user: User, *, actor_id: int | None = None, category: str | None = None, q: str | None = None,
              date_from: date | None = None, date_to: date | None = None, limit: int = 50, offset: int = 0,
              action: str | None = None, target_type: str | None = None, target_id: int | None = None) -> dict:
    _require_admin(user, db)
    query = _filtered(db, actor_id=actor_id, category=category, q=q, action=action, target_type=target_type, target_id=target_id)
    lo, hi = _bounds(date_from, date_to)
    if lo:
        query = query.filter(AuditLog.created_at >= lo)
    if hi:
        query = query.filter(AuditLog.created_at < hi)
    total = query.count()
    rows = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset(offset).limit(min(limit, 200)).all()
    return {"total": total, "items": [_out(r) for r in rows], "categories": CATEGORIES}


def user_activity(db: Session, admin: User, user_id: int, limit: int = 60) -> list[dict]:
    """خط زمانی یک کاربر: گزارش فعالیت + وضعیت‌هایی که روی سفارش‌ها زده + گردش‌های انبار که ثبت کرده."""
    _require_admin(admin)
    target = db.get(User, user_id)
    if target is None:
        raise NotFoundError("کاربر یافت نشد.")
    from app.services.order_service import STATUS_LABELS
    from app.services.report_data import MOVEMENT_LABELS
    items: list[dict] = []
    for r in db.query(AuditLog).filter(or_(AuditLog.actor_id == user_id, (AuditLog.target_type == "user") & (AuditLog.target_id == user_id))) \
            .order_by(AuditLog.created_at.desc()).limit(limit).all():
        items.append({"at": r.created_at, "kind": "audit", "category": r.category, "action": r.action, "title": r.summary,
                      "detail": f"توسط {r.actor_name}" if r.actor_id and r.actor_id != user_id and r.actor_name else None,
                      "order_id": None, "ip": r.ip})
    history = db.query(OrderStatusHistory).filter(OrderStatusHistory.changed_by_id == user_id) \
        .order_by(OrderStatusHistory.changed_at.desc()).limit(limit).all()
    codes = dict(db.query(Order.id, Order.tracking_code).filter(Order.id.in_({h.order_id for h in history})).all()) if history else {}
    for h in history:
        code = codes.get(h.order_id, f"#{h.order_id}")
        title = f"سفارش {code} ثبت شد" if h.from_status is None else \
            f"سفارش {code}: {STATUS_LABELS.get(h.from_status, h.from_status)} ← {STATUS_LABELS.get(h.to_status, h.to_status)}"
        items.append({"at": h.changed_at, "kind": "order", "category": "orders", "action": f"order.{h.to_status}", "title": title,
                      "detail": h.note, "order_id": h.order_id, "ip": None})
    for m in db.query(StockMovement).options(joinedload(StockMovement.product), joinedload(StockMovement.warehouse)) \
            .filter(StockMovement.created_by_id == user_id).order_by(StockMovement.created_at.desc()).limit(limit).all():
        sign = "+" if m.quantity_change > 0 else "−"
        items.append({"at": m.created_at, "kind": "stock", "category": "stock", "action": f"stock.{m.movement_type}",
                      "title": f"{MOVEMENT_LABELS.get(m.movement_type, m.movement_type)}: {m.product.name if m.product else 'کالا'} "
                               f"({sign}{abs(m.quantity_change)}) — {m.warehouse.name if m.warehouse else ''}".strip(" —"),
                      "detail": m.reason, "order_id": None, "ip": None})
    items.sort(key=lambda x: x["at"] or datetime.min, reverse=True)
    return items[:limit]
