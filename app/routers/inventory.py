from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, status
from app.database import db_dependency
from app.dependencies import user_dependency
from app.schemas.product import (
    ProductCreate, ProductResponse, StockUpdate, StockMovementCreate, StockMovementResponse, StockTransferCreate,
)
from app.services import inventory_service
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
MovementType = Literal["initial", "receipt", "order_out", "order_return", "adjustment", "damage",
                       "transfer_out", "transfer_in", "stocktake"]


@router.get("/movements", response_model=list[StockMovementResponse], summary="📒 تاریخچه گردش کالا (ورود/خروج/اصلاح/انتقال)")
def list_movements(
    db: db_dependency,
    user: user_dependency,
    product_id: Optional[int] = Query(None, gt=0, description="فقط گردش‌های این کالا"),
    warehouse_id: Optional[int] = Query(None, gt=0, description="فقط این انبار (مدیر انبار همیشه انبار خودش)"),
    movement_type: Optional[MovementType] = Query(None, description="نوع گردش"),
    date_from: Optional[datetime] = Query(None, description="از تاریخ (شامل)"),
    date_to: Optional[datetime] = Query(None, description="تا تاریخ (بدون شامل)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    try:
        movements = inventory_service.list_movements(db, user, product_id, warehouse_id, movement_type,
                                                     date_from, date_to, skip, limit)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return [StockMovementResponse.from_movement(m) for m in movements]


@router.post("/movements", status_code=status.HTTP_201_CREATED, response_model=StockMovementResponse,
             summary="➕ ثبت گردش: ورود کالا، ضایعات یا اصلاح موجودی")
def record_movement(data: StockMovementCreate, db: db_dependency, user: user_dependency):
    try:
        movement = inventory_service.record_movement(db, user, data)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return StockMovementResponse.from_movement(movement)


@router.post("/transfers", status_code=status.HTTP_201_CREATED, response_model=list[StockMovementResponse],
             summary="🔁 انتقال کالا بین انبارهای سازمان")
def transfer_stock(data: StockTransferCreate, db: db_dependency, user: user_dependency):
    try:
        movements = inventory_service.transfer_stock(db, user, data)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return [StockMovementResponse.from_movement(m) for m in movements]


@router.get("/ledger-check", summary="🧮 بررسی صحت دفتر: مانده هر ردیف = مجموع گردش‌هایش")
def ledger_check(db: db_dependency, user: user_dependency):
    try:
        return inventory_service.ledger_check(db, user)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
