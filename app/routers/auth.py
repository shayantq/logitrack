from app.core.security import create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from app.schemas.user import CreateUserRequest, MessageResponse, PasswordResetChannels, PasswordResetConfirmIn, PasswordResetRequestIn, UserResponse
from app.models import User
from app.database import db_dependency
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Path, Request, Response
from typing import Annotated

from pydantic import BaseModel, Field
from datetime import timedelta
from starlette import status
from app.dependencies import current_user_dependency, user_dependency
from app.services import session_service, user_service
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
def login_for_access_token(request: Request, response: Response, form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
                           db: db_dependency, remember: Annotated[bool, Form()] = False,
                           otp: Annotated[str | None, Form(max_length=12)] = None):
    # قفل موقت پس از تلاش‌های ناموفق، حساب غیرفعال و ثبت در گزارش فعالیت — app/services/user_service.authenticate
    # جدا از قفل هر حساب، تلاش ناموفق زیاد از یک IP (روی نام‌های کاربری مختلف) هم موقتاً بسته می‌شود
    ip = request.client.host if request.client else "unknown"
    if login_failure_limiter.blocked(ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="تلاش ناموفق ورود از این شبکه زیاد بوده است؛ چند دقیقه دیگر دوباره امتحان کنید.")
    try:
        user = user_service.authenticate(db, form_data.username, form_data.password, otp)
    except user_service.MfaRequired as e:
        # رمز درست بوده؛ فرم ورود با این هدر فیلد کد دومرحله‌ای را نشان می‌دهد (کد اشتباه هم تلاش ناموفق است)
        if e.message != user_service.MFA_REQUIRED:
            login_failure_limiter.allow(ip)
        raise HTTPException(status_code=e.status_code, detail=e.message, headers={"X-MFA-Required": "1"})
    except DomainError as e:
        if e.status_code == 401:
            login_failure_limiter.allow(ip)
        raise HTTPException(status_code=e.status_code, detail=e.message)

    session_service.set_cookie(request, response, session_service.start(db, user, remember))
    return _access(user)


# ---------------------------------------------------------------------------
# نشست ماندگار: تمدید توکن کوتاه با کوکی HttpOnly، خروج، فهرست و بستن نشست‌ها (app/services/session_service.py)
# ---------------------------------------------------------------------------
def _access(user: User) -> dict:
    token = create_access_token(user.username, user.id, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES), user.token_version or 0)
    return {"access_token": token, "token_type": "bearer", "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60}


def _same_site_request(request: Request) -> None:
    """کوکی SameSite=Strict است؛ این هدر سفارشی هم فقط از خود سایت فرستاده می‌شود (سد دوم CSRF)."""
    origin = request.headers.get("origin")
    if request.headers.get("x-requested-with") != "pasineh" or (origin and origin.split("://", 1)[-1] != request.headers.get("host")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="درخواست از مبدأ نامعتبر است.")


@router.post('/refresh', summary="🔄 تمدید توکن دسترسی با نشست ماندگار (کوکی)")
def refresh_access_token(request: Request, response: Response, db: db_dependency,
                         refresh_token: Annotated[str | None, Cookie(alias=session_service.COOKIE_NAME)] = None):
    _same_site_request(request)
    try:
        issued = session_service.refresh(db, refresh_token)
    except session_service.SessionInvalid:
        session_service.clear_cookie(request, response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="نشست شما به پایان رسیده است؛ دوباره وارد شوید.",
                            headers={"set-cookie": response.headers.get("set-cookie", "")})
    session_service.set_cookie(request, response, issued)
    return _access(issued.user)


@router.post('/logout', status_code=status.HTTP_204_NO_CONTENT, summary="🚪 خروج و بستن نشست ماندگار این مرورگر")
def logout(request: Request, response: Response, db: db_dependency,
           refresh_token: Annotated[str | None, Cookie(alias=session_service.COOKIE_NAME)] = None):
    _same_site_request(request)
    session_service.end(db, refresh_token)
    session_service.clear_cookie(request, response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


# ---------------------------------------------------------------------------
# ورود دومرحله‌ای (TOTP) — app/core/totp.py
# ---------------------------------------------------------------------------
class MfaCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=12)


class MfaDisableIn(MfaCodeIn):
    password: str = Field(min_length=1, max_length=128)


@router.get('/mfa', summary="🛡️ وضعیت ورود دومرحله‌ای من")
def mfa_status(user: current_user_dependency):
    return {"enabled": user.totp_enabled_at is not None, "required": user_service.mfa_required(user)}


@router.post('/mfa/setup', summary="🛡️ ساخت راز و کد QR ورود دومرحله‌ای (هنوز فعال نیست)")
def mfa_setup(user: current_user_dependency, db: db_dependency, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return user_service.mfa_setup(db, user)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post('/mfa/enable', status_code=status.HTTP_204_NO_CONTENT, summary="🛡️ فعال‌سازی ورود دومرحله‌ای با اولین کد")
def mfa_enable(data: MfaCodeIn, user: current_user_dependency, db: db_dependency):
    try:
        user_service.mfa_enable(db, user, data.code)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post('/mfa/disable', status_code=status.HTTP_204_NO_CONTENT, summary="🛡️ خاموش‌کردن ورود دومرحله‌ای (با رمز و کد)")
def mfa_disable(data: MfaDisableIn, user: current_user_dependency, db: db_dependency):
    try:
        user_service.mfa_disable(db, user, data.password, data.code)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get('/sessions', summary="🖥️ نشست‌های فعال من (دستگاه‌ها)")
def my_sessions(user: current_user_dependency, db: db_dependency,
                refresh_token: Annotated[str | None, Cookie(alias=session_service.COOKIE_NAME)] = None):
    current = session_service.current_family(db, refresh_token)
    return [{"id": s.id, "created_at": s.created_at, "last_used_at": s.last_used_at, "expires_at": s.expires_at,
             "remember": s.remember, "ip": s.ip, "user_agent": s.user_agent, "current": s.family == current}
            for s in session_service.active_for(db, user)]


@router.delete('/sessions/{session_id}', status_code=status.HTTP_204_NO_CONTENT, summary="⛔ بستن یکی از نشست‌های من")
def revoke_my_session(user: current_user_dependency, db: db_dependency, session_id: int = Path(gt=0)):
    if not session_service.revoke_for(db, user, session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="نشست پیدا نشد.")


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
