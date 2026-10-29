"""مرکز اقدام (صفحه ورود هر نقش)، جستجوی سراسری و نماهای ذخیره‌شده فهرست‌ها."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Path, Query, status

from app.database import db_dependency
from app.dependencies import current_user_dependency, user_dependency
from app.schemas.action_center import ActionCenterOut, SavedViewIn, SavedViewOut, SavedViewPage, SearchOut
from app.services import action_center_service, saved_view_service, search_service
from app.services.exceptions import DomainError

router = APIRouter(tags=["🎯 مرکز اقدام و جستجو"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/action-center", response_model=ActionCenterOut, summary="🎯 کارهایی که الان اقدام می‌خواهند (بر اساس نقش)")
def action_center(db: db_dependency, user: current_user_dependency):
    return _call(action_center_service.action_center, db, user)


@router.get("/search", response_model=SearchOut, summary="🔎 جستجوی سراسری: سفارش، کالا، محموله، انتقال، تیکت، راننده، خودرو")
def search(db: db_dependency, user: current_user_dependency, q: str = Query(..., min_length=1, max_length=100)):
    return _call(search_service.search, db, user, q)


@router.get("/saved-views", response_model=list[SavedViewOut], summary="⭐ نماهای ذخیره‌شده یک صفحه (خودم و مشترک با نقشم)")
def list_views(db: db_dependency, user: user_dependency, page: Optional[SavedViewPage] = None):
    return _call(saved_view_service.list_views, db, user, page)


@router.post("/saved-views", response_model=SavedViewOut, status_code=status.HTTP_201_CREATED, summary="⭐ ذخیره نمای فعلی")
def create_view(data: SavedViewIn, db: db_dependency, user: user_dependency):
    return _call(saved_view_service.create_view, db, user, data)


@router.delete("/saved-views/{view_id}", status_code=status.HTTP_204_NO_CONTENT, summary="🗑️ حذف نمای خودم")
def delete_view(db: db_dependency, user: user_dependency, view_id: int = Path(gt=0)):
    _call(saved_view_service.delete_view, db, user, view_id)
