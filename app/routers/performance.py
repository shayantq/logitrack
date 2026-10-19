"""مرحله ۸: قوانین سطح و پورسانت، امتیازدهی، پروفایل کامل راننده، عملکرد من و برترین رانندگان."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from app.core.rate_limit import RateLimiter
from app.database import db_dependency
from app.dependencies import require_role
from app.models import RoleEnum
from app.schemas.performance import (
    CommissionPlanIn, CommissionPlanOut, DriverOverview, LeaderboardRow, OrderRatings, PerformanceResponse,
    PublicRatingInfo, RatingIn, RatingOut,
)
from app.services import commission_service, performance_service
from app.services.exceptions import DomainError
from app.services import audit_service

staff = require_role([RoleEnum.ORG_ADMIN, RoleEnum.WAREHOUSE_MANAGER])
org_admin = require_role([RoleEnum.ORG_ADMIN])
driver_only = require_role([RoleEnum.DRIVER])
platform_staff = require_role([RoleEnum.PLATFORM_ADMIN, RoleEnum.PLATFORM_SUPPORT])
public_rating_limiter = RateLimiter(max_requests=30, window_seconds=3600)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


router = APIRouter(tags=["🏆 عملکرد، امتیاز و پورسانت رانندگان"])


@router.get("/commission-plan", response_model=CommissionPlanOut, summary="📐 قوانین کرایه، سطح و پورسانت پلکانی")
def get_plan(db: db_dependency, user=Depends(staff)):
    return commission_service.get_plan(db)


@router.put("/commission-plan", response_model=CommissionPlanOut, summary="✏️ تغییر قوانین (فقط سفارش‌های بعدی را تحت تأثیر قرار می‌دهد)")
def save_plan(data: CommissionPlanIn, db: db_dependency, user=Depends(org_admin)):
    result = commission_service.save_plan(db, user, data.model_dump())
    audit_service.record(db, user, "commission.plan", "قوانین سطح، کرایه و پورسانت تغییر کرد")
    return result


@router.get("/drivers/leaderboard", response_model=list[LeaderboardRow], summary="🏆 برترین رانندگان")
def leaderboard(db: db_dependency, period: Literal["month", "all"] = "month",
                sort: Literal["deliveries", "rating", "earnings", "success"] = "deliveries", user=Depends(staff)):
    return _call(performance_service.leaderboard, db, user, period, sort)


@router.get("/drivers/{driver_id}/overview", response_model=DriverOverview, summary="🪪 پروفایل کامل راننده")
def overview(db: db_dependency, driver_id: int = Path(gt=0), user=Depends(staff)):
    return _call(performance_service.overview, db, user, driver_id)


@router.get("/driver/performance", response_model=PerformanceResponse, summary="📈 سطح، امتیاز و درآمد من (راننده)")
def my_performance(db: db_dependency, user=Depends(driver_only)):
    return _call(performance_service.my_performance, db, user)


@router.get("/orders/{order_id}/rating", response_model=OrderRatings, summary="⭐ امتیازهای یک سفارش + لینک نظرسنجی مشتری")
def order_ratings(db: db_dependency, order_id: int = Path(gt=0), user=Depends(staff)):
    return _call(performance_service.order_ratings, db, user, order_id)


@router.put("/orders/{order_id}/rating", response_model=OrderRatings, summary="⭐ امتیاز سازمان به راننده برای این سفارش")
def rate_order(data: RatingIn, db: db_dependency, order_id: int = Path(gt=0), user=Depends(staff)):
    return _call(performance_service.rate_order, db, user, order_id, data.score, data.comment, data.tags)


@router.get("/public/ratings/{token}", response_model=PublicRatingInfo, summary="⭐ صفحه نظرسنجی مشتری (عمومی)")
def public_info(token: str, db: db_dependency):
    return _call(performance_service.public_rating_info, db, token)


@router.post("/public/ratings/{token}", response_model=PublicRatingInfo, summary="⭐ ثبت امتیاز مشتری (یک‌بار)")
def public_submit(token: str, data: RatingIn, request: Request, db: db_dependency):
    if not public_rating_limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="تعداد درخواست‌ها زیاد است؛ کمی بعد تلاش کنید.")
    return _call(performance_service.submit_public_rating, db, token, data.score, data.comment, data.tags)


@router.get("/platform/organizations/{organization_id}/drivers", summary="🛰️ رانندگان یک سازمان با امتیاز (پلتفرم)")
def platform_drivers(db: db_dependency, organization_id: int = Path(gt=0), user=Depends(platform_staff)):
    return _call(performance_service.platform_driver_ratings, db, user, organization_id)


@router.post("/platform/organizations/{organization_id}/drivers/{driver_id}/ratings", response_model=RatingOut, status_code=201,
             summary="🛰️ ارزیابی پلتفرم از راننده")
def platform_rate(data: RatingIn, db: db_dependency, organization_id: int = Path(gt=0), driver_id: int = Path(gt=0),
                  user=Depends(platform_staff)):
    return _call(performance_service.platform_rate_driver, db, user, organization_id, driver_id, data.score, data.comment)

