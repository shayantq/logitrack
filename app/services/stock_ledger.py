"""
دفتر گردش کالا (Stock Ledger) و اسناد انبار

قاعده‌های غیرقابل‌مذاکره (app/core/wms.py):
  ۱. موجودی هرگز با ویرایش مستقیم عدد عوض نمی‌شود؛ تنها راه record() است که همراه با یک
     سند انبار (StockDocument) یک گردش (StockMovement) و ردیف‌های ریز آن (StockMovementLine: محل، بچ،
     سریال، مالک، انقضا) ثبت می‌کند. بنابراین همیشه برقرار است:
         Inventory.quantity == مجموع گردش‌های همان ردیف == مجموع StockBalance‌های همان ردیف
         StockBalance.quantity == مجموع ردیف‌های ریز گردش همان مانده
  ۲. سند قطعی و گردش‌هایش ویرایش یا حذف نمی‌شوند؛ اصلاح فقط با سند برگشت (reverse_document).
  ۳. خروج کالا هرگز موجودی رزروشده را مصرف نمی‌کند (موجودی آزاد = موجود − رزرو)، مگر از مسیر
     مصرف همان رزرو (app/services/allocation_service.py).
  ۴. ورود به هر محل از ظرفیت و قاعده اختلاط آن محل می‌گذرد (location_service.ensure_fits)؛ هر شماره سریال
     حداکثر یک‌جا در موجودی است و هر بچ فقط یک تاریخ انقضا دارد.

خروجی بدون محل/بچ مشخص (مثلاً حواله سفارش یا اصلاحیه) خودکار از ردیف‌های ریز برداشته می‌شود
(pick_lines): اول‌منقضی، اول‌خروج (FEFO) و سپس قدیمی‌ترین ردیف. حواله سفارش اول از موجودی قابل تخصیص
برمی‌دارد؛ بقیه خروجی‌ها اول از موجودی غیرقابل تخصیص (منقضی، محل تخلیه، ...) تا رزرو سفارش‌ها بی‌پوشش نماند.

محافظ لایه داده (before_flush پایین همین فایل) هر کدی را که این قاعده‌ها را دور بزند متوقف می‌کند:
  • تغییر quantity یا reserved_quantity بدون مسیر مجاز ← LedgerViolationError
  • ویرایش/حذف گردش، ردیف ریز گردش، رویداد یا سند قطعی ← LedgerViolationError
  • تغییر SKU یا هویت ردیف موجودی (کالا/انبار/وضعیت/محل/بچ) ← LedgerViolationError
  • ردیف موجودی جدیدی که با quantity غیرصفر ساخته شود، خودکار سند «موجودی اول دوره» می‌گیرد.
در PostgreSQL تریگرهای مایگریشن‌های ۰۰۲۴ و ۰۰۲۵ همین را برای SQL مستقیم هم تضمین می‌کنند.
"""
from __future__ import annotations

import secrets
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone

from sqlalchemy import event, func, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.tenancy import SKIP_TENANT_FILTER
from app.core.wms import AVAILABLE, DOCUMENT_TYPES, MOVEMENT_DOCUMENT_TYPE
from app.models import (
    DomainEvent, Inventory, Location, Product, StockBalance, StockDocument, StockMovement, StockMovementLine,
    StockReservation, User,
)
from app.services.exceptions import ConflictError

_EXPECTED_QUANTITY = "_ledger_expected_quantity"
_EXPECTED_RESERVED = "_ledger_expected_reserved"
MAINTENANCE_KEY = "ledger_maintenance"
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
# گردش‌های جابه‌جایی داخلی: اعلان نقطه سفارش نمی‌دهند و پوشش رزرو را تابع move() در پایان بررسی می‌کند
_MOVE_TYPES = ("move_out", "move_in")

# سیاست برداشت خودکار
ALLOCATABLE_FIRST = "allocatable_first"     # حواله سفارش: از موجودی قابل تخصیص
PROTECT_ALLOCATABLE = "protect_allocatable"  # بقیه: اول منقضی/محل‌های غیرقابل تخصیص، تا رزروها پوشش بمانند


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
# ابعاد ردیف ریز
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StockKey:
    """ابعاد ردیف ریز موجودی داخل یک ردیف Inventory (همه خالی = بدون محل، بدون بچ، مال خود سازمان)."""
    location_id: int | None = None
    owner_id: int | None = None
    lot_number: str | None = None
    serial_number: str | None = None
    expiry_date: date | None = None

    def with_(self, **changes) -> StockKey:
        return replace(self, **changes)


KEY_FIELDS = ("location_id", "owner_id", "lot_number", "serial_number", "expiry_date")
Line = tuple[StockKey, int]      # (ابعاد، مقدار مثبت)


def key_of(row) -> StockKey:
    return StockKey(**{f: getattr(row, f) for f in KEY_FIELDS})


def mirror(movement: StockMovement, **overrides) -> list[Line]:
    """ردیف‌های ریز یک گردش با مقدار مثبت — برای ورود همان کالا (همان بچ/سریال/مالک) به جای دیگر."""
    return [(key_of(line).with_(**overrides), abs(line.quantity_change)) for line in movement.lines]


def describe(key: StockKey, location: Location | None = None) -> str:
    parts = []
    if key.location_id is not None:
        parts.append(f"محل {location.code if location else key.location_id}")
    if key.lot_number:
        parts.append(f"بچ {key.lot_number}")
    if key.serial_number:
        parts.append(f"سریال {key.serial_number}")
    return "، ".join(parts) or "بدون محل"


# ---------------------------------------------------------------------------
# سند انبار
# ---------------------------------------------------------------------------
def new_code(db: Session, model, prefix: str) -> str:
    """کد تصادفی یکتا در کل پلتفرم (نه فقط سازمان جاری) — برای اسناد، رسیدها، بازرسی‌ها و وظایف."""
    while True:
        code = f"{prefix}-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
        if not db.query(model.id).filter(model.code == code).execution_options(**SKIP_TENANT_FILTER).first():
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
        organization_id=organization_id, code=new_code(db, StockDocument, kind.prefix), doc_type=doc_type,
        status="posted", warehouse_id=warehouse_id, partner_id=partner_id, reference_type=reference_type,
        reference_id=reference_id, external_ref=external_ref, note=note, idempotency_key=idempotency_key,
        request_hash=request_hash, reversal_of=reversal_of, created_at=now, created_by_id=user.id if user else None,
        posted_at=now, posted_by_id=user.id if user else None,
    )
    db.add(document)
    return document


# ---------------------------------------------------------------------------
# ردیف‌های ریز
# ---------------------------------------------------------------------------
def _is_new(obj) -> bool:
    return not inspect(obj).persistent


def _balance_query(db: Session, inventory_id: int, key: StockKey):
    query = db.query(StockBalance).filter(StockBalance.inventory_id == inventory_id)
    for name in KEY_FIELDS:
        value, column = getattr(key, name), getattr(StockBalance, name)
        query = query.filter(column.is_(None) if value is None else column == value)
    return query


def lock_balance(db: Session, inventory: Inventory, key: StockKey, *, create: bool) -> StockBalance | None:
    """ردیف ریز با قفل؛ اگر نیست (و create) با موجودی صفر ساخته می‌شود — ساخت هم‌زمان با قید یکتا و SAVEPOINT."""
    def new_row():
        return StockBalance(organization_id=inventory.organization_id, inventory=inventory, product_id=inventory.product_id,
                            warehouse_id=inventory.warehouse_id, stock_status=inventory.stock_status or AVAILABLE,
                            quantity=0, **asdict(key))

    if _is_new(inventory):
        # ردیف موجودی تازه (مثلاً موجودی اول دوره در همان flush): هنوز ردیف ریزی ندارد
        found = next((b for b in inventory.balances if key_of(b) == key), None)
        if found is None and create:
            found = new_row()
            db.add(found)
        return found

    found = _balance_query(db, inventory.id, key).with_for_update().first()
    if found is not None or not create:
        return found
    try:
        with db.begin_nested():
            found = new_row()
            db.add(found)
            db.flush()
    except IntegrityError:
        found = _balance_query(db, inventory.id, key).with_for_update().first()
        if found is None:
            raise
    return found


def _ensure_serial(db: Session, inventory: Inventory, key: StockKey, quantity: int) -> None:
    if quantity != 1:
        raise ConflictError(f"هر شماره سریال یک واحد است (سریال {key.serial_number}).")
    db.flush()
    taken = db.query(StockBalance).filter(
        StockBalance.product_id == inventory.product_id, StockBalance.serial_number == key.serial_number,
        StockBalance.quantity > 0,
    ).first()
    if taken is not None:
        raise ConflictError(f"شماره سریال {key.serial_number} همین الان در موجودی است (انبار {taken.warehouse_id}).")


def _ensure_lot_expiry(db: Session, inventory: Inventory, key: StockKey) -> None:
    other = db.query(StockBalance.expiry_date).filter(
        StockBalance.product_id == inventory.product_id, StockBalance.lot_number == key.lot_number,
        StockBalance.expiry_date.is_not(None),
    ).first()
    if other is not None and other[0] != key.expiry_date:
        raise ConflictError(f"بچ {key.lot_number} قبلاً با تاریخ انقضای {other[0]} ثبت شده است؛ هر بچ فقط یک تاریخ انقضا دارد.")


def _check_incoming(db: Session, inventory: Inventory, key: StockKey, quantity: int) -> None:
    if key.location_id is not None:
        from app.services import location_service
        location_service.ensure_fits(db, inventory, key.location_id, quantity, lot_number=key.lot_number, owner_id=key.owner_id)
    if key.serial_number:
        _ensure_serial(db, inventory, key, quantity)
    if key.lot_number:
        _ensure_lot_expiry(db, inventory, key)


def pick_lines(db: Session, inventory: Inventory, quantity: int, *, match: dict | None = None,
               policy: str = PROTECT_ALLOCATABLE) -> list[Line]:
    """
    برداشت خودکار quantity واحد از ردیف‌های ریز inventory (محدود به match، مثلاً {"location_id": 5} یا
    {"lot_number": "B1"}؛ مقدار None یعنی «خالی»). ترتیب: FEFO، بعد قدیمی‌ترین ردیف؛ سیاست، اولویت قابل‌تخصیص را تعیین می‌کند.
    """
    from app.services import catalog_service, location_service
    if _is_new(inventory):
        candidates = [b for b in inventory.balances if (b.quantity or 0) > 0]
    else:
        db.flush()
        query = db.query(StockBalance).filter(StockBalance.inventory_id == inventory.id, StockBalance.quantity > 0)
        for name, value in (match or {}).items():
            column = getattr(StockBalance, name)
            query = query.filter(column.is_(None) if value is None else column == value)
        candidates = query.with_for_update().all()
    today = catalog_service.today_local()
    locations = {loc.id: loc for loc in db.query(Location).filter(
        Location.id.in_({b.location_id for b in candidates if b.location_id} or {-1})).all()}

    def allocatable(b: StockBalance) -> bool:
        return (b.stock_status == AVAILABLE and b.owner_id is None and (b.expiry_date is None or b.expiry_date >= today)
                and location_service.is_allocatable(locations.get(b.location_id)))

    def order(b: StockBalance):
        first = (0 if allocatable(b) else 1) if policy == ALLOCATABLE_FIRST else (1 if allocatable(b) else 0)
        return (first, b.expiry_date or date.max, b.id or 0)

    lines: list[Line] = []
    remaining = quantity
    for balance in sorted(candidates, key=order):
        if remaining <= 0:
            break
        take = min(balance.quantity, remaining)
        lines.append((key_of(balance), take))
        remaining -= take
    if remaining > 0:
        location_id = (match or {}).get("location_id")
        scope = describe(StockKey(**(match or {})), db.get(Location, location_id) if location_id else None)
        raise ConflictError(f"موجودی کافی نیست ({scope}): موجود {quantity - remaining} عدد — درخواستی {quantity} عدد.")
    return lines


def _ensure_not_counting(db: Session, location_ids: set[int]) -> None:
    """محل قفل‌شده برای انبارگردانی (فصل ۱۶) تا تأیید یا لغو همان انبارگردانی گردشی نمی‌پذیرد."""
    if not location_ids:
        return
    locked = db.query(Location.code).filter(Location.id.in_(location_ids), Location.count_lock_id.is_not(None)).first()
    if locked is not None:
        raise ConflictError(f"محل {locked[0]} در حال انبارگردانی و قفل است؛ تا پایان شمارش، کالا از این محل یا به آن جابه‌جا نمی‌شود.")


# ---------------------------------------------------------------------------
# ثبت گردش
# ---------------------------------------------------------------------------
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
    lines: list[Line] | None = None,
    match: dict | None = None,
    pick: str = PROTECT_ALLOCATABLE,
) -> StockMovement:
    """
    موجودی را change واحد تغییر می‌دهد و گردش آن را زیر سند document ثبت می‌کند. اگر سندی داده نشود،
    یک سند تک‌گردشی از نوع متناظر (MOVEMENT_DOCUMENT_TYPE) ساخته می‌شود.
    ابعاد: lines صریح [(StockKey, مقدار مثبت)]؛ وگرنه ورود با ابعاد match (پیش‌فرض: بدون محل و بچ) و
    خروج با برداشت خودکار از محدوده match.
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

    quantity = abs(change)
    if lines is None:
        lines = [(StockKey(**(match or {})), quantity)] if change > 0 else pick_lines(db, inventory, quantity, match=match, policy=pick)
    lines = [(key, qty) for key, qty in lines if qty]
    if any(qty < 0 for _, qty in lines) or sum(qty for _, qty in lines) != quantity:
        raise ValueError("مجموع ردیف‌های ریز گردش با مقدار گردش برابر نیست.")
    if movement_type != "stocktake":
        _ensure_not_counting(db, {key.location_id for key, _ in lines if key.location_id})

    if document is None:
        document = new_document(
            db, MOVEMENT_DOCUMENT_TYPE.get(movement_type, "adjustment"), organization_id=inventory.organization_id,
            user=user, warehouse_id=inventory.warehouse_id, reference_type=reference_type, reference_id=reference_id,
            note=reason,
        )

    inventory.quantity = new_balance
    setattr(inventory, _EXPECTED_QUANTITY, new_balance)
    if inventory.stock_status in (None, AVAILABLE) and movement_type not in _MOVE_TYPES:
        if new_balance > (inventory.reorder_point or 0):
            # از این به بعد اگر به حد آستانه برسد، اعلان «رو‌به‌اتمام» می‌گیرد
            inventory.ever_exceeded_reorder = True
            inventory.low_alerted = False
        else:
            # هشدار فوری (همان لحظه خروج کالا) — بررسی ساعتی فقط پشتیبان است
            from app.services import notification_service
            notification_service.low_stock(db, inventory)

    status = inventory.stock_status or AVAILABLE
    movement = StockMovement(
        document=document,
        inventory=inventory,
        organization_id=inventory.organization_id,
        product_id=inventory.product_id,
        warehouse_id=inventory.warehouse_id,
        stock_status=status,
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

    sign = 1 if change > 0 else -1
    for key, qty in lines:
        balance = lock_balance(db, inventory, key, create=change > 0)
        if change < 0 and (balance is None or (balance.quantity or 0) < qty):
            location = db.get(Location, key.location_id) if key.location_id else None
            raise ConflictError(f"موجودی کافی نیست ({describe(key, location)}): موجود {balance.quantity if balance else 0} "
                                f"عدد — درخواستی {qty} عدد. احتمالاً کالا قبلاً جابه‌جا یا خارج شده است.")
        if change > 0 and not _is_new(inventory):
            _check_incoming(db, inventory, key, qty)
        balance.quantity = (balance.quantity or 0) + sign * qty
        setattr(balance, _EXPECTED_QUANTITY, balance.quantity)
        db.add(StockMovementLine(
            movement=movement, balance=balance, organization_id=inventory.organization_id,
            product_id=inventory.product_id, warehouse_id=inventory.warehouse_id, stock_status=status,
            quantity_change=sign * qty, balance_after=balance.quantity, **asdict(key),
        ))

    if change < 0 and status == AVAILABLE and reserved and movement_type not in _MOVE_TYPES and not _is_new(inventory):
        from app.services import allocation_service
        allocation_service.ensure_covered(db, inventory)
    return movement


def move(db: Session, source: Inventory, quantity: int, *, document: StockDocument, target: Inventory | None = None,
         out_type: str = "move_out", in_type: str = "move_in", match: dict | None = None, lines: list[Line] | None = None,
         overrides: dict | None = None, pick: str = PROTECT_ALLOCATABLE, user: User | None = None,
         reason: str | None = None, reference_type: str | None = None, reference_id: int | None = None,
         ) -> tuple[StockMovement, StockMovement]:
    """
    جابه‌جایی دومرحله‌ای زیر یک سند: خروج از source (محدوده match یا lines) و ورود همان ردیف‌های ریز به target
    (پیش‌فرض همان ردیف) با تغییر overrides — مثلاً {"location_id": مقصد} برای جانمایی، یا ردیف وضعیت دیگر
    برای تغییر وضعیت کیفی (محل و بچ ثابت می‌ماند)، یا ردیف انبار دیگر برای انتقال.
    """
    common = {"document": document, "user": user, "reason": reason, "reference_type": reference_type, "reference_id": reference_id}
    if target is None or target is source:
        # جابه‌جایی داخل همان ردیف (جانمایی، برداشت، محل به محل): اول ورود و بعد خروج، تا مانده ردیف حتی لحظه‌ای
        # کمتر از رزرو نشود — کالای رزروشده هم می‌تواند جابه‌جا شود.
        if lines is None:
            lines = pick_lines(db, source, quantity, match=match, policy=pick)
        inn = record(db, source, quantity, in_type, lines=[(key.with_(**(overrides or {})), qty) for key, qty in lines], **common)
        out = record(db, source, -quantity, out_type, lines=lines, **common)
        if (source.stock_status or AVAILABLE) == AVAILABLE and source.reserved_quantity:
            from app.services import allocation_service
            allocation_service.ensure_covered(db, source)
        return out, inn
    out = record(db, source, -quantity, out_type, match=match, lines=lines, pick=pick, **common)
    inn = record(db, target, quantity, in_type, lines=mirror(out, **(overrides or {})), **common)
    if (source.stock_status or AVAILABLE) == AVAILABLE and source.reserved_quantity:
        from app.services import allocation_service
        allocation_service.ensure_covered(db, source)
    return out, inn


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
    ناسازگاری‌های دفتر گردش (باید همیشه خالی باشد): مانده ردیف موجودی با مجموع گردش‌ها و مجموع ردیف‌های ریز،
    رزرو با رزروهای فعال، مانده هر ردیف ریز با گردش‌های ریزش و هر گردش با مجموع ردیف‌های ریزش.
    """
    db.flush()
    sums = dict(db.query(StockMovement.inventory_id, func.coalesce(func.sum(StockMovement.quantity_change), 0))
                .group_by(StockMovement.inventory_id).all())
    reserved = dict(db.query(StockReservation.inventory_id, func.coalesce(func.sum(StockReservation.quantity), 0))
                    .filter(StockReservation.status == "active").group_by(StockReservation.inventory_id).all())
    detail = dict(db.query(StockBalance.inventory_id, func.coalesce(func.sum(StockBalance.quantity), 0))
                  .group_by(StockBalance.inventory_id).all())
    mismatches = []
    for inv in db.query(Inventory).all():
        ledger_total = int(sums.get(inv.id, 0))
        reserved_total = int(reserved.get(inv.id, 0))
        detail_total = int(detail.get(inv.id, 0))
        if ledger_total != (inv.quantity or 0) or reserved_total != (inv.reserved_quantity or 0) or detail_total != (inv.quantity or 0):
            mismatches.append({
                "kind": "inventory", "inventory_id": inv.id, "product_id": inv.product_id, "warehouse_id": inv.warehouse_id,
                "stock_status": inv.stock_status, "quantity": inv.quantity, "ledger_total": ledger_total,
                "detail_total": detail_total, "reserved_quantity": inv.reserved_quantity, "reserved_total": reserved_total,
            })
    line_sums = dict(db.query(StockMovementLine.balance_id, func.sum(StockMovementLine.quantity_change))
                     .group_by(StockMovementLine.balance_id).all())
    for balance_id, quantity in db.query(StockBalance.id, StockBalance.quantity).all():
        if int(line_sums.get(balance_id, 0)) != (quantity or 0):
            mismatches.append({"kind": "balance", "balance_id": balance_id, "quantity": quantity,
                               "ledger_total": int(line_sums.get(balance_id, 0))})
    movement_lines = dict(db.query(StockMovementLine.movement_id, func.sum(StockMovementLine.quantity_change))
                          .group_by(StockMovementLine.movement_id).all())
    for movement_id, change in db.query(StockMovement.id, StockMovement.quantity_change).all():
        if int(movement_lines.get(movement_id, 0)) != change:
            mismatches.append({"kind": "movement", "movement_id": movement_id, "quantity_change": change,
                               "lines_total": int(movement_lines.get(movement_id, 0))})
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
        elif isinstance(obj, StockBalance):
            if (obj.quantity or 0) != 0 and getattr(obj, _EXPECTED_QUANTITY, None) != obj.quantity:
                raise LedgerViolationError("ردیف ریز موجودی فقط از دفتر گردش کالا (record) ساخته می‌شود.")

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
        elif isinstance(obj, StockBalance):
            if _changed(obj, "quantity") and getattr(obj, _EXPECTED_QUANTITY, None) != obj.quantity:
                raise LedgerViolationError(f"ردیف ریز موجودی {obj.id} بدون ثبت گردش تغییر کرده است.")
            if _changed(obj, "inventory_id", "product_id", "warehouse_id", "stock_status", "organization_id", *KEY_FIELDS):
                raise LedgerViolationError("ابعاد ردیف ریز موجودی (محل، بچ، سریال، مالک، انقضا) تغییرناپذیر است؛ از سند جابه‌جایی استفاده کنید.")
        elif isinstance(obj, (StockMovement, StockMovementLine, DomainEvent)):
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
        if isinstance(obj, (StockMovement, StockMovementLine, DomainEvent)):
            raise LedgerViolationError(f"{type(obj).__name__} قابل حذف نیست.")
        if isinstance(obj, StockDocument) and obj.status not in ("draft", "canceled"):
            raise LedgerViolationError("سند قطعی انبار قابل حذف نیست؛ برای اصلاح سند برگشت ثبت کنید.")
        if isinstance(obj, (Inventory, StockBalance)) and (obj.quantity or 0) != 0:
            raise LedgerViolationError(f"ردیف موجودی {obj.id} مانده دارد و قابل حذف نیست.")
        if isinstance(obj, Inventory) and (obj.reserved_quantity or 0) != 0:
            raise LedgerViolationError(f"ردیف موجودی {obj.id} رزرو دارد و قابل حذف نیست.")
        if isinstance(obj, StockReservation):
            raise LedgerViolationError("سابقه رزرو قابل حذف نیست.")
