"""محل‌های انبار (فصل ۶): منطقه، راهرو، قفسه، طبقه و خانه با نوع، ظرفیت و قاعده اختلاط."""
from fastapi import APIRouter, HTTPException, Path, Query, status

from app.database import db_dependency
from app.dependencies import user_dependency
from app.schemas.operations import LocationIn, LocationOut
from app.services import location_service
from app.services.exceptions import DomainError

router = APIRouter(tags=["📍 محل‌های انبار"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/warehouses/{warehouse_id}/locations", response_model=list[LocationOut],
            summary="🗺️ محل‌های یک انبار (درختی، با میزان پر بودن)")
def list_locations(db: db_dependency, user: user_dependency, warehouse_id: int = Path(gt=0)):
    return _call(location_service.list_locations, db, user, warehouse_id)


@router.post("/warehouses/{warehouse_id}/locations", response_model=LocationOut, status_code=status.HTTP_201_CREATED,
             summary="➕ تعریف محل")
def create_location(data: LocationIn, db: db_dependency, user: user_dependency, warehouse_id: int = Path(gt=0)):
    return _call(location_service.create_location, db, user, warehouse_id, data.model_dump())


@router.get("/warehouses/{warehouse_id}/locations/lookup", response_model=LocationOut,
            summary="🔎 پیدا کردن محل با اسکن بارکد یا کد")
def lookup_location(db: db_dependency, user: user_dependency, warehouse_id: int = Path(gt=0),
                    code: str = Query(min_length=1, max_length=64)):
    return _call(location_service.lookup, db, user, warehouse_id, code)


@router.get("/locations/{location_id}", response_model=LocationOut, summary="📄 جزئیات و محتوای محل")
def get_location(db: db_dependency, user: user_dependency, location_id: int = Path(gt=0)):
    return _call(location_service.location_detail, db, user, location_id)


@router.put("/locations/{location_id}", response_model=LocationOut, summary="✏️ ویرایش محل (ظرفیت، اختلاط، مسدودسازی)")
def update_location(data: LocationIn, db: db_dependency, user: user_dependency, location_id: int = Path(gt=0)):
    return _call(location_service.update_location, db, user, location_id, data.model_dump())


@router.delete("/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT, summary="🗑️ حذف محل بی‌سابقه")
def delete_location(db: db_dependency, user: user_dependency, location_id: int = Path(gt=0)):
    _call(location_service.delete_location, db, user, location_id)
