"""
تخصیص و رزرو موجودی (Allocation)

رزرو، موجودی فیزیکی را تغییر نمی‌دهد؛ فقط بخشی از موجودی «قابل تخصیص» را برای یک سند (مثلاً سفارش)
کنار می‌گذارد تا سفارش دیگری آن را نفروشد. سه پایان ممکن:
  • consume  — کالا با حواله از انبار خارج شد (گردش order_out زیر یک سند انبار)
  • release  — سند لغو/منقضی شد و موجودی دوباره آزاد است

قابل تخصیص (allocatable) = موجودی تأییدشده‌ای که
  • در محل نگهداری/برداشت فعال و غیرمسدود است (یا انبار محل‌بندی ندارد)،
  • منقضی نشده و
  • مال خود سازمان است (کالای امانی مالک دیگر به سفارش‌های سازمان تخصیص نمی‌یابد).
موجودی قابل وعده (ATP) = قابل تخصیص − رزرو. هر عملیاتی که قابل تخصیص را کمتر از رزرو کند رد می‌شود (ensure_covered).

جلوگیری از رزرو دوباره (Race Condition): هر تابع روی ردیف موجودیِ قفل‌شده (SELECT ... FOR UPDATE،
همیشه به ترتیب id تا deadlock رخ ندهد) کار می‌کند و دیتابیس با CHECK
`reserved_quantity <= quantity` آخرین سد است.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.wms import ALLOCATABLE_LOCATION_TYPES, AVAILABLE
from app.models import Inventory, Location, StockBalance, StockDocument, StockMovement, StockReservation, User
from app.services import stock_ledger
from app.services.exceptions import ConflictError


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def unallocatable_map(db: Session, inventory_ids=None) -> dict[int, int]:
    """مقدار تأییدشده‌ای از هر ردیف موجودی که قابل تخصیص نیست (محل نامناسب، منقضی، کالای امانی)."""
    from app.services import catalog_service
    today = catalog_service.today_local()
    query = db.query(StockBalance.inventory_id, func.sum(StockBalance.quantity)).outerjoin(
        Location, StockBalance.location_id == Location.id,
    ).filter(
        StockBalance.stock_status == AVAILABLE, StockBalance.quantity > 0,
        or_(
            StockBalance.owner_id.is_not(None),
            StockBalance.expiry_date < today,
            and_(StockBalance.location_id.is_not(None), or_(
                Location.location_type.not_in(ALLOCATABLE_LOCATION_TYPES), Location.is_active.is_(False),
                Location.is_blocked.is_(True),
            )),
        ),
    )
    if inventory_ids is not None:
        query = query.filter(StockBalance.inventory_id.in_(list(inventory_ids) or [-1]))
    result = {inventory_id: int(total or 0) for inventory_id, total in query.group_by(StockBalance.inventory_id).all()}
    # کالای برداشت‌شده‌ای که در محل آماده‌سازی منتظر حواله است همچنان پوشش رزرو همان سفارش است
    for inventory_id, staged in staged_map(db, result.keys()).items():
        result[inventory_id] = max(result[inventory_id] - staged, 0)
    return result


def staged_map(db: Session, inventory_ids) -> dict[int, int]:
    """مقدار برداشت‌شده و منتقل‌شده به محل آماده‌سازی (هنوز بدون حواله) به تفکیک ردیف موجودی تأییدشده."""
    ids = list(inventory_ids)
    if not ids:
        return {}
    from app.models import PickLine
    rows = db.query(Inventory.id, func.sum(PickLine.picked_quantity)).join(
        PickLine, (PickLine.product_id == Inventory.product_id) & (PickLine.warehouse_id == Inventory.warehouse_id),
    ).filter(
        Inventory.id.in_(ids), Inventory.stock_status == AVAILABLE, PickLine.staged_location_id.is_not(None),
        PickLine.issued.is_(False), PickLine.picked_quantity > 0,
    ).group_by(Inventory.id).all()
    return {inventory_id: int(total or 0) for inventory_id, total in rows}


def allocatable(db: Session, inventory: Inventory) -> int:
    if (inventory.stock_status or AVAILABLE) != AVAILABLE:
        return 0
    db.flush()
    return (inventory.quantity or 0) - unallocatable_map(db, [inventory.id]).get(inventory.id, 0)


def available_to_promise(db: Session, inventory: Inventory) -> int:
    return max(allocatable(db, inventory) - (inventory.reserved_quantity or 0), 0)


def ensure_covered(db: Session, inventory: Inventory) -> None:
    """رزرو سفارش‌های باز باید همیشه با موجودی قابل تخصیص پوشش داشته باشد."""
    reserved = inventory.reserved_quantity or 0
    if not reserved:
        return
    covered = allocatable(db, inventory)
    if covered < reserved:
        raise ConflictError(
            f"{reserved} عدد از این کالا برای سفارش‌های باز رزرو است و بعد از این عملیات فقط {covered} عدد "
            "قابل تخصیص (در محل نگهداری/برداشت و تأییدشده) می‌ماند. ابتدا سفارش‌ها را ارسال یا لغو کنید."
        )


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
        raise ConflictError("فقط موجودی تأییدشده (سالم) قابل رزرو است.")
    free = available_to_promise(db, inventory)
    if free < quantity:
        raise ConflictError(
            f"موجودی آزاد کافی نیست. موجودی آزاد: {free} عدد — درخواستی: {quantity} عدد."
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


def transfer(db: Session, reservation: StockReservation, *, reference_type: str, reference_id: int,
             user: User | None = None, reason: str | None = None) -> StockReservation:
    """
    رزرو را به سند دیگری می‌سپارد (مثلاً رزرو سفارش معوق ← سفارش تکمیلی): رزرو قبلی آزاد و همان مقدار در همان
    تراکنش و روی همان ردیف قفل‌شده برای مرجع جدید رزرو می‌شود — بین این دو، سفارش دیگری نمی‌تواند آن را بردارد.
    """
    inventory = _close(reservation, "released", user, reason)
    stock_ledger.set_reserved(inventory, (inventory.reserved_quantity or 0) + reservation.quantity)
    moved = StockReservation(
        organization_id=inventory.organization_id, inventory=inventory, product_id=inventory.product_id,
        warehouse_id=inventory.warehouse_id, quantity=reservation.quantity, status="active",
        reference_type=reference_type, reference_id=reference_id, created_at=_now(),
        created_by_id=user.id if user else None,
    )
    db.add(moved)
    return moved


def consume(db: Session, reservation: StockReservation, document: StockDocument, *, user: User | None = None,
            reason: str | None = None, movement_type: str = "order_out", lines=None) -> StockMovement:
    """
    رزرو را مصرف و همان مقدار را با گردش خروج زیر سند document کم می‌کند: از همان محل/بچ‌هایی که برداشت
    (پیکینگ) شده‌اند (lines)، یا اگر سفارش پیکینگ نداشت با برداشت خودکار FEFO از موجودی قابل تخصیص.
    """
    inventory = _close(reservation, "consumed", user, reason)
    movement = stock_ledger.record(
        db, inventory, -reservation.quantity, movement_type, document=document, user=user, reason=reason,
        reference_type=reservation.reference_type, reference_id=reservation.reference_id,
        pick=stock_ledger.ALLOCATABLE_FIRST, lines=lines,
    )
    reservation.movement = movement
    return movement
