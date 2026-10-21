from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, constr, EmailStr
from typing import Annotated, Any, Literal, Optional
from app.schemas.geo_fields import KnownCity


# رمز عبور trim نمی‌شود (فاصله بخشی از رمز است). سقف ۷۲ کاراکتر محدودیت خود bcrypt است.
Password = Annotated[str, StringConstraints(min_length=6, max_length=72)]
# نقش‌هایی که ادمین سازمان می‌تواند بسازد (نقش‌های پلتفرم فقط توسط اسکریپت create_admin.py)
TenantRole = Literal["org_admin", "warehouse_manager", "driver"]


class CreateUserRequest(BaseModel):
    username: constr(min_length=3, max_length=20, strip_whitespace=True) = Field(examples=['john_doe'])
    email: EmailStr = Field(examples=['john_doe@example.com'])
    role: TenantRole = Field(examples=['driver'])
    password: Password = Field(examples=['secret123'])
    city: Optional[KnownCity] = Field(None, examples=['تهران'])
    warehouse_id: Optional[int] = Field(None, gt=0, examples=[1])
    full_name: Optional[str] = Field(None, examples=['علی رضایی'])
    mobile: Optional[Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^09\d{9}$")]] = None
    # کاربر در اولین ورود باید رمز را عوض کند (ادمین رمز را می‌داند)
    must_change_password: bool = False


class UserUpdateRequest(BaseModel):
    """ویرایش کاربر توسط ادمین سازمان؛ نام کاربری (شناسه ورود) عوض نمی‌شود."""
    full_name: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=150)]] = None
    email: Optional[EmailStr] = None
    mobile: Optional[Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^(09\d{9})?$")]] = None
    role: Optional[TenantRole] = None
    city: Optional[KnownCity] = None
    warehouse_id: Optional[int] = Field(None, gt=0)


class UpdateUserRequest(BaseModel):
    old_password: Password = Field(examples=['old_password'])
    new_password: Password = Field(examples=['new_password'])


class UpdateRoleRequest(BaseModel):
    role: TenantRole = Field(examples=['driver'])


class PasswordRequest(BaseModel):
    password: Password = Field(examples=['secret123'])


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: Optional[str] = None
    role: str
    city: Optional[str] = None
    warehouse_id: Optional[int] = None
    full_name: Optional[str] = None
    driver_code: Optional[str] = None
    organization_id: Optional[int] = None
    # فقط برای رانندگان معنا دارد: incomplete / submitted / approved / rejected
    driver_status: Optional[str] = None
    mobile: Optional[str] = None
    is_active: bool = True
    must_change_password: bool = False
    locked_until: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class PasswordResetResponse(BaseModel):
    user: UserResponse
    temporary_password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserStats(BaseModel):
    logins_30d: int
    failed_logins_30d: int
    order_actions: int
    stock_movements: int
    deliveries: int
    history: int


class UserDetailResponse(BaseModel):
    user: UserResponse
    stats: UserStats


class ActivityItem(BaseModel):
    at: Optional[datetime] = None
    kind: str
    category: str
    action: str
    title: str
    detail: Optional[str] = None
    order_id: Optional[int] = None
    ip: Optional[str] = None


class AuditLogItem(BaseModel):
    id: int
    at: datetime
    actor_id: Optional[int] = None
    actor_name: Optional[str] = None
    action: str
    category: str
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    target_label: Optional[str] = None
    summary: str
    details: Optional[dict[str, Any]] = None
    ip: Optional[str] = None
    user_agent: Optional[str] = None


class AuditLogPage(BaseModel):
    total: int
    items: list[AuditLogItem]
    categories: dict[str, str]


class OrganizationBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str


class MeResponse(UserResponse):
    """کاربر جاری به‌همراه سازمانش (برای نمایش نام سازمان در پنل‌ها)."""
    organization: Optional[OrganizationBrief] = None
    # راهنمای تعاملی: {"<شناسه راهنما>": "done" | "skipped"} — راهنمایی که اینجا نیست، بار اول خودکار باز می‌شود
    tour_state: Optional[dict[str, str]] = None


class TourStateIn(BaseModel):
    state: Literal["done", "skipped"]


class PasswordResetChannels(BaseModel):
    sms: bool
    email: bool


class PasswordResetRequestIn(BaseModel):
    identifier: constr(min_length=3, max_length=254, strip_whitespace=True) = Field(examples=['09121234567'])


class PasswordResetConfirmIn(BaseModel):
    identifier: constr(min_length=3, max_length=254, strip_whitespace=True)
    code: constr(min_length=4, max_length=12, strip_whitespace=True) = Field(examples=['123456'])
    new_password: Password


class MessageResponse(BaseModel):
    message: str
