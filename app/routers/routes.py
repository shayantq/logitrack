"""مرحله ۱۰: مسیر سفارش روی نقشه، نقشه ارسال‌ها و گزارش «رسیدم به شهر ...» راننده."""
from fastapi import APIRouter, HTTPException, Path

from app.database import db_dependency
from app.dependencies import user_dependency
from app.core import geo
from app.schemas.route import GeoCity, CheckpointIn, MapOrders, MapScope, OrderRoute
from app.services import route_service
from app.services.exceptions import DomainError

router = APIRouter(tags=["🗺️ مسیر و نقشه"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/geo/cities", response_model=list[GeoCity], summary="🗺️ شهرهای هر استان (برای فهرست انتخاب شهر)")
def list_cities(province: str | None = None):
    return [GeoCity(name=c.name, province=c.province, capital=c.capital) for c in geo.cities_of(province)]


@router.get("/orders/{order_id}/route", response_model=OrderRoute, summary="🗺️ مسیر شهربه‌شهر و پیشرفت سفارش")
def get_route(db: db_dependency, user: user_dependency, order_id: int = Path(gt=0)):
    return _call(route_service.get_order_route, db, user, order_id)


@router.post("/orders/{order_id}/checkpoints", response_model=OrderRoute,
             summary="📍 گزارش راننده: رسیدم به این شهر")
def report_checkpoint(data: CheckpointIn, db: db_dependency, user: user_dependency, order_id: int = Path(gt=0)):
    return _call(route_service.report_checkpoint, db, user, order_id, data.seq)


@router.delete("/orders/{order_id}/checkpoints/last", response_model=OrderRoute,
               summary="↩️ برگرداندن آخرین گزارش موقعیت")
def undo_checkpoint(db: db_dependency, user: user_dependency, order_id: int = Path(gt=0)):
    return _call(route_service.undo_checkpoint, db, user, order_id)


@router.get("/map/orders", response_model=MapOrders, summary="🗺️ نقشه ارسال‌ها: سفارش‌ها با مسیر و پیشرفت")
def map_orders(db: db_dependency, user: user_dependency, scope: MapScope = "active"):
    return _call(route_service.map_orders, db, user, scope)
