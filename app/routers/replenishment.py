"""نقطه سفارش با فرمول (ROP) و برآورد سرمایه لازم برای خرید ماه‌های آینده."""
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Path, Query

from app.database import db_dependency
from app.dependencies import user_dependency
from app.schemas.replenishment import (
    ApplyAutoIn, ApplyAutoOut, CapitalPlan, InventoryPolicy, InventoryPolicyUpdate, RopItem, RopItemUpdate, RopList,
)
from app.services import replenishment_service
from app.services.exceptions import DomainError

router = APIRouter(prefix="/replenishment", tags=["📈 نقطه سفارش و برنامه خرید"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/policy", response_model=InventoryPolicy, summary="⚙️ سیاست انبار سازمان (پیش‌فرض‌های فرمول)")
def get_policy(db: db_dependency, user: user_dependency):
    return _call(replenishment_service.get_policy, db, user)


@router.put("/policy", response_model=InventoryPolicy, summary="⚙️ تغییر سیاست انبار (فقط ادمین؛ اقلام خودکار دوباره محاسبه می‌شوند)")
def update_policy(data: InventoryPolicyUpdate, db: db_dependency, user: user_dependency):
    return _call(replenishment_service.update_policy, db, user, data.model_dump(exclude_none=True))


@router.get("/items", response_model=RopList, summary="📈 نقطه سفارش هر کالا در هر انبار با جزئیات فرمول")
def list_items(db: db_dependency, user: user_dependency, warehouse_id: Optional[int] = Query(None, gt=0),
               status: Optional[Literal["out", "critical", "reorder", "ok"]] = None,
               mode: Optional[Literal["manual", "auto"]] = None, q: Optional[str] = Query(None, max_length=100)):
    return _call(replenishment_service.list_items, db, user, warehouse_id, status, q, mode)


@router.put("/items/{inventory_id}", response_model=RopItem, summary="✏️ حالت (دستی/خودکار) و پارامترهای یک قلم")
def update_item(data: RopItemUpdate, db: db_dependency, user: user_dependency, inventory_id: int = Path(gt=0)):
    return _call(replenishment_service.update_item, db, user, inventory_id, data.model_dump(exclude_unset=True))


@router.post("/items/apply-auto", response_model=ApplyAutoOut, summary="⚡ خودکار کردن نقطه سفارش اقلام دارای سابقه کافی")
def apply_auto(data: ApplyAutoIn, db: db_dependency, user: user_dependency):
    return _call(replenishment_service.apply_auto, db, user, data.inventory_ids, data.warehouse_id)


@router.get("/capital-plan", response_model=CapitalPlan, summary="💰 سرمایه لازم برای خرید ماه‌های آینده (فقط ادمین)")
def capital_plan(db: db_dependency, user: user_dependency, months: int = Query(6, ge=1, le=12),
                 warehouse_id: Optional[int] = Query(None, gt=0),
                 price_growth: Optional[float] = Query(None, ge=-0.5, le=1, description="تورم ماهانه بهای خرید؛ خالی = سیاست سازمان"),
                 demand_growth: Optional[float] = Query(None, ge=-0.5, le=1, description="رشد ماهانه تقاضا؛ خالی = سیاست سازمان")):
    return _call(replenishment_service.plan, db, user, months, warehouse_id, price_growth, demand_growth)
