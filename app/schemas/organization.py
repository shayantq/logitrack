from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import (
    AfterValidator, BaseModel, BeforeValidator, ConfigDict, EmailStr, Field, StringConstraints, model_validator,
)

from app.core.iran import PROVINCES, normalize_digits, normalize_persian_text
from app.schemas.geo_fields import city_in_province
from app.schemas.user import Password

# اول کوچک/تمیز می‌شود، بعد الگو بررسی می‌شود (مثلاً «Qazvin-Shop» → «qazvin-shop»)
Slug = Annotated[
    str,
    BeforeValidator(lambda v: v.strip().lower() if isinstance(v, str) else v),
    StringConstraints(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$"),
]
Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=20)]

# ---------------------------------------------------------------------------
# فیلدهای پروفایل — ارقام فارسی خودکار به لاتین تبدیل می‌شوند
# ---------------------------------------------------------------------------
BusinessType = Literal["retail", "ecommerce", "wholesale", "warehouse_3pl", "manufacturing", "healthcare", "food", "other"]
EmployeeRange = Literal["1-10", "11-50", "51-200", "201-1000", "1000+"]
OrderVolume = Literal["<100", "100-1000", "1000-10000", "10000+"]
Feature = Literal["transport", "warehouse", "stocktaking", "accounting", "reports", "api"]
# «چطور با ما آشنا شدید؟»
ReferralSource = Literal["search", "instagram", "linkedin", "telegram", "referral", "event", "ads", "other"]


def _digits(pattern: str, max_length: int):
    return Annotated[str, BeforeValidator(normalize_digits), StringConstraints(max_length=max_length, pattern=pattern)]


def _check_province(value: str) -> str:
    if value not in PROVINCES:
        raise ValueError("استان انتخاب‌شده معتبر نیست.")
    return value


Text = lambda min_len, max_len: Annotated[  # noqa: E731
    str, BeforeValidator(normalize_persian_text), StringConstraints(min_length=min_len, max_length=max_len)
]

NationalId = _digits(r"^\d{11}$", 11)            # شناسه ملی ۱۱ رقمی اشخاص حقوقی
EconomicCode = _digits(r"^\d{11,14}$", 14)        # کد اقتصادی (۱۱ تا ۱۴ رقم)
PostalCode = _digits(r"^\d{10}$", 10)
Phone = _digits(r"^0\d{9,10}$", 20)               # تلفن ثابت با کد شهر
Mobile = _digits(r"^09\d{9}$", 11)
Province = Annotated[str, BeforeValidator(normalize_persian_text), AfterValidator(_check_province)]


class OrganizationProfileFields(BaseModel):
    """همه فیلدهای پروفایل، اختیاری — پایه ویرایش پروفایل و پاسخ‌ها."""
    legal_name: Optional[Text(2, 200)] = None
    business_type: Optional[BusinessType] = None
    national_id: Optional[NationalId] = None
    economic_code: Optional[EconomicCode] = None
    registration_number: Optional[_digits(r"^\d{1,32}$", 32)] = None
    province: Optional[Province] = None
    city: Optional[Text(2, 64)] = None
    address: Optional[Text(10, 500)] = None
    postal_code: Optional[PostalCode] = None
    phone: Optional[Phone] = None
    website: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]] = None
    employee_count: Optional[EmployeeRange] = None
    monthly_order_volume: Optional[OrderVolume] = None
    warehouse_count: Optional[int] = Field(None, ge=0, le=10000)
    fleet_size: Optional[int] = Field(None, ge=0, le=100000)
    contact_name: Optional[Text(2, 100)] = None
    contact_mobile: Optional[Mobile] = None
    contact_email: Optional[EmailStr] = None

    @model_validator(mode="after")
    def _known_city(self):
        city_in_province(self, "city", "province")
        return self


# ---------------------------------------------------------------------------
# درخواست عمومی از لندینگ پیج
# ---------------------------------------------------------------------------
class OrganizationRequestCreate(OrganizationProfileFields):
    name: Text(2, 200) = Field(examples=['فروشگاه نمونه قزوین'])
    legal_name: Text(2, 200)
    business_type: BusinessType
    national_id: NationalId = Field(examples=['10101234567'])
    province: Province = Field(examples=['قزوین'])
    city: Text(2, 64)
    address: Text(10, 500)
    employee_count: EmployeeRange
    monthly_order_volume: OrderVolume
    requested_features: list[Feature] = Field(min_length=1, examples=[['transport', 'warehouse']])
    contact_name: Text(2, 100)
    contact_mobile: Mobile = Field(examples=['09121234567'])
    contact_email: EmailStr
    notes: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]] = None
    # اختیاری؛ اگر «سایر» انتخاب شود، توضیح (از کجا آشنا شده) الزامی است
    referral_source: Optional[ReferralSource] = None
    referral_detail: Optional[Text(0, 200)] = None
    # فیلد تله برای ربات‌ها (در فرم مخفی است؛ انسان آن را پر نمی‌کند)
    company_fax: Optional[str] = Field(None, exclude=True)

    @model_validator(mode="after")
    def _referral(self):
        detail = (self.referral_detail or "").strip() or None
        if self.referral_source is None:
            detail = None                      # بدون انتخاب، توضیح هم ذخیره نمی‌شود
        elif self.referral_source == "other" and (detail is None or len(detail) < 2):
            raise ValueError("لطفاً بنویسید از کجا با ما آشنا شدید.")
        self.referral_detail = detail
        return self


class OrganizationRequestSubmitted(BaseModel):
    tracking_code: str
    message: str


class OrganizationRequestPublicStatus(BaseModel):
    """چیزی که متقاضی با کد پیگیری می‌بیند — بدون اطلاعات داخلی."""
    model_config = ConfigDict(from_attributes=True)

    tracking_code: str
    name: str
    status: str
    created_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None


class OrganizationRequestResponse(OrganizationProfileFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tracking_code: str
    name: str
    status: str
    requested_features: list[str] = []
    notes: Optional[str] = None
    referral_source: Optional[str] = None
    referral_detail: Optional[str] = None
    created_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    reviewed_by_id: Optional[int] = None
    rejection_reason: Optional[str] = None
    organization_id: Optional[int] = None
    # برای نمایش؛ مقادیر قدیمی‌تر ممکن است با اعتبارسنجی جدید نخوانند
    contact_email: Optional[str] = None


class OrganizationRequestApprove(BaseModel):
    slug: Slug = Field(examples=['qazvin-shop'])
    admin_username: Optional[Username] = None
    # اگر خالی باشد ایمیل مسئول تماس درخواست استفاده می‌شود
    admin_email: Optional[EmailStr] = None
    # اگر خالی باشد یک رمز موقت تصادفی ساخته و یک‌بار نمایش داده می‌شود
    admin_password: Optional[Password] = None


class OrganizationRequestReject(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]


# ---------------------------------------------------------------------------
# ساخت مستقیم سازمان توسط ادمین پلتفرم
# ---------------------------------------------------------------------------
class OrganizationAdminCreate(BaseModel):
    """اولین ادمین سازمان که همراه خود سازمان ساخته می‌شود."""
    username: Username
    email: EmailStr
    password: Password
    full_name: Optional[str] = None


class OrganizationCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)] = Field(examples=['فروشگاه نمونه قزوین'])
    slug: Slug = Field(examples=['qazvin-shop'])
    admin: OrganizationAdminCreate


class OrganizationUpdate(BaseModel):
    name: Optional[Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]] = None
    is_active: Optional[bool] = None


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    is_active: bool
    created_at: Optional[datetime] = None


class OrganizationStats(OrganizationResponse):
    users_count: int = 0
    drivers_count: int = 0
    warehouses_count: int = 0
    products_count: int = 0
    vehicles_count: int = 0
    orders_count: int = 0
    active_orders_count: int = 0


class OrganizationApproved(BaseModel):
    organization: OrganizationStats
    admin_username: str
    # فقط وقتی رمز توسط سیستم ساخته شده باشد (یک‌بار نمایش)
    temporary_password: Optional[str] = None


# ---------------------------------------------------------------------------
# پروفایل سازمان (برای ادمین سازمان و کارکنان پلتفرم)
# ---------------------------------------------------------------------------
class OrganizationProfileUpdate(OrganizationProfileFields):
    name: Optional[Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]] = None
    # رنگ سازمان در گزارش‌ها (هگز شش‌رقمی)
    brand_color: Optional[Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^#[0-9A-Fa-f]{6}$")]] = None


class OrganizationProfileResponse(OrganizationProfileFields):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    has_logo: bool = False
    brand_color: Optional[str] = None
    # داده‌های قبلی ممکن است با اعتبارسنجی جدید نخوانند؛ در پاسخ سخت‌گیری نمی‌کنیم
    contact_email: Optional[str] = None
    province: Optional[str] = None
