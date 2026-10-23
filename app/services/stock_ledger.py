"""
دفتر گردش کالا (Stock Ledger) و اسناد انبار

قاعده‌های غیرقابل‌مذاکره (app/core/wms.py):
  ۱. موجودی هرگز با ویرایش مستقیم عدد عوض نمی‌شود؛ تنها راه record() است که همراه با یک
     سند انبار (StockDocument) یک گردش (StockMovement) ثبت می‌کند. بنابراین همیشه برقرار است:
         Inventory.quantity == مجموع quantity_change گردش‌های همان ردیف
  ۲. سند قطعی و گردش‌هایش ویرایش یا حذف نمی‌شوند؛ اصلاح فقط با سند برگشت (reverse_document).
  ۳. خروج کالا هرگز موجودی رزروشده را مصرف نمی‌کند (موجودی آزاد = موجود − رزرو)، مگر از مسیر
     مصرف همان رزرو (app/services/allocation_service.py).

محافظ لایه داده (before_flush پایین همین فایل) هر کدی را که این قاعده‌ها را دور بزند متوقف می‌کند:
  • تغییر quantity یا reserved_quantity بدون مسیر مجاز ← LedgerViolationError
  • ویرایش/حذف گردش، رویداد یا سند قطعی ← LedgerViolationError
  • تغییر SKU یا هویت ردیف موجودی (کالا/انبار/وضعیت) ← LedgerViolationError
  • ردیف موجودی جدیدی که با quantity غیرصفر ساخته شود، خودکار سند «موجودی اول دوره» می‌گیرد.
در PostgreSQL تریگرهای مایگریشن ۰۰۲۴ همین را برای SQL مستقیم هم تضمین می‌کنند.
"""
from __future__ import annotations

import secrets
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import event, func, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.tenancy import SKIP_TENANT_FILTER
from app.core.wms import AVAILABLE, DOCUMENT_TYPES, MOVEMENT_DOCUMENT_TYPE
from app.models import DomainEvent, Inventory, Product, StockDocument, StockMovement, StockReservation, User
from app.services.exceptions import ConflictError

_EXPECTED_QUANTITY = "_ledger_expected_quantity"
_EXPECTED_RESERVED = "_ledger_expected_reserved"
MAINTENANCE_KEY = "ledger_maintenance"
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class LedgerViolationError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@contextmanager
def maintenance(db: Session):
    """
    فقط برای اسکریپت‌های نگهداری و داده نمونه (مثلاً ساخت سابقه فروش با تاریخ گذشته): محافظ‌های
    تغییرناپذیری را تا پایان همین تراکنش خاموش می‌کند. هرگز در مسیر درخواست کاربر استفاده نشود.
    """
    db.info[MAINTENANCE_KEY] = True
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT set_config('pasineh.ledger_maintenance', 'on', true)"))
    try:
        yield
    finally:
        db.info.pop(MAINTENANCE_KEY, None)


# ---------------------------------------------------------------------------
# سند انبار
# ---------------------------------------------------------------------------
def _new_code(db: Session, prefix: str) -> str:
    while True:
        code = f"{prefix}-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        # یکتا در کل پلتفرم (نه فقط سازمان جاری)
        if not db.query(StockDocument.id).filter(StockDocument.code == code).execution_options(**SKIP_TENANT_FILTER).first():
            return code


def new_document(db: Session, doc_type: str, *, organization_id: int, user: User | None = None,
                 warehouse_id: int | None = None, partner_id: int | None = None, reference_type: str | None = None,
                 reference_id: int | None = None, external_ref: str | None = None, note: str | None = None,
                 idempotency_key: str | None = None, request_hash: str | None = None,
                 reversal_of: StockDocument | None = None) -> StockDocument:
    """یک سند قطعی تازه؛ گردش‌ها با record(..., document=سند) به آن اضافه می‌شوند (همه در یک تراکنش)."""
    kind = DOCUMENT_TYPES[doc_type]
    now = _now()
    document = StockDocument(
        organization_id=organization_id, code=_new_code(db, kind.prefix), doc_type=doc_type, status="posted",
        warehouse_id=warehouse_id, partner_id=partner_id, reference_type=reference_type, reference_id=reference_id,
        external_ref=external_ref, note=note, idempotency_key=idempotency_key, request_hash=request_hash,
        reversal_of=reversal_of, created_at=now, created_by_id=user.id if user else None,
        posted_at=now, posted_by_id=user.id if user else None,
    )
    db.add(document)
    return document


def record(
    db: Session,
    inventory: Inventory,
    change: int,
    movement_type: str,
    *,
    document: StockDocument | None = None,
    user: User | None = None,
    reason: str | None = None,
    reference_type: str | None = None,
    reference_id: int | None = None,
    reversal_of: StockMovement | None = None,
) -> StockMovement:
    """
    موجودی را change واحد تغییر می‌دهد و گردش آن را زیر سند document ثبت می‌کند. اگر سندی داده نشود،
    یک سند تک‌گردشی از نوع متناظر (MOVEMENT_DOCUMENT_TYPE) ساخته می‌شود.
    ⚠️ فراخواننده باید ردیف موجودی را قبلاً با SELECT ... FOR UPDATE قفل کرده باشد.
    """
    if change == 0:
        raise ValueError("مقدار گردش نمی‌تواند صفر باشد.")
    current = inventory.quantity or 0
    reserved = inventory.reserved_quantity or 0
    new_balance = current + change
    if new_balance < 0:
        raise ConflictError(f"موجودی کافی نیست. موجودی فعلی: {current} عدد — مقدار خروج: {-change} عدد.")
    if new_balance < reserved:
        raise ConflictError(
            f"موجودی آزاد کافی نیست. موجودی: {current} عدد، رزرو سفارش‌های باز: {reserved} عدد — "
            f"مقدار خروج: {-change} عدد. ابتدا سفارش‌ها را ارسال یا لغو کنید."
        )

    if document is None:
        document = new_document(
            db, MOVEMENT_DOCUMENT_TYPE.get(movement_type, "adjustment"), organization_id=inventory.organization_id,
            user=user, warehouse_id=inventory.warehouse_id, reference_type=reference_type, reference_id=reference_id,
            note=reason,
        )

    inventory.quantity = new_balance
    setattr(inventory, _EXPECTED_QUANTITY, new_balance)
    if inventory.stock_status in (None, AVAILABLE):
        if new_balance > (inventory.reorder_point or 0):
            # از این به بعد اگر به حد آستانه برسد، اعلان «رو‌به‌اتمام» می‌گیرد
            inventory.ever_exceeded_reorder = True
            inventory.low_alerted = False
        else:
            # هشدار فوری (همان لحظه خروج کالا) — بررسی ساعتی فقط پشتیبان است
            from app.services import notification_service
            notification_service.low_stock(db, inventory)

    movement = StockMovement(
        document=document,
        inventory=inventory,
        organization_id=inventory.organization_id,
        product_id=inventory.product_id,
        warehouse_id=inventory.warehouse_id,
        stock_status=inventory.stock_status or AVAILABLE,
        movement_type=movement_type,
        quantity_change=change,
        balance_after=new_balance,
        reason=reason,
        reference_type=reference_type if reference_type is not None else document.reference_type,
        reference_id=reference_id if reference_id is not None else document.reference_id,
        reversal_of_id=reversal_of.id if reversal_of is not None else None,
        created_by_id=user.id if user else None,
    )
    db.add(movement)
    return movement


def lock_bucket(db: Session, product_id: int, warehouse_id: int, stock_status: str = AVAILABLE, *,
                create: bool = True, reorder_point: int | None = None, organization_id: int | None = None) -> Inventory | None:
    """
    ردیف موجودی (کالا × انبار × وضعیت) را با قفل برمی‌گرداند و اگر نیست (و create) با موجودی صفر می‌سازد.
    ساخت هم‌زمان یک ردیف در دو درخواست با قید یکتای uq_inventories_bucket و SAVEPOINT بی‌خطر است.
    """
    def find():
        return db.query(Inventory).filter(
            Inventory.product_id == product_id, Inventory.warehouse_id == warehouse_id, Inventory.stock_status == stock_status,
        ).with_for_update().first()

    inventory = find()
    if inventory is not None or not create:
        return inventory
    try:
        with db.begin_nested():
            inventory = Inventory(product_id=product_id, warehouse_id=warehouse_id, stock_status=stock_status, quantity=0,
                                  reorder_point=10 if reorder_point is None else reorder_point)
            if organization_id is not None:
                inventory.organization_id = organization_id
            db.add(inventory)
            db.flush()
    except IntegrityError:
        inventory = find()
        if inventory is None:
            raise
    return inventory


def set_balance(db: Session, inventory: Inventory, new_quantity: int, movement_type: str = "adjustment", **kwargs):
    """موجودی را به یک عدد مشخص می‌رساند (با ثبت گردشِ اختلاف). اگر تغییری نباشد None برمی‌گرداند."""
    change = new_quantity - (inventory.quantity or 0)
    if change == 0:
        return None
    return record(db, inventory, change, movement_type, **kwargs)


def set_reserved(inventory: Inventory, value: int) -> None:
    """فقط allocation_service: مقدار رزرو ردیف را عوض می‌کند (محافظ پایین تغییر بی‌مسیر را رد می‌کند)."""
    inventory.reserved_quantity = value
    setattr(inventory, _EXPECTED_RESERVED, value)


def find_mismatches(db: Session) -> list[dict]:
    """
    ردیف‌هایی که مانده‌شان با مجموع گردش‌ها، یا رزروشان با مجموع رزروهای فعال نمی‌خواند (باید همیشه خالی باشد).
    """
    sums = dict(
        db.query(StockMovement.inventory_id, func.coalesce(func.sum(StockMovement.quantity_change), 0))
        .group_by(StockMovement.inventory_id).all()
    )
    reserved = dict(
        db.query(StockReservation.inventory_id, func.coalesce(func.sum(StockReservation.quantity), 0))
        .filter(StockReservation.status == "active").group_by(StockReservation.inventory_id).all()
    )
    mismatches = []
    for inv in db.query(Inventory).all():
        ledger_total = int(sums.get(inv.id, 0))
        reserved_total = int(reserved.get(inv.id, 0))
        if ledger_total != (inv.quantity or 0) or reserved_total != (inv.reserved_quantity or 0):
            mismatches.append({
                "inventory_id": inv.id, "product_id": inv.product_id, "warehouse_id": inv.warehouse_id,
                "stock_status": inv.stock_status, "quantity": inv.quantity, "ledger_total": ledger_total,
                "reserved_quantity": inv.reserved_quantity, "reserved_total": reserved_total,
            })
    return mismatches


# ---------------------------------------------------------------------------
# محافظ لایه داده
# ---------------------------------------------------------------------------
def _changed(obj, *names: str) -> list[str]:
    attrs = inspect(obj).attrs
    return [n for n in names if attrs[n].history.has_changes()]


def _changed_columns(obj, allowed: set[str] = frozenset()) -> list[str]:
    state = inspect(obj)
    return [c.key for c in state.mapper.column_attrs if c.key not in allowed and state.attrs[c.key].history.has_changes()]


@event.listens_for(Session, "before_flush")
def _guard_inventory_changes(session, flush_context, instances):
    if session.info.get(MAINTENANCE_KEY):
        return
    for obj in list(session.new):
        if isinstance(obj, Inventory):
            if (obj.reserved_quantity or 0) != 0 and getattr(obj, _EXPECTED_RESERVED, None) is None:
                raise LedgerViolationError("ردیف موجودی جدید نمی‌تواند از ابتدا رزرو داشته باشد.")
            if (obj.quantity or 0) != 0 and getattr(obj, _EXPECTED_QUANTITY, None) is None:
                opening = obj.quantity
                obj.quantity = 0
                record(session, obj, opening, "initial", reason="موجودی اولیه")

    for obj in session.dirty:
        if isinstance(obj, Inventory):
            if _changed(obj, "quantity") and getattr(obj, _EXPECTED_QUANTITY, None) != obj.quantity:
                raise LedgerViolationError(
                    f"موجودی ردیف {obj.id} بدون ثبت سند و گردش تغییر کرده است؛ از app.services.stock_ledger.record استفاده کنید."
                )
            if _changed(obj, "reserved_quantity") and getattr(obj, _EXPECTED_RESERVED, None) != obj.reserved_quantity:
                raise LedgerViolationError(f"رزرو ردیف {obj.id} فقط از app.services.allocation_service تغییر می‌کند.")
            if _changed(obj, "product_id", "warehouse_id", "stock_status", "organization_id"):
                raise LedgerViolationError("کالا، انبار و وضعیت کیفی یک ردیف موجودی تغییرناپذیر است؛ از سند انتقال یا تغییر وضعیت استفاده کنید.")
        elif isinstance(obj, (StockMovement, DomainEvent)):
            if _changed_columns(obj):
                raise LedgerViolationError(f"{type(obj).__name__} غیرقابل‌ویرایش است؛ برای اصلاح سند برگشت ثبت کنید.")
        elif isinstance(obj, StockDocument):
            history = inspect(obj).attrs.status.history
            before = history.deleted[0] if history.deleted else obj.status
            if before == "draft":
                continue
            if _changed_columns(obj, {"status"}) or (history.has_changes() and not (before == "posted" and obj.status == "reversed")):
                raise LedgerViolationError("سند قطعی انبار غیرقابل‌ویرایش است؛ فقط با سند برگشت خنثی می‌شود.")
        elif isinstance(obj, StockReservation):
            history = inspect(obj).attrs.status.history
            before = history.deleted[0] if history.deleted else obj.status
            if _changed(obj, "quantity", "inventory_id", "product_id", "warehouse_id", "reference_type", "reference_id") \
                    or (history.has_changes() and before != "active"):
                raise LedgerViolationError("رزرو بسته‌شده یا مقدار رزرو قابل تغییر نیست.")
        elif isinstance(obj, Product):
            if _changed(obj, "sku"):
                raise LedgerViolationError("کد کالا (SKU) پس از ثبت تغییرناپذیر است.")

    for obj in session.deleted:
        if isinstance(obj, (StockMovement, DomainEvent)):
            raise LedgerViolationError(f"{type(obj).__name__} قابل حذف نیست.")
        if isinstance(obj, StockDocument) and obj.status not in ("draft", "canceled"):
            raise LedgerViolationError("سند قطعی انبار قابل حذف نیست؛ برای اصلاح سند برگشت ثبت کنید.")
        if isinstance(obj, Inventory) and ((obj.quantity or 0) != 0 or (obj.reserved_quantity or 0) != 0):
            raise LedgerViolationError(f"ردیف موجودی {obj.id} مانده یا رزرو دارد و قابل حذف نیست.")
        if isinstance(obj, StockReservation):
            raise LedgerViolationError("سابقه رزرو قابل حذف نیست.")
