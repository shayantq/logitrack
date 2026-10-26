"""
جانمایی و مدیریت نگهداری (فصل ۹)

وظیفه جانمایی: «این مقدار از این کالا (با این بچ/مالک/وضعیت) را از محل مبدأ به یک محل نگهداری ببر».
  • ساخت خودکار: پس از دریافت رسید یا بازرسی، برای کالایی که در محل تخلیه/بدون محل مانده است (فقط اگر انبار
    محل نگهداری مناسب دارد). ساخت دستی هم ممکن است. مجموع وظایف باز یک محدوده از موجودی آن بیشتر نمی‌شود.
  • پیشنهاد مقصد (suggest): محل‌های انتهایی، فعال و غیرمسدود از نوع مناسب (تأییدشده ← نگهداری/برداشت،
    غیرقابل‌استفاده ← قرنطینه) که با ظرفیت و قاعده اختلاط جا دارند؛ اولویت: همان کالا و بچ، همان کالا،
    محل خالی، بقیه — و در هر گروه به ترتیب کد محل.
  • اجرا (execute): اسکن کالا (SKU، بارکد کالا یا بارکد واحد فرعی)، محل مبدأ و محل مقصد اجباری است.
    مقصد می‌تواند غیر از پیشنهاد باشد اگر از نوع مناسب باشد و جا داشته باشد. اجرای ناقص مجاز است.
  • خطا: اسکن اشتباه یا نقض قاعده محل رد می‌شود و در شمارنده خطای وظیفه و رویداد putaway.task.failed می‌ماند.
    گزارش مشکل: مقصد پر/مسدود ← آن محل کنار گذاشته و مقصد دیگری پیشنهاد می‌شود؛ کالای آسیب‌دیده ←
    باقی‌مانده در همان محل «آسیب‌دیده» می‌شود و وظیفه بسته می‌شود؛ کالای ناموجود ← وظیفه بسته می‌شود
    (اختلاف موجودی فقط با انبارگردانی/اصلاحیه اصلاح می‌شود، نه خودکار).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.wms import (
    AVAILABLE, LOCATION_TYPES, PENDING, PUTAWAY_PROBLEM_LABELS, PUTAWAY_STATUS_LABELS, STOCK_STATUS_LABELS, TASK_TYPE_LABELS,
    quality_roles,
)
from app.models import (
    Location, Product, ProductUom, PutawayTask, StockBalance, StockDocument, StockMovement, User, Warehouse,
)
from app.services import event_bus, location_service, stock_document_service, stock_ledger
from app.services.exceptions import ConflictError, DomainError, ForbiddenError, NotFoundError


class ScanMismatchError(DomainError):
    def __init__(self, message: str):
        super().__init__(message, status_code=422)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def target_kind(stock_status: str) -> str:
    return "approved" if stock_status == AVAILABLE else "held"


def _scope(task: PutawayTask) -> dict:
    return {"location_id": task.source_location_id, "owner_id": task.owner_id, "lot_number": task.lot_number,
            "expiry_date": task.expiry_date}


# ---------------------------------------------------------------------------
# پیشنهاد مقصد
# ---------------------------------------------------------------------------
def candidates(db: Session, warehouse_id: int, stock_status: str) -> list[Location]:
    kind = target_kind(stock_status)
    types = [t.code for t in LOCATION_TYPES.values() if t.putaway_for == kind]
    parents = {p for (p,) in db.query(Location.parent_id).filter(Location.warehouse_id == warehouse_id,
                                                                   Location.parent_id.is_not(None)).all()}
    return [loc for loc in db.query(Location).filter(
        Location.warehouse_id == warehouse_id, Location.location_type.in_(types), Location.is_active.is_not(False),
        Location.is_blocked.is_not(True),
    ).order_by(Location.code).all() if loc.id not in parents]


def suggest(db: Session, *, warehouse_id: int, product: Product, quantity: int, stock_status: str,
            lot_number: str | None, owner_id: int | None, exclude=()) -> Location | None:
    options = [loc for loc in candidates(db, warehouse_id, stock_status) if loc.id not in set(exclude)]
    if not options:
        return None
    db.flush()
    groups = location_service.contents(db, [loc.id for loc in options])
    products = {p.id: p for p in db.query(Product).filter(
        Product.id.in_({c.product_id for items in groups.values() for c in items} or {-1})).all()}
    ranked = []
    for loc in options:
        items = groups.get(loc.id, [])
        if location_service.fit_problems(loc, product, quantity, lot_number=lot_number, owner_id=owner_id, items=items,
                                         products=products, is_leaf=True):
            continue
        same_product = [c for c in items if c.product_id == product.id]
        rank = 0 if any(c.lot_number == lot_number for c in same_product) else 1 if same_product else 2 if not items else 3
        ranked.append((rank, loc.code, loc))
    return min(ranked, key=lambda r: (r[0], r[1]))[2] if ranked else None


def _resuggest(db: Session, task: PutawayTask) -> None:
    exclude = set(task.excluded_location_ids or []) | ({task.source_location_id} if task.source_location_id else set())
    location = suggest(db, warehouse_id=task.warehouse_id, product=task.product or db.get(Product, task.product_id),
                       quantity=task.remaining, stock_status=task.stock_status, lot_number=task.lot_number,
                       owner_id=task.owner_id, exclude=exclude)
    task.suggested_location_id = location.id if location else None


# ---------------------------------------------------------------------------
# ساخت وظیفه
# ---------------------------------------------------------------------------
def _scope_quantity(db: Session, *, warehouse_id: int, product_id: int, stock_status: str, scope: dict) -> int:
    db.flush()
    query = db.query(func.coalesce(func.sum(StockBalance.quantity), 0)).filter(
        StockBalance.warehouse_id == warehouse_id, StockBalance.product_id == product_id,
        StockBalance.stock_status == stock_status)
    for name, value in scope.items():
        column = getattr(StockBalance, name)
        query = query.filter(column.is_(None) if value is None else column == value)
    return int(query.scalar() or 0)


def _open_quantity(db: Session, *, warehouse_id: int, product_id: int, stock_status: str, scope: dict,
                   exclude_task_id: int | None = None) -> int:
    query = db.query(PutawayTask).filter(
        PutawayTask.warehouse_id == warehouse_id, PutawayTask.product_id == product_id,
        PutawayTask.stock_status == stock_status, PutawayTask.status.in_(("open", "partial")))
    for name, value in (("source_location_id", scope["location_id"]), ("owner_id", scope["owner_id"]),
                        ("lot_number", scope["lot_number"]), ("expiry_date", scope["expiry_date"])):
        column = getattr(PutawayTask, name)
        query = query.filter(column.is_(None) if value is None else column == value)
    if exclude_task_id is not None:
        query = query.filter(PutawayTask.id != exclude_task_id)
    return sum(t.remaining for t in query.all())


def _create(db: Session, user: User | None, *, warehouse_id: int, product: Product, quantity: int, stock_status: str,
            scope: dict, receipt_id: int | None = None, inspection_id: int | None = None, note: str | None = None,
            task_type: str = "putaway", destination_id: int | None = None) -> PutawayTask:
    on_hand = _scope_quantity(db, warehouse_id=warehouse_id, product_id=product.id, stock_status=stock_status, scope=scope)
    planned = _open_quantity(db, warehouse_id=warehouse_id, product_id=product.id, stock_status=stock_status, scope=scope)
    if quantity > on_hand - planned:
        raise ConflictError(f"در این محل {on_hand} عدد «{product.name}» هست و {planned} عدد آن قبلاً وظیفه جانمایی دارد؛ "
                            f"حداکثر {max(on_hand - planned, 0)} عدد دیگر قابل برنامه‌ریزی است.")
    task = PutawayTask(
        code=stock_ledger.new_code(db, PutawayTask, "PT"), status="open", warehouse_id=warehouse_id, product_id=product.id,
        product=product, stock_status=stock_status, quantity=quantity, quantity_done=0,
        source_location_id=scope["location_id"], owner_id=scope["owner_id"], lot_number=scope["lot_number"],
        expiry_date=scope["expiry_date"], receipt_id=receipt_id, inspection_id=inspection_id, excluded_location_ids=[],
        note=note, created_at=_now(), created_by_id=user.id if user else None, task_type=task_type,
    )
    db.add(task)
    if destination_id is not None:
        task.suggested_location_id = destination_id       # تأمین مجدد: مقصد همان محل برداشت قاعده است
    else:
        _resuggest(db, task)
    db.flush()
    event_bus.emit(db, "putaway.task.created", "putaway_task", task.id,
                   {"code": task.code, "product_id": product.id, "quantity": quantity, "stock_status": stock_status,
                    "source_location_id": task.source_location_id, "suggested_location_id": task.suggested_location_id},
                   organization_id=task.organization_id, actor=user)
    return task


def tasks_for_movement(db: Session, user: User | None, movement: StockMovement, *, receipt_id: int | None = None,
                       inspection_id: int | None = None) -> list[PutawayTask]:
    """
    پس از دریافت/بازرسی: برای کالایی که هنوز در جای مناسب وضعیتش نیست (تخلیه، بدون محل، یا محل نامتناسب با
    وضعیت کیفی) وظیفه جانمایی می‌سازد — فقط اگر انبار برای آن وضعیت محل مقصدی دارد.
    """
    # کالای «در انتظار بازرسی» تا نتیجه بازرسی در محل تخلیه می‌ماند
    if movement.quantity_change <= 0 or movement.stock_status == PENDING \
            or not candidates(db, movement.warehouse_id, movement.stock_status):
        return []
    kind = target_kind(movement.stock_status)
    groups: dict[tuple, int] = {}
    for line in movement.lines:
        location = db.get(Location, line.location_id) if line.location_id else None
        if location is not None and LOCATION_TYPES[location.location_type].putaway_for == kind:
            continue                      # همین الان در جای مناسب است
        key = (line.location_id, line.owner_id, line.lot_number, line.expiry_date)
        groups[key] = groups.get(key, 0) + line.quantity_change
    product = movement.product or db.get(Product, movement.product_id)
    tasks = []
    for (location_id, owner_id, lot, expiry), quantity in groups.items():
        tasks.append(_create(db, user, warehouse_id=movement.warehouse_id, product=product, quantity=quantity,
                             stock_status=movement.stock_status, receipt_id=receipt_id, inspection_id=inspection_id,
                             scope={"location_id": location_id, "owner_id": owner_id, "lot_number": lot, "expiry_date": expiry}))
    return tasks


def create_internal(db: Session, user: User | None, **kwargs) -> PutawayTask:
    """وظیفه از مسیرهای دیگر (برگشت کالای آماده‌سازی به قفسه، تأمین مجدد محل برداشت)."""
    return _create(db, user, **kwargs)


def create_task(db: Session, user: User, data) -> dict:
    warehouse_id = location_service.scope_warehouse(user, data.warehouse_id)
    if warehouse_id is None:
        raise ConflictError("انبار را انتخاب کنید.")
    product = db.get(Product, data.product_id)
    if product is None:
        raise NotFoundError("کالا یافت نشد.")
    try:
        if data.source_location_id is not None:
            location_service.resolve(db, warehouse_id, data.source_location_id)
        task = _create(db, user, warehouse_id=warehouse_id, product=product, quantity=data.quantity,
                       stock_status=data.stock_status, note=data.note,
                       scope={"location_id": data.source_location_id, "owner_id": data.owner_id,
                              "lot_number": data.lot_number, "expiry_date": data.expiry_date})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_task(db, user, task.id)


# ---------------------------------------------------------------------------
# اجرا با اسکن
# ---------------------------------------------------------------------------
def _lock_task(db: Session, user: User, task_id: int) -> PutawayTask:
    task = db.query(PutawayTask).filter(PutawayTask.id == task_id).with_for_update().first()
    if task is None:
        raise NotFoundError("وظیفه جانمایی یافت نشد.")
    location_service.scope_warehouse(user, task.warehouse_id)
    if task.status not in ("open", "partial"):
        raise ConflictError(f"وظیفه {task.code} {PUTAWAY_STATUS_LABELS[task.status]} است.")
    return task


def _record_failure(db: Session, user: User, task_id: int, problem: str, message: str) -> None:
    """خطای اجرا در تراکنش جدا ثبت می‌شود تا حتی وقتی عملیات رد شد، سابقه‌اش بماند."""
    db.rollback()
    task = db.get(PutawayTask, task_id)
    if task is None:
        return
    task.failure_count = (task.failure_count or 0) + 1
    task.last_problem, task.last_error = problem, message[:300]
    event_bus.emit(db, "putaway.task.failed", "putaway_task", task.id,
                   {"code": task.code, "problem": problem, "message": message[:300]},
                   organization_id=task.organization_id, actor=user)
    db.commit()


def matches_product(db: Session, product: Product, scanned: str) -> bool:
    value = (scanned or "").strip().upper()
    if not value:
        return False
    if value in {(product.sku or "").upper(), (product.barcode or "").upper()}:
        return True
    return db.query(ProductUom.id).filter(ProductUom.product_id == product.id,
                                          func.upper(ProductUom.barcode) == value).first() is not None


def _verify_scans(db: Session, task: PutawayTask, data) -> Location:
    product = task.product or db.get(Product, task.product_id)
    if not matches_product(db, product, data.product_scan):
        raise ScanMismatchError(f"کالای اسکن‌شده «{data.product_scan}» با کالای وظیفه ({product.sku}) یکی نیست.")
    if task.source_location_id is not None:
        source = location_service.find_by_scan(db, task.warehouse_id, data.source_scan)
        if source is None or source.id != task.source_location_id:
            expected = db.get(Location, task.source_location_id)
            raise ScanMismatchError(f"محل مبدأ اسکن‌شده «{data.source_scan}» با محل وظیفه ({expected.code}) یکی نیست.")
    else:
        warehouse = db.get(Warehouse, task.warehouse_id)
        if (data.source_scan or "").strip().upper() != (warehouse.code or "").upper():
            raise ScanMismatchError(f"کالای این وظیفه بدون محل است؛ به‌جای محل مبدأ کد انبار ({warehouse.code}) را اسکن کنید.")
    if task.lot_number and (data.lot_scan or "").strip().upper() != task.lot_number.upper():
        raise ScanMismatchError(f"بچ اسکن‌شده با بچ وظیفه ({task.lot_number}) یکی نیست.")
    destination = location_service.find_by_scan(db, task.warehouse_id, data.destination_scan)
    if destination is None:
        raise ScanMismatchError(f"محل مقصد «{data.destination_scan}» در این انبار پیدا نشد.")
    if destination.id == task.source_location_id:
        raise ScanMismatchError("محل مقصد همان محل مبدأ است.")
    kind = target_kind(task.stock_status)
    if LOCATION_TYPES[destination.location_type].putaway_for != kind:
        wanted = "نگهداری یا برداشت" if kind == "approved" else "قرنطینه"
        raise ScanMismatchError(f"کالای «{STOCK_STATUS_LABELS[task.stock_status]}» فقط در محل {wanted} جانمایی می‌شود؛ "
                                f"{destination.code} محل «{LOCATION_TYPES[destination.location_type].label}» است.")
    return destination


def execute(db: Session, user: User, task_id: int, data, idempotency_key: str | None = None) -> dict:
    def create(key, digest):
        task = _lock_task(db, user, task_id)
        if data.quantity > task.remaining:
            raise ConflictError(f"باقی‌مانده این وظیفه {task.remaining} عدد است.")
        try:
            destination = _verify_scans(db, task, data)
        except ScanMismatchError as error:
            _record_failure(db, user, task_id, "scan_mismatch", error.message)
            raise
        try:
            inventory = stock_ledger.lock_bucket(db, task.product_id, task.warehouse_id, task.stock_status, create=False)
            if inventory is None:
                raise ConflictError("کالای این وظیفه دیگر در انبار نیست.")
            document = stock_ledger.new_document(
                db, task.task_type, organization_id=task.organization_id, user=user, warehouse_id=task.warehouse_id,
                reference_type="putaway_task", reference_id=task.id, note=f"جانمایی {task.code}",
                idempotency_key=key, request_hash=digest,
            )
            stock_ledger.move(db, inventory, data.quantity, document=document, match=_scope(task),
                              overrides={"location_id": destination.id}, user=user, reason=f"جانمایی {task.code}")
            task.quantity_done += data.quantity
            task.destination_location_id = destination.id
            task.last_problem = task.last_error = None
            if task.remaining == 0:
                task.status, task.completed_at, task.completed_by_id = "done", _now(), user.id
                event_bus.emit(db, "putaway.task.completed", "putaway_task", task.id,
                               {"code": task.code, "destination_location_id": destination.id,
                                "suggested_location_id": task.suggested_location_id, "quantity": task.quantity},
                               organization_id=task.organization_id, actor=user)
            else:
                task.status = "partial"
                if task.task_type == "putaway":
                    _resuggest(db, task)
            db.commit()
            return document
        except ConflictError as error:
            _record_failure(db, user, task_id, "rule_violation", error.message)
            raise
        except Exception:
            db.rollback()
            raise

    stock_document_service.idempotent(db, StockDocument, idempotency_key, f"putaway:{task_id}",
                                      data.model_dump(mode="json"), create)
    return get_task(db, user, task_id)


def report_problem(db: Session, user: User, task_id: int, data) -> dict:
    try:
        task = _lock_task(db, user, task_id)
        message = PUTAWAY_PROBLEM_LABELS[data.problem] + (f" — {data.note}" if data.note else "")
        task.failure_count = (task.failure_count or 0) + 1
        task.last_problem, task.last_error = data.problem, message[:300]
        if data.problem in ("destination_full", "destination_blocked"):
            location_id = data.location_id or task.suggested_location_id
            if location_id is None:
                raise ConflictError("محل مقصدی که مشکل دارد را مشخص کنید.")
            task.excluded_location_ids = sorted(set(task.excluded_location_ids or []) | {location_id})
            _resuggest(db, task)
        elif data.problem == "item_damaged":
            if not quality_roles(task.stock_status, "damaged"):
                raise ConflictError(f"کالای «{STOCK_STATUS_LABELS[task.stock_status]}» را نمی‌توان «آسیب‌دیده» کرد.")
            if _role(user) not in quality_roles(task.stock_status, "damaged"):
                raise ForbiddenError("تغییر این وضعیت کیفی فقط با ادمین سازمان است.")
            source = stock_ledger.lock_bucket(db, task.product_id, task.warehouse_id, task.stock_status, create=False)
            damaged = stock_ledger.lock_bucket(db, task.product_id, task.warehouse_id, "damaged")
            document = stock_ledger.new_document(
                db, "status_change", organization_id=task.organization_id, user=user, warehouse_id=task.warehouse_id,
                reference_type="putaway_task", reference_id=task.id, note=f"آسیب‌دیدگی در جانمایی {task.code}",
            )
            label = f"{STOCK_STATUS_LABELS[task.stock_status]} ← {STOCK_STATUS_LABELS['damaged']}: {message}"
            stock_ledger.move(db, source, task.remaining, document=document, target=damaged, out_type="status_out",
                              in_type="status_in", match=_scope(task), user=user, reason=label)
            task.status, task.cancel_reason = "canceled", message[:300]
        else:  # item_missing
            task.status, task.cancel_reason = "canceled", message[:300]
        event_bus.emit(db, "putaway.task.failed", "putaway_task", task.id,
                       {"code": task.code, "problem": data.problem, "message": message[:300]},
                       organization_id=task.organization_id, actor=user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_task(db, user, task_id)


def cancel(db: Session, user: User, task_id: int, reason: str) -> dict:
    try:
        task = _lock_task(db, user, task_id)
        task.status, task.cancel_reason = "canceled", reason[:300]
        event_bus.emit(db, "putaway.task.canceled", "putaway_task", task.id, {"code": task.code, "reason": reason[:300]},
                       organization_id=task.organization_id, actor=user)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_task(db, user, task_id)


def refresh_suggestion(db: Session, user: User, task_id: int) -> dict:
    try:
        task = _lock_task(db, user, task_id)
        _resuggest(db, task)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_task(db, user, task_id)


# ---------------------------------------------------------------------------
# خواندن
# ---------------------------------------------------------------------------
def _serialize(task: PutawayTask, warehouse_code: str | None = None) -> dict:
    def code(loc):
        return loc.code if loc else None
    return {
        "id": task.id, "code": task.code, "status": task.status, "status_label": PUTAWAY_STATUS_LABELS[task.status],
        "task_type": task.task_type, "task_type_label": TASK_TYPE_LABELS[task.task_type],
        "warehouse_id": task.warehouse_id, "warehouse_code": warehouse_code, "product_id": task.product_id,
        "product_name": task.product.name, "product_sku": task.product.sku, "product_barcode": task.product.barcode,
        "unit": task.product.unit or "عدد", "stock_status": task.stock_status,
        "stock_status_label": STOCK_STATUS_LABELS.get(task.stock_status, task.stock_status),
        "quantity": task.quantity, "quantity_done": task.quantity_done, "remaining": task.remaining,
        "source_location_id": task.source_location_id, "source_location_code": code(task.source_location),
        "suggested_location_id": task.suggested_location_id, "suggested_location_code": code(task.suggested_location),
        "destination_location_id": task.destination_location_id, "destination_location_code": code(task.destination_location),
        "lot_number": task.lot_number, "expiry_date": task.expiry_date, "owner_id": task.owner_id,
        "owner_name": task.owner.name if task.owner else None, "receipt_id": task.receipt_id,
        "inspection_id": task.inspection_id, "failure_count": task.failure_count or 0, "last_problem": task.last_problem,
        "last_error": task.last_error, "note": task.note, "cancel_reason": task.cancel_reason,
        "created_at": task.created_at, "completed_at": task.completed_at,
    }


def _options(query):
    return query.options(joinedload(PutawayTask.product), joinedload(PutawayTask.source_location),
                         joinedload(PutawayTask.suggested_location), joinedload(PutawayTask.destination_location),
                         joinedload(PutawayTask.owner))


def get_task(db: Session, user: User, task_id: int) -> dict:
    task = _options(db.query(PutawayTask)).filter(PutawayTask.id == task_id).first()
    if task is None:
        raise NotFoundError("وظیفه جانمایی یافت نشد.")
    location_service.scope_warehouse(user, task.warehouse_id)
    warehouse = db.get(Warehouse, task.warehouse_id)
    return _serialize(task, warehouse.code if warehouse else None)


def list_tasks(db: Session, user: User, *, status: str | None = None, warehouse_id: int | None = None,
               receipt_id: int | None = None, task_type: str | None = None, limit: int = 200) -> list[dict]:
    warehouse_id = location_service.scope_warehouse(user, warehouse_id)
    query = _options(db.query(PutawayTask))
    if task_type:
        query = query.filter(PutawayTask.task_type == task_type)
    if warehouse_id is not None:
        query = query.filter(PutawayTask.warehouse_id == warehouse_id)
    if status == "active":
        query = query.filter(PutawayTask.status.in_(("open", "partial")))
    elif status:
        query = query.filter(PutawayTask.status == status)
    if receipt_id is not None:
        query = query.filter(PutawayTask.receipt_id == receipt_id)
    codes = {w.id: w.code for w in db.query(Warehouse).all()}
    return [_serialize(t, codes.get(t.warehouse_id)) for t in query.order_by(PutawayTask.id.desc()).limit(limit).all()]
