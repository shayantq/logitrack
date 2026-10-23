"""طرف‌های تجاری سازمان: تأمین‌کنندگان، مشتریان حقوقی/عمده و شرکت‌های حمل."""
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Path, Query, status

from app.core.wms import PARTNER_ROLES
from app.database import db_dependency
from app.dependencies import user_dependency
from app.schemas.partner import PartnerIn, PartnerOut
from app.services import partner_service
from app.services.exceptions import DomainError

router = APIRouter(prefix="/partners", tags=["🤝 طرف‌های تجاری"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/", response_model=list[PartnerOut], summary="📋 فهرست طرف‌های تجاری")
def list_partners(db: db_dependency, user: user_dependency,
                  role: Optional[Literal[PARTNER_ROLES]] = Query(None, description="فقط این نقش"),
                  q: Optional[str] = Query(None, max_length=100), include_inactive: bool = False):
    return _call(partner_service.list_partners, db, user, role=role, q=q, include_inactive=include_inactive)


@router.post("/", response_model=PartnerOut, status_code=status.HTTP_201_CREATED, summary="➕ تعریف طرف تجاری")
def create_partner(data: PartnerIn, db: db_dependency, user: user_dependency):
    return _call(partner_service.create_partner, db, user, data.model_dump())


@router.get("/{partner_id}", response_model=PartnerOut, summary="📄 مشخصات طرف تجاری")
def get_partner(db: db_dependency, user: user_dependency, partner_id: int = Path(gt=0)):
    return _call(partner_service.get_partner, db, user, partner_id)


@router.put("/{partner_id}", response_model=PartnerOut, summary="✏️ ویرایش طرف تجاری")
def update_partner(data: PartnerIn, db: db_dependency, user: user_dependency, partner_id: int = Path(gt=0)):
    return _call(partner_service.update_partner, db, user, partner_id, data.model_dump())


@router.post("/{partner_id}/archive", response_model=PartnerOut, summary="🗄️ بایگانی (غیرفعال‌سازی)")
def archive_partner(db: db_dependency, user: user_dependency, partner_id: int = Path(gt=0)):
    return _call(partner_service.set_active, db, user, partner_id, False)


@router.post("/{partner_id}/activate", response_model=PartnerOut, summary="♻️ فعال‌سازی دوباره")
def activate_partner(db: db_dependency, user: user_dependency, partner_id: int = Path(gt=0)):
    return _call(partner_service.set_active, db, user, partner_id, True)


@router.delete("/{partner_id}", status_code=status.HTTP_204_NO_CONTENT, summary="🗑️ حذف طرف تجاریِ بی‌سابقه")
def delete_partner(db: db_dependency, user: user_dependency, partner_id: int = Path(gt=0)):
    _call(partner_service.delete_partner, db, user, partner_id)
