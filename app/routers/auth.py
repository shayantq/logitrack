from app.core.security import create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from app.schemas.user import CreateUserRequest, MessageResponse, PasswordResetChannels, PasswordResetConfirmIn, PasswordResetRequestIn, UserResponse
from app.models import User
from app.database import db_dependency
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Annotated
from datetime import timedelta
from starlette import status
from app.dependencies import user_dependency
from app.services import user_service
from app.services.exceptions import DomainError
from app.core.rate_limit import login_failure_limiter, password_reset_confirm_limiter, password_reset_request_limiter

router = APIRouter(
    prefix='/auth',
    tags=['🔐 احراز هویت و صدور توکن']
)


@router.post('/', status_code=status.HTTP_201_CREATED, response_model=UserResponse, summary="✨ ثبت کاربر جدید توسط ادمین")
def create_user(db: db_dependency, create_user_request: CreateUserRequest, current_user: user_dependency) -> User:
    """
    **سطح دسترسی:** فقط نقش **ادمین (Admin)** می‌تواند کاربر/راننده جدید ثبت کند.
    """
    try:
        return user_service.create_user(db, current_user, create_user_request)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post('/token', summary="🔑 ورود و دریافت توکن دسترسی JWT")
def login_for_access_token(request: Request, form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: db_dependency):
    # قفل موقت پس از تلاش‌های ناموفق، حساب غیرفعال و ثبت در گزارش فعالیت — app/services/user_service.authenticate
    # جدا از قفل هر حساب، تلاش ناموفق زیاد از یک IP (روی نام‌های کاربری مختلف) هم موقتاً بسته می‌شود
    ip = request.client.host if request.client else "unknown"
    if login_failure_limiter.blocked(ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="تلاش ناموفق ورود از این شبکه زیاد بوده است؛ چند دقیقه دیگر دوباره امتحان کنید.")
    try:
        user = user_service.authenticate(db, form_data.username, form_data.password)
    except DomainError as e:
        if e.status_code == 401:
            login_failure_limiter.allow(ip)
        raise HTTPException(status_code=e.status_code, detail=e.message)

    token = create_access_token(user.username, user.id, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES), user.token_version or 0)
    return {"access_token": token, "token_type": "bearer"}


# ---------------------------------------------------------------------------
# بازیابی رمز توسط خود کاربر (عمومی، بدون ورود)
# ---------------------------------------------------------------------------
RESET_SENT = "اگر حسابی با این مشخصات وجود داشته باشد، کد بازیابی به موبایل یا ایمیل ثبت‌شده در آن ارسال شد."


@router.get('/password-reset', response_model=PasswordResetChannels, summary="🔁 راه‌های فعال بازیابی رمز (پیامک/ایمیل)")
def password_reset_channels():
    return user_service.reset_channels()


@router.post('/password-reset/request', response_model=MessageResponse, summary="🔁 درخواست کد بازیابی رمز")
def password_reset_request(data: PasswordResetRequestIn, request: Request, db: db_dependency):
    """پاسخ همیشه یکسان است تا وجود یا نبودِ حساب فاش نشود."""
    if not password_reset_request_limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="تعداد درخواست‌ها زیاد است؛ کمی بعد دوباره امتحان کنید.")
    user_service.request_password_reset(db, data.identifier)
    return {"message": RESET_SENT}


@router.post('/password-reset/confirm', response_model=MessageResponse, summary="🔁 تأیید کد و تعیین رمز جدید")
def password_reset_confirm(data: PasswordResetConfirmIn, request: Request, db: db_dependency):
    if not password_reset_confirm_limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="تعداد تلاش‌ها زیاد است؛ کمی بعد دوباره امتحان کنید.")
    try:
        user_service.confirm_password_reset(db, data.identifier, data.code, data.new_password)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return {"message": "رمز عبور تغییر کرد؛ اکنون با رمز جدید وارد شوید."}
