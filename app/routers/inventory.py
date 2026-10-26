from datetime import date, datetime
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Path, Query, status
from app.core.wms import DOCUMENT_STATUSES, DOCUMENT_TYPES, RESERVATION_STATUSES, STOCK_STATUSES
from app.database import db_dependency
from app.dependencies import IdempotencyKey, user_dependency
from app.models import MOVEMENT_TYPES
from app.schemas.product import (
    LocationMoveCreate, ProductCreate, ProductResponse, StatusChangeCreate, StockUpdate, StockMovementCreate,
    StockMovementResponse, StockTransferCreate,
)
from app.schemas.operations import StockBalanceOut, StockCardOut, StockPositionOut
from app.schemas.wms import ReservationOut, ReverseRequest, StockBucketOut, StockDocumentOut
from app.services import audit_service, inventory_service, stock_document_service, stock_position_service
from app.services.exceptions import DomainError

router = APIRouter(
    prefix="/inventory",
    tags=["📦 مدیریت انبار و زنجیره تامین"]
)


@router.get("/products", status_code=status.HTTP_200_OK, response_model=list[ProductResponse], summary="📋 دریافت لیست کالاهای موجود در کاتالوگ")
async def list_products(db: db_dependency, user: user_dependency):
    return inventory_service.list_products(db, user)


@router.post("/products", status_code=status.HTTP_201_CREATED, summary="➕ تعریف کالای جدید در کاتالوگ")
async def create_product(product_data: ProductCreate, db: db_dependency, user: user_dependency):
    """
    **توضیحات امنیت:** فقط لایه **ادمین (Admin)** و **مدیر انبار (Manager)** حق ثبت کالا دارند.
    """
    try:
        new_product = inventory_service.create_product(db, user, product_data)
        return {
            "message": "✅ محصول با موفقیت تعریف شد",
            "product": ProductResponse.model_validate(new_product).model_dump(include={"id", "name", "sku", "weight_kg", "price"})
        }
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT, summary="🗑️ حذف کالا از کاتالوگ")
async def delete_product(product_id: int, db: db_dependency, user: user_dependency):
    try:
        inventory_service.delete_product(db, user, product_id)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.put("/stock/{product_id}", summary="🔄 بروزرسانی موجودی و پایش سطح بحرانی")
async def update_stock(product_id: int, stock_data: StockUpdate, db: db_dependency, user: user_dependency):
    """
    بروزرسانی انبارداری + الگوریتم سنجش خودکار **Reorder Point**.
    """
    try:
        return inventory_service.update_stock(db, user, product_id, stock_data)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)



# =========================================================================
# دفتر گردش کالا
# =========================================================================
MovementType = Literal[MOVEMENT_TYPES]
DocumentType = Literal[tuple(DOCUMENT_TYPES)]


@router.get("/movements", response_model=list[StockMovementResponse], summary="📒 تاریخچه گردش کالا (ورود/خروج/اصلاح/انتقال)")
def list_movements(
    db: db_dependency,
    user: user_dependency,
    product_id: Optional[int] = Query(None, gt=0, description="فقط گردش‌های این کالا"),
    warehouse_id: Optional[int] = Query(None, gt=0, description="فقط این انبار (مدیر انبار همیشه انبار خودش)"),
    movement_type: Optional[MovementType] = Query(None, description="نوع گردش"),
    date_from: Optional[datetime] = Query(None, description="از تاریخ (شامل)"),
    date_to: Optional[datetime] = Query(None, description="تا تاریخ (بدون شامل)"),
    document_id: Optional[int] = Query(None, gt=0, description="فقط گردش‌های این سند"),
    stock_status: Optional[Literal[STOCK_STATUSES]] = Query(None, description="وضعیت کیفی"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    try:
        movements = inventory_service.list_movements(db, user, product_id, warehouse_id, movement_type,
                                                     date_from, date_to, skip, limit,
                                                     document_id=document_id, stock_status=stock_status)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return [StockMovementResponse.from_movement(m) for m in movements]


@router.post("/movements", status_code=status.HTTP_201_CREATED, response_model=StockMovementResponse,
             summary="➕ ثبت گردش: ورود کالا، ضایعات یا اصلاح موجودی")
def record_movement(data: StockMovementCreate, db: db_dependency, user: user_dependency, idempotency_key: IdempotencyKey = None):
    try:
        movement = inventory_service.record_movement(db, user, data, idempotency_key)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    if data.movement_type != "receipt":
        audit_service.record(db, user, "stock.adjust",
                             f"{'ضایعات' if data.movement_type == 'damage' else 'اصلاح موجودی'} {movement.quantity_change:+d} — "
                             f"{movement.product.name if movement.product else ''}", target_type="movement",
                             target_id=movement.id, reason=data.reason, details={"document_id": movement.document_id})
    return StockMovementResponse.from_movement(movement)


@router.post("/transfers", status_code=status.HTTP_201_CREATED, response_model=list[StockMovementResponse],
             summary="🔁 انتقال کالا بین انبارهای سازمان")
def transfer_stock(data: StockTransferCreate, db: db_dependency, user: user_dependency, idempotency_key: IdempotencyKey = None):
    try:
        movements = inventory_service.transfer_stock(db, user, data, idempotency_key)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return [StockMovementResponse.from_movement(m) for m in movements]


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/status-changes", status_code=status.HTTP_201_CREATED, response_model=StockDocumentOut,
             summary="🧪 تغییر وضعیت کیفی (قرنطینه، توقیف، معیوب ↔ سالم و آزاد)")
def change_status(data: StatusChangeCreate, db: db_dependency, user: user_dependency, idempotency_key: IdempotencyKey = None):
    result = _call(inventory_service.change_status, db, user, data, idempotency_key)
    audit_service.record(db, user, "stock.status_change", f"تغییر وضعیت کیفی {data.quantity} واحد: {data.from_status} ← {data.to_status}",
                         target_type="document", target_id=result.get("id"), target_label=result.get("code"), reason=data.reason)
    return result


@router.get("/documents", response_model=list[StockDocumentOut], summary="🧾 اسناد انبار (رسید، حواله، اصلاحیه، انتقال، ...)")
def list_documents(
    db: db_dependency,
    user: user_dependency,
    doc_type: Optional[DocumentType] = Query(None),
    status_: Optional[Literal[DOCUMENT_STATUSES]] = Query(None, alias="status"),
    warehouse_id: Optional[int] = Query(None, gt=0),
    product_id: Optional[int] = Query(None, gt=0),
    q: Optional[str] = Query(None, max_length=64, description="کد سند یا شماره فاکتور/بارنامه"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    return _call(stock_document_service.list_documents, db, user, doc_type=doc_type, status=status_,
                 warehouse_id=warehouse_id, product_id=product_id, q=q, date_from=date_from, date_to=date_to,
                 skip=skip, limit=limit)


@router.get("/documents/{document_id}", response_model=StockDocumentOut, summary="🧾 جزئیات سند انبار و گردش‌هایش")
def get_document(db: db_dependency, user: user_dependency, document_id: int = Path(gt=0)):
    return _call(stock_document_service.get_document, db, user, document_id)


@router.post("/documents/{document_id}/reverse", status_code=status.HTTP_201_CREATED, response_model=StockDocumentOut,
             summary="↩️ سند برگشت: خنثی کردن یک سند قطعی (بدون حذف یا ویرایش)")
def reverse_document(data: ReverseRequest, db: db_dependency, user: user_dependency, document_id: int = Path(gt=0),
                     idempotency_key: IdempotencyKey = None):
    result = _call(stock_document_service.reverse_document, db, user, document_id, data.reason, idempotency_key)
    audit_service.record(db, user, "stock.reverse", f"سند برگشت {result.get('code')} ثبت شد", target_type="document",
                         target_id=document_id, target_label=result.get("code"), reason=data.reason)
    return result


@router.get("/stock", response_model=list[StockBucketOut], summary="📊 موجودی به تفکیک انبار و وضعیت کیفی (با رزرو و موجودی آزاد)")
def stock_buckets(
    db: db_dependency,
    user: user_dependency,
    product_id: Optional[int] = Query(None, gt=0),
    warehouse_id: Optional[int] = Query(None, gt=0),
    stock_status: Optional[Literal[STOCK_STATUSES]] = Query(None),
    include_empty: bool = Query(False),
):
    return _call(inventory_service.stock_buckets, db, user, product_id, warehouse_id, stock_status, include_empty)


@router.get("/reservations", response_model=list[ReservationOut], summary="🔒 رزروهای موجودی (تخصیص به سفارش‌ها)")
def list_reservations(
    db: db_dependency,
    user: user_dependency,
    status_: Optional[Literal[RESERVATION_STATUSES]] = Query("active", alias="status"),
    product_id: Optional[int] = Query(None, gt=0),
    warehouse_id: Optional[int] = Query(None, gt=0),
):
    return _call(inventory_service.list_reservations, db, user, status_, product_id, warehouse_id)


@router.post("/location-moves", status_code=status.HTTP_201_CREATED, response_model=StockDocumentOut,
             summary="📍 جابه‌جایی کالا بین محل‌های یک انبار")
def move_between_locations(data: LocationMoveCreate, db: db_dependency, user: user_dependency,
                           idempotency_key: IdempotencyKey = None):
    return _call(inventory_service.move_between_locations, db, user, data, idempotency_key)


@router.get("/positions", response_model=list[StockPositionOut],
            summary="📐 وضعیت مقدار: فیزیکی، قابل تخصیص، رزرو، قابل وعده، در انتظار بازرسی، قرنطینه، در راه")
def stock_positions(db: db_dependency, user: user_dependency, product_id: Optional[int] = Query(None, gt=0),
                    warehouse_id: Optional[int] = Query(None, gt=0)):
    return _call(stock_position_service.positions, db, user, product_id=product_id, warehouse_id=warehouse_id)


@router.get("/balances", response_model=list[StockBalanceOut],
            summary="🧩 موجودی ریز: محل × بچ × سریال × مالک × انقضا")
def stock_balances(
    db: db_dependency, user: user_dependency,
    product_id: Optional[int] = Query(None, gt=0), warehouse_id: Optional[int] = Query(None, gt=0),
    location_id: Optional[int] = Query(None, gt=0), stock_status: Optional[Literal[STOCK_STATUSES]] = Query(None),
    lot_number: Optional[str] = Query(None, max_length=64), limit: int = Query(500, ge=1, le=2000),
):
    return _call(stock_position_service.balances, db, user, product_id=product_id, warehouse_id=warehouse_id,
                 location_id=location_id, stock_status=stock_status, lot_number=lot_number, limit=limit)


@router.get("/stock-card", response_model=StockCardOut, summary="🗂️ کاردکس کالا: مانده اول دوره، ورود، خروج و مانده")
def stock_card(
    db: db_dependency, user: user_dependency, product_id: int = Query(gt=0),
    warehouse_id: Optional[int] = Query(None, gt=0), location_id: Optional[int] = Query(None, gt=0),
    lot_number: Optional[str] = Query(None, max_length=64), stock_status: Optional[Literal[STOCK_STATUSES]] = Query(None),
    date_from: Optional[date] = Query(None, description="از تاریخ (شامل، به وقت ایران)"),
    date_to: Optional[date] = Query(None, description="تا تاریخ (بدون شامل)"),
    include_internal: bool = Query(False, description="نمایش جابه‌جایی‌های داخلی که در این محدوده خالص صفرند"),
):
    return _call(stock_position_service.stock_card, db, user, product_id=product_id, warehouse_id=warehouse_id,
                 location_id=location_id, lot_number=lot_number.upper() if lot_number else None,
                 stock_status=stock_status, date_from=date_from, date_to=date_to, include_internal=include_internal)


@router.get("/ledger-check", summary="🧮 بررسی صحت دفتر: مانده هر ردیف = مجموع گردش‌هایش")
def ledger_check(db: db_dependency, user: user_dependency):
    try:
        return inventory_service.ledger_check(db, user)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
