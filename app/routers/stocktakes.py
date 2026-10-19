"""مرحله ۱۲: انبارگردانی دوره‌ای — شمارش کور، بررسی مغایرت، شمارش مجدد، تأیید و اصلاح موجودی."""
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Path

from app.database import db_dependency
from app.dependencies import user_dependency
from app.schemas.stocktake import (
    AddLineIn, ApproveIn, CountIn, IntervalIn, RecountIn, StocktakeCount, StocktakeCreate, StocktakeDetail, StocktakeSummary,
    WarehouseStocktakeStatus,
)
from app.services import stocktake_service
from app.services.exceptions import DomainError

router = APIRouter(prefix="/stocktakes", tags=["📋 انبارگردانی"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/", response_model=list[StocktakeSummary], summary="📋 انبارگردانی‌ها")
def list_stocktakes(db: db_dependency, user: user_dependency,
                    status: Optional[Literal["counting", "review", "approved", "canceled"]] = None, warehouse_id: Optional[int] = None):
    return _call(stocktake_service.list_stocktakes, db, user, status, warehouse_id)


@router.get("/overview", response_model=list[WarehouseStocktakeStatus], summary="🏬 وضعیت انبارگردانی هر انبار و سررسید دوره بعد")
def overview(db: db_dependency, user: user_dependency):
    return _call(stocktake_service.overview, db, user)


@router.get("/summary", response_model=StocktakeCount, summary="🔔 تعداد کارهای انبارگردانی (برای نشان منو)")
def summary(db: db_dependency, user: user_dependency):
    return _call(stocktake_service.summary, db, user)


@router.put("/warehouses/{warehouse_id}/interval", response_model=list[WarehouseStocktakeStatus],
            summary="🗓️ دوره انبارگردانی انبار (هر چند روز؛ خالی = بدون برنامه)")
def set_interval(data: IntervalIn, db: db_dependency, user: user_dependency, warehouse_id: int = Path(gt=0)):
    return _call(stocktake_service.set_interval, db, user, warehouse_id, data.days)


@router.post("/", response_model=StocktakeDetail, status_code=201, summary="➕ شروع انبارگردانی (کامل یا بخشی)")
def create(data: StocktakeCreate, db: db_dependency, user: user_dependency):
    return _call(stocktake_service.create, db, user, warehouse_id=data.warehouse_id, scope=data.scope,
                 product_ids=data.product_ids, title=data.title, note=data.note)


@router.get("/{stocktake_id}", response_model=StocktakeDetail, summary="📄 جزئیات (عدد سیستم فقط در مرحله بررسی و برای ادمین)")
def get_stocktake(db: db_dependency, user: user_dependency, stocktake_id: int = Path(gt=0)):
    return _call(stocktake_service.detail, db, user, stocktake_id)


@router.put("/{stocktake_id}/lines/{line_id}", response_model=StocktakeDetail, summary="🔢 ثبت شمارش یک قلم")
def count(data: CountIn, db: db_dependency, user: user_dependency, stocktake_id: int = Path(gt=0), line_id: int = Path(gt=0)):
    return _call(stocktake_service.count, db, user, stocktake_id, line_id, data.counted_qty)


@router.post("/{stocktake_id}/lines", response_model=StocktakeDetail, summary="➕ کالای پیداشده خارج از فهرست")
def add_line(data: AddLineIn, db: db_dependency, user: user_dependency, stocktake_id: int = Path(gt=0)):
    return _call(stocktake_service.add_line, db, user, stocktake_id, data.product_id, data.counted_qty)


@router.post("/{stocktake_id}/submit", response_model=StocktakeDetail, summary="📤 پایان شمارش و ارسال برای بررسی")
def submit(db: db_dependency, user: user_dependency, stocktake_id: int = Path(gt=0)):
    return _call(stocktake_service.submit, db, user, stocktake_id)


@router.post("/{stocktake_id}/recount", response_model=StocktakeDetail, summary="🔁 درخواست شمارش مجدد اقلام مشکوک")
def recount(data: RecountIn, db: db_dependency, user: user_dependency, stocktake_id: int = Path(gt=0)):
    return _call(stocktake_service.recount, db, user, stocktake_id, data.line_ids, data.note)


@router.post("/{stocktake_id}/approve", response_model=StocktakeDetail, summary="✅ تأیید و اصلاح موجودی")
def approve(data: ApproveIn, db: db_dependency, user: user_dependency, stocktake_id: int = Path(gt=0)):
    return _call(stocktake_service.approve, db, user, stocktake_id, data.reasons)


@router.post("/{stocktake_id}/cancel", response_model=StocktakeDetail, summary="✖️ لغو انبارگردانی")
def cancel(db: db_dependency, user: user_dependency, stocktake_id: int = Path(gt=0)):
    return _call(stocktake_service.cancel, db, user, stocktake_id)
