"""
تخصیص و رزرو موجودی (Allocation)

رزرو، موجودی فیزیکی را تغییر نمی‌دهد؛ فقط بخشی از موجودی «سالم و آزاد» را برای یک سند (مثلاً سفارش)
کنار می‌گذارد تا سفارش دیگری آن را نفروشد. سه پایان ممکن:
  • consume  — کالا با حواله از انبار خارج شد (گردش order_out زیر یک سند انبار)
  • release  — سند لغو/منقضی شد و موجودی دوباره آزاد است

جلوگیری از رزرو دوباره (Race Condition): هر تابع روی ردیف موجودیِ قفل‌شده (SELECT ... FOR UPDATE،
همیشه به ترتیب id تا deadlock رخ ندهد) کار می‌کند و دیتابیس با CHECK
`reserved_quantity <= quantity` آخرین سد است.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.wms import AVAILABLE
from app.models import Inventory, StockDocument, StockMovement, StockReservation, User
from app.services import stock_ledger
from app.services.exceptions import ConflictError


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def lock_inventories(db: Session, inventory_ids) -> dict[int, Inventory]:
    ids = sorted(set(inventory_ids))
    if not ids:
        return {}
    rows = db.query(Inventory).filter(Inventory.id.in_(ids)).order_by(Inventory.id).with_for_update().all()
    return {inv.id: inv for inv in rows}


def reserve(db: Session, inventory: Inventory, quantity: int, *, reference_type: str, reference_id: int,
            user: User | None = None) -> StockReservation:
    """⚠️ ردیف موجودی باید قفل شده باشد."""
    if quantity <= 0:
        raise ValueError("مقدار رزرو باید مثبت باشد.")
    if (inventory.stock_status or AVAILABLE) != AVAILABLE:
        raise ConflictError("فقط موجودی «سالم و آزاد» قابل رزرو است.")
    if inventory.free_quantity < quantity:
        raise ConflictError(
            f"موجودی آزاد کافی نیست. موجودی آزاد: {inventory.free_quantity} عدد — درخواستی: {quantity} عدد."
        )
    stock_ledger.set_reserved(inventory, (inventory.reserved_quantity or 0) + quantity)
    reservation = StockReservation(
        organization_id=inventory.organization_id, inventory=inventory, product_id=inventory.product_id,
        warehouse_id=inventory.warehouse_id, quantity=quantity, status="active",
        reference_type=reference_type, reference_id=reference_id, created_at=_now(),
        created_by_id=user.id if user else None,
    )
    db.add(reservation)
    return reservation


def active_for(db: Session, reference_type: str, reference_id: int) -> list[StockReservation]:
    """رزروهای فعال یک سند — ردیف‌های موجودی‌شان به ترتیب id قفل می‌شوند."""
    reservations = db.query(StockReservation).filter(
        StockReservation.reference_type == reference_type, StockReservation.reference_id == reference_id,
        StockReservation.status == "active",
    ).order_by(StockReservation.id).with_for_update().all()
    lock_inventories(db, [r.inventory_id for r in reservations])
    return reservations


def _close(reservation: StockReservation, status: str, user: User | None, reason: str | None) -> Inventory:
    if reservation.status != "active":
        raise ConflictError("این رزرو قبلاً بسته شده است.")
    inventory = reservation.inventory
    stock_ledger.set_reserved(inventory, (inventory.reserved_quantity or 0) - reservation.quantity)
    reservation.status = status
    reservation.closed_at = _now()
    reservation.closed_by_id = user.id if user else None
    reservation.close_reason = (reason or "")[:200] or None
    return inventory


def release(db: Session, reservation: StockReservation, *, user: User | None = None, reason: str | None = None) -> None:
    _close(reservation, "released", user, reason)


def consume(db: Session, reservation: StockReservation, document: StockDocument, *, user: User | None = None,
            reason: str | None = None, movement_type: str = "order_out") -> StockMovement:
    """رزرو را مصرف و همان مقدار را با گردش خروج زیر سند document از موجودی کم می‌کند."""
    inventory = _close(reservation, "consumed", user, reason)
    movement = stock_ledger.record(
        db, inventory, -reservation.quantity, movement_type, document=document, user=user, reason=reason,
        reference_type=reservation.reference_type, reference_id=reservation.reference_id,
    )
    reservation.movement = movement
    return movement
