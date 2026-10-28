"""مرحله ۱۱: تیکت پشتیبانی — سازمان و راننده، پشتیبانی پلتفرم، و مشتری با لینک محرمانه."""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Path, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app.core.rate_limit import RateLimiter
from app.database import db_dependency
from app.dependencies import require_role, user_dependency
from app.models import RoleEnum
from app.schemas.ticket import EscalateIn, PublicTicketCreated, TicketDetail, TicketsSummary, TicketSummary, TicketUpdate
from app.services import ticket_service
from app.services.exceptions import DomainError

platform_staff = require_role([RoleEnum.PLATFORM_ADMIN, RoleEnum.PLATFORM_SUPPORT])
# فرم عمومی: ۱۰ تیکت جدید و ۶۰ پیام در ساعت از هر IP
public_create_limiter = RateLimiter("ticket-create", max_requests=10, window_seconds=3600)
public_message_limiter = RateLimiter("ticket-message", max_requests=60, window_seconds=3600)
MAX_UPLOAD = ticket_service.MAX_IMAGE + 1

Status = Literal["open", "resolved", "closed"]
Source = Literal["customer", "driver", "org"]
VisibilityForm = Literal["all", "staff", "side"]


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


async def _read(file: UploadFile | None) -> bytes | None:
    if file is None or not file.filename:
        return None
    data = await file.read(MAX_UPLOAD)
    if len(data) >= MAX_UPLOAD:
        raise HTTPException(status_code=400, detail="حجم تصویر نباید بیشتر از ۵ مگابایت باشد.")
    return data


def _file(path_and_type):
    path, media_type = path_and_type
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=300"})


def _limit(limiter: RateLimiter, request: Request):
    if not limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="تعداد درخواست‌ها زیاد است؛ کمی بعد دوباره تلاش کنید.")


# ---------------------------------------------------------------------------
# سازمان (ادمین/مدیر انبار) و راننده
# ---------------------------------------------------------------------------
router = APIRouter(prefix="/tickets", tags=["🎫 تیکت‌ها (سازمان و راننده)"])


@router.get("/", response_model=list[TicketSummary], summary="📋 تیکت‌ها (راننده: فقط تیکت‌های خودش)")
def list_tickets(db: db_dependency, user: user_dependency, status: Optional[Status] = None,
                 waiting: bool = Query(False, description="فقط تیکت‌هایی که منتظر پاسخ من هستند"),
                 source: Optional[Source] = None, q: Optional[str] = Query(None, max_length=100)):
    return _call(ticket_service.list_tickets, db, user, status=status, waiting=waiting, source=source, q=q)


@router.get("/summary", response_model=TicketsSummary, summary="🔔 تعداد تیکت‌های منتظر پاسخ من")
def tickets_summary(db: db_dependency, user: user_dependency):
    return _call(ticket_service.summary, db, user)


@router.post("/", response_model=TicketDetail, status_code=201,
             summary="➕ تیکت جدید (راننده ← سازمان، کارکنان سازمان ← پشتیبانی پسینه)")
async def create_ticket(db: db_dependency, user: user_dependency, category: str = Form(...), body: str = Form(..., max_length=5000),
                        subject: Optional[str] = Form(None, max_length=200), priority: Literal["normal", "high", "urgent"] = Form("normal"),
                        order_id: Optional[int] = Form(None), file: Optional[UploadFile] = None):
    data = await _read(file)
    return _call(ticket_service.create_ticket, db, user, category=category, subject=subject, body=body,
                 priority=priority, order_id=order_id, attachment=data)


@router.get("/{ticket_id}", response_model=TicketDetail, summary="💬 جزئیات و گفت‌وگوی تیکت")
def get_ticket(db: db_dependency, user: user_dependency, ticket_id: int = Path(gt=0)):
    return _call(ticket_service.get_ticket, db, user, ticket_id)


@router.post("/{ticket_id}/messages", response_model=TicketDetail, summary="✉️ پیام جدید (پاسخ، پیام به پلتفرم یا یادداشت داخلی)")
async def post_message(db: db_dependency, user: user_dependency, ticket_id: int = Path(gt=0),
                       body: str = Form("", max_length=5000), visibility: VisibilityForm = Form("all"),
                       file: Optional[UploadFile] = None):
    data = await _read(file)
    return _call(ticket_service.post_message, db, user, ticket_id, body, visibility, data)


@router.post("/{ticket_id}/escalate", response_model=TicketDetail, summary="⤴️ ارجاع به پشتیبانی پسینه")
def escalate(data: EscalateIn, db: db_dependency, user: user_dependency, ticket_id: int = Path(gt=0)):
    return _call(ticket_service.escalate, db, user, ticket_id, data.reason)


@router.post("/{ticket_id}/resolve", response_model=TicketDetail, summary="✅ اعلام حل شدن")
def resolve(db: db_dependency, user: user_dependency, ticket_id: int = Path(gt=0)):
    return _call(ticket_service.resolve, db, user, ticket_id)


@router.post("/{ticket_id}/close", response_model=TicketDetail, summary="🔒 بستن تیکت")
def close(db: db_dependency, user: user_dependency, ticket_id: int = Path(gt=0)):
    return _call(ticket_service.close, db, user, ticket_id)


@router.patch("/{ticket_id}", response_model=TicketDetail, summary="✏️ اولویت و مسئول پیگیری")
def update(data: TicketUpdate, db: db_dependency, user: user_dependency, ticket_id: int = Path(gt=0)):
    return _call(ticket_service.update, db, user, ticket_id, priority=data.priority, assignee_id=data.assignee_id,
                 unassign=data.unassign)


@router.get("/{ticket_id}/messages/{message_id}/attachment", summary="🖼️ تصویر پیوست پیام")
def attachment(db: db_dependency, user: user_dependency, ticket_id: int = Path(gt=0), message_id: int = Path(gt=0)):
    return _file(_call(ticket_service.attachment, db, user, ticket_id, message_id))


# ---------------------------------------------------------------------------
# پشتیبانی پلتفرم — همه سازمان‌ها (فقط تیکت‌های ارجاعی و تیکت‌های خود سازمان‌ها)
# ---------------------------------------------------------------------------
platform_router = APIRouter(prefix="/platform/tickets", tags=["🎫 تیکت‌ها (پشتیبانی پلتفرم)"])


@platform_router.get("/", response_model=list[TicketSummary], summary="📋 تیکت‌های ارجاعی همه سازمان‌ها")
def platform_list(db: db_dependency, user=Depends(platform_staff), status: Optional[Status] = None, waiting: bool = False,
                  source: Optional[Source] = None, q: Optional[str] = Query(None, max_length=100)):
    return _call(ticket_service.list_tickets, db, user, status=status, waiting=waiting, source=source, q=q)


@platform_router.get("/summary", response_model=TicketsSummary, summary="🔔 تعداد تیکت‌های منتظر پشتیبانی")
def platform_summary(db: db_dependency, user=Depends(platform_staff)):
    return _call(ticket_service.summary, db, user)


@platform_router.get("/{ticket_id}", response_model=TicketDetail, summary="💬 جزئیات تیکت")
def platform_get(db: db_dependency, user=Depends(platform_staff), ticket_id: int = Path(gt=0)):
    return _call(ticket_service.get_ticket, db, user, ticket_id)


@platform_router.post("/{ticket_id}/messages", response_model=TicketDetail, summary="✉️ پاسخ پشتیبانی")
async def platform_message(db: db_dependency, user=Depends(platform_staff), ticket_id: int = Path(gt=0),
                           body: str = Form("", max_length=5000), visibility: VisibilityForm = Form("staff"),
                           file: Optional[UploadFile] = None):
    data = await _read(file)
    return _call(ticket_service.post_message, db, user, ticket_id, body, visibility, data)


@platform_router.post("/{ticket_id}/resolve", response_model=TicketDetail, summary="✅ پایان بررسی پلتفرم")
def platform_resolve(db: db_dependency, user=Depends(platform_staff), ticket_id: int = Path(gt=0)):
    return _call(ticket_service.resolve, db, user, ticket_id)


@platform_router.post("/{ticket_id}/close", response_model=TicketDetail, summary="🔒 بستن تیکت سازمان")
def platform_close(db: db_dependency, user=Depends(platform_staff), ticket_id: int = Path(gt=0)):
    return _call(ticket_service.close, db, user, ticket_id)


@platform_router.get("/{ticket_id}/messages/{message_id}/attachment", summary="🖼️ تصویر پیوست")
def platform_attachment(db: db_dependency, user=Depends(platform_staff), ticket_id: int = Path(gt=0), message_id: int = Path(gt=0)):
    return _file(_call(ticket_service.attachment, db, user, ticket_id, message_id))


# ---------------------------------------------------------------------------
# مشتری — بدون ورود (ثبت از صفحه پیگیری سفارش، پیگیری با لینک محرمانه)
# ---------------------------------------------------------------------------
public_router = APIRouter(tags=["🎫 پشتیبانی مشتری (عمومی)"])


@public_router.post("/public/track/{code}/tickets", response_model=PublicTicketCreated, status_code=201,
                    summary="🆘 درخواست پشتیبانی برای یک سفارش (با ۴ رقم آخر موبایل)")
async def public_create(code: str, request: Request, db: db_dependency, phone: str = Form(..., max_length=8),
                        category: str = Form(...), body: str = Form(..., min_length=5, max_length=3000),
                        file: Optional[UploadFile] = None):
    _limit(public_create_limiter, request)
    data = await _read(file)
    return _call(ticket_service.create_customer_ticket, db, code, phone, category=category, body=body, attachment=data)


@public_router.get("/public/tickets/{token}", response_model=TicketDetail, summary="💬 پیگیری درخواست پشتیبانی")
def public_get(token: str, db: db_dependency):
    return _call(ticket_service.public_get, db, token)


@public_router.post("/public/tickets/{token}/messages", response_model=TicketDetail, summary="✉️ پیام مشتری")
async def public_message(token: str, request: Request, db: db_dependency, body: str = Form("", max_length=3000),
                         file: Optional[UploadFile] = None):
    _limit(public_message_limiter, request)
    data = await _read(file)
    return _call(ticket_service.public_message, db, token, body, data)


@public_router.post("/public/tickets/{token}/resolve", response_model=TicketDetail, summary="✅ مشکل حل شد")
def public_resolve(token: str, db: db_dependency):
    return _call(ticket_service.public_resolve, db, token)


@public_router.get("/public/tickets/{token}/messages/{message_id}/attachment", summary="🖼️ تصویر پیوست")
def public_attachment(token: str, db: db_dependency, message_id: int = Path(gt=0)):
    return _file(_call(ticket_service.public_attachment, db, token, message_id))
