from app.core.security import bcrypt_context, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from app.schemas.user import CreateUserRequest, UserResponse
from app.models import User
from app.database import db_dependency
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated
from datetime import timedelta
from starlette import status
from app.dependencies import user_dependency
from app.services import user_service
from app.services.exceptions import DomainError

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
def login_for_access_token(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: db_dependency):
    # قفل موقت پس از تلاش‌های ناموفق، حساب غیرفعال و ثبت در گزارش فعالیت — app/services/user_service.authenticate
    try:
        user = user_service.authenticate(db, form_data.username, form_data.password)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    token = create_access_token(user.username, user.id, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES), user.token_version or 0)
    return {"access_token": token, "token_type": "bearer"}
