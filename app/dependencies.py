from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.security import SECRET_KEY, ALGORITHM
from app.core.tenancy import set_tenant
from app.database import get_db
from app.models import User, RoleEnum, PLATFORM_ROLES

# نکته: با توجه به روتر auth شما، آدرس توکن برابر با /auth/token است
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


# ------------------------------------------------------------------------------
# ۱. واکشی و تایید هویت کاربر جاری از روی توکن JWT
# ------------------------------------------------------------------------------
def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    هر کاربر لاگین‌کرده (سازمانی یا کارکنان پلتفرم). برای کاربر سازمانی،
    «سازمان جاری» Session همین درخواست تنظیم می‌شود تا همه کوئری‌ها
    خودکار به داده‌های همان سازمان محدود شوند (app/core/tenancy.py).
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="توکن نامعتبر است یا منقضی شده؛ لطفاً دوباره وارد شوید.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    # رمز بازنشانی/عوض شده یا حساب غیرفعال شده ← توکن‌های قبلی دیگر معتبر نیستند
    if int(payload.get("tv", 0) or 0) != (user.token_version or 0):
        raise credentials_exception
    if user.is_active is False:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="حساب کاربری شما غیرفعال شده است؛ با ادمین سازمان تماس بگیرید.",
                            headers={"WWW-Authenticate": "Bearer"})

    if user.organization_id is not None:
        if user.organization is None or not user.organization.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="حساب سازمان شما غیرفعال شده است؛ با پشتیبانی LogiTrack تماس بگیرید.",
            )
        set_tenant(db, user.organization_id)
    else:
        set_tenant(db, None)

    return user


def get_tenant_user(current_user: User = Depends(get_current_user)) -> User:
    """فقط کاربران یک سازمان — همه APIهای عملیاتی (سفارش، انبار، ناوگان، ...) از این استفاده می‌کنند."""
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="این بخش مخصوص کاربران سازمان‌هاست؛ کارکنان پلتفرم از پنل پلتفرم استفاده کنند.",
        )
    return current_user


# هر کاربر لاگین‌کرده (برای /users/me)
current_user_dependency = Annotated[User, Depends(get_current_user)]
# کاربر یک سازمان — پیش‌فرض همه روترهای عملیاتی
user_dependency = Annotated[User, Depends(get_tenant_user)]


# ------------------------------------------------------------------------------
# ۲. کنترل سطح دسترسی بر اساس نقش‌ها (RBAC Guard)
# ------------------------------------------------------------------------------
def require_role(allowed_roles: list[RoleEnum]):
    platform_only = all(r in PLATFORM_ROLES for r in allowed_roles)
    base_dependency = get_current_user if platform_only else get_tenant_user

    def role_checker(current_user: User = Depends(base_dependency)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"دسترسی غیرمجاز! این عملیات فقط برای نقش‌های {[r.value for r in allowed_roles]} مجاز است."
            )
        return current_user

    return role_checker
