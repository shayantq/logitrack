"""
دفتر گردش کالا (Stock Ledger)

تنها راه مجاز تغییر موجودی، تابع record() است: موجودی را تغییر می‌دهد و
هم‌زمان یک StockMovement با نوع، مقدار، مانده بعد از گردش، دلیل، مرجع و
کاربر ثبت می‌کند. بنابراین همیشه برقرار است:

    Inventory.quantity == مجموع quantity_change گردش‌های همان ردیف

محافظ لایه داده (before_flush پایین همین فایل):
  • اگر کدی quantity یک Inventory را مستقیم و بدون record() عوض کند، flush
    با LedgerViolationError متوقف می‌شود — هیچ تغییر بی‌سندی ذخیره نمی‌شود.
  • ردیف موجودی جدیدی که با quantity غیرصفر ساخته شود، خودکار یک گردش
    «موجودی اولیه» می‌گیرد (مثل افتتاح حساب با مانده اول دوره).
"""
from sqlalchemy import event, func, inspect
from sqlalchemy.orm import Session

from app.models import Inventory, StockMovement, User
from app.services.exceptions import ConflictError

_EXPECTED_QUANTITY = "_ledger_expected_quantity"


class LedgerViolationError(RuntimeError):
    pass


def record(
    db: Session,
    inventory: Inventory,
    change: int,
    movement_type: str,
    *,
    user: User | None = None,
    reason: str | None = None,
    reference_type: str | None = None,
    reference_id: int | None = None,
) -> StockMovement:
    """
    موجودی را change واحد تغییر می‌دهد و گردش آن را ثبت می‌کند.
    ⚠️ فراخواننده باید ردیف موجودی را قبلاً با SELECT ... FOR UPDATE قفل کرده باشد.
    """
    if change == 0:
        raise ValueError("مقدار گردش نمی‌تواند صفر باشد.")
    new_balance = (inventory.quantity or 0) + change
    if new_balance < 0:
        raise ConflictError(
            f"موجودی کافی نیست. موجودی فعلی: {inventory.quantity or 0} عدد — مقدار خروج: {-change} عدد."
        )

    inventory.quantity = new_balance
    setattr(inventory, _EXPECTED_QUANTITY, new_balance)
    if new_balance > (inventory.reorder_point or 0):
        # از این به بعد اگر به حد آستانه برسد، اعلان «رو‌به‌اتمام» می‌گیرد
        inventory.ever_exceeded_reorder = True
        inventory.low_alerted = False
    else:
        # هشدار فوری (همان لحظه خروج کالا) — بررسی ساعتی فقط پشتیبان است
        from app.services import notification_service
        notification_service.low_stock(db, inventory)

    movement = StockMovement(
        inventory=inventory,
        organization_id=inventory.organization_id,
        product_id=inventory.product_id,
        warehouse_id=inventory.warehouse_id,
        movement_type=movement_type,
        quantity_change=change,
        balance_after=new_balance,
        reason=reason,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by_id=user.id if user else None,
    )
    db.add(movement)
    return movement


def set_balance(db: Session, inventory: Inventory, new_quantity: int, movement_type: str = "adjustment", **kwargs):
    """موجودی را به یک عدد مشخص می‌رساند (با ثبت گردشِ اختلاف). اگر تغییری نباشد None برمی‌گرداند."""
    change = new_quantity - (inventory.quantity or 0)
    if change == 0:
        return None
    return record(db, inventory, change, movement_type, **kwargs)


def find_mismatches(db: Session) -> list[dict]:
    """ردیف‌های موجودی‌ای که مانده‌شان با مجموع گردش‌ها نمی‌خواند (باید همیشه خالی باشد)."""
    sums = dict(
        db.query(StockMovement.inventory_id, func.coalesce(func.sum(StockMovement.quantity_change), 0))
        .group_by(StockMovement.inventory_id).all()
    )
    mismatches = []
    for inv in db.query(Inventory).all():
        ledger_total = int(sums.get(inv.id, 0))
        if ledger_total != (inv.quantity or 0):
            mismatches.append({
                "inventory_id": inv.id, "product_id": inv.product_id, "warehouse_id": inv.warehouse_id,
                "quantity": inv.quantity, "ledger_total": ledger_total,
            })
    return mismatches


# ---------------------------------------------------------------------------
# محافظ لایه داده
# ---------------------------------------------------------------------------
@event.listens_for(Session, "before_flush")
def _guard_inventory_changes(session, flush_context, instances):
    for obj in list(session.new):
        if isinstance(obj, Inventory) and (obj.quantity or 0) != 0 and getattr(obj, _EXPECTED_QUANTITY, None) is None:
            opening = obj.quantity
            obj.quantity = 0
            record(session, obj, opening, "initial", reason="موجودی اولیه")

    for obj in session.dirty:
        if not isinstance(obj, Inventory):
            continue
        history = inspect(obj).attrs.quantity.history
        if history.has_changes() and getattr(obj, _EXPECTED_QUANTITY, None) != obj.quantity:
            raise LedgerViolationError(
                f"موجودی ردیف {obj.id} بدون ثبت گردش تغییر کرده است؛ از app.services.stock_ledger.record استفاده کنید."
            )
