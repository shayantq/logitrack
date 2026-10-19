"""اسکیماهای ثبت‌نام و احراز هویت رانندگان (لینک دعوت، پرونده، مدارک، بررسی ادمین)."""
from datetime import date, datetime
from typing import Annotated, Literal, Optional
from app.schemas.geo_fields import city_in_province

from pydantic import model_validator, AfterValidator, BaseModel, BeforeValidator, ConfigDict, EmailStr, Field, StringConstraints

from app.core.iran import normalize_digits
from app.schemas.organization import Mobile, PostalCode, Province, Text, Username
from app.schemas.user import Password

VehicleType = Literal["motorcycle", "sedan", "pickup", "van", "truck"]
DocumentKind = Literal["national_card", "selfie", "video", "driving_license", "vehicle_photo", "vehicle_card",
                       "technical_inspection"]

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _check_national_code(value: str) -> str:
    """کد ملی ۱۰ رقمی با رقم کنترل (الگوریتم رسمی ثبت احوال)."""
    if len(value) != 10 or not value.isdigit() or len(set(value)) == 1:
        raise ValueError("کد ملی باید ۱۰ رقم معتبر باشد.")
    remainder = sum(int(value[i]) * (10 - i) for i in range(9)) % 11
    check = int(value[9])
    if not ((remainder < 2 and check == remainder) or (remainder >= 2 and check == 11 - remainder)):
        raise ValueError("کد ملی نامعتبر است (رقم کنترل مطابقت ندارد).")
    return value


def _normalize_plate(value):
    """ارقام فارسی → لاتین، حذف فاصله و کلمه «ایران»؛ خط تیره قبل از کد استان حفظ می‌شود."""
    if not isinstance(value, str):
        return value
    value = value.translate(_DIGITS).replace("ایران", "-").replace(" ", "").replace("ي", "ی").replace("ك", "ک")
    while "--" in value:
        value = value.replace("--", "-")
    return value.strip("-")


NationalCode = Annotated[str, BeforeValidator(normalize_digits), AfterValidator(_check_national_code)]
# خودرو: ۱۲ب۳۴۵-۶۷   موتور: ۱۲۳-۴۵۶۷۸
Plate = Annotated[str, BeforeValidator(_normalize_plate),
                  StringConstraints(pattern=r"^(\d{2}[آ-ی]\d{3}-\d{2}|\d{3}-\d{5})$")]
CAR_PLATE = r"^\d{2}[آ-ی]\d{3}-\d{2}$"


# ---------------------------------------------------------------------------
# لینک دعوت
# ---------------------------------------------------------------------------
class DriverInviteCreate(BaseModel):
    label: Optional[Text(0, 100)] = Field(None, examples=["رانندگان قزوین"])
    expires_in_days: Optional[int] = Field(None, ge=1, le=365, examples=[30])
    max_uses: Optional[int] = Field(None, ge=1, le=10000, examples=[20])


class DriverInviteUpdate(BaseModel):
    is_active: bool


class DriverInviteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    label: Optional[str] = None
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = None
    uses: int
    is_active: bool
    is_usable: bool = False


class DriverInvitePublic(BaseModel):
    """چیزی که راننده قبل از ثبت‌نام می‌بیند — فقط نام سازمان."""
    code: str
    organization_name: str


class DriverSignupRequest(BaseModel):
    full_name: Text(3, 100) = Field(examples=["علی رضایی"])
    mobile: Mobile = Field(examples=["09121234567"])
    username: Username = Field(examples=["ali_rezaei"])
    password: Password = Field(examples=["secret123"])
    email: Optional[EmailStr] = None


class DriverSignupResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------------------------------------------------------------------------
# پرونده راننده
# ---------------------------------------------------------------------------
class DriverApplicationUpdate(BaseModel):
    """ذخیره هر مرحله از فرم — همه فیلدها اختیاری‌اند؛ کامل بودن هنگام «ارسال» بررسی می‌شود."""
    first_name: Optional[Text(2, 64)] = None
    last_name: Optional[Text(2, 64)] = None
    national_code: Optional[NationalCode] = None
    birth_date: Optional[date] = None
    mobile: Optional[Mobile] = None
    province: Optional[Province] = None
    city: Optional[Text(2, 64)] = None
    address: Optional[Text(10, 500)] = None
    postal_code: Optional[PostalCode] = None
    vehicle_type: Optional[VehicleType] = None
    vehicle_model: Optional[Text(2, 64)] = None
    vehicle_color: Optional[Text(2, 32)] = None
    license_plate: Optional[Plate] = None
    max_weight_kg: Optional[int] = Field(None, gt=0, le=40000)
    intercity: Optional[bool] = None
    inspection_expiry: Optional[date] = None

    @model_validator(mode="after")
    def _known_city(self):
        city_in_province(self, "city", "province")
        return self


class DriverDocumentInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    content_type: str
    size_bytes: int
    uploaded_at: Optional[datetime] = None


class DriverApplicationResponse(BaseModel):
    user_id: int
    username: str
    full_name: Optional[str] = None
    driver_code: Optional[str] = None
    driver_status: str
    created_at: Optional[datetime] = None

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    national_code: Optional[str] = None
    birth_date: Optional[date] = None
    mobile: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    vehicle_type: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_color: Optional[str] = None
    license_plate: Optional[str] = None
    max_weight_kg: Optional[int] = None
    intercity: bool = False
    inspection_expiry: Optional[date] = None

    submitted_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    vehicle_id: Optional[int] = None
    invite_label: Optional[str] = None

    documents: list[DriverDocumentInfo] = []
    # آنچه برای «ارسال برای بررسی» هنوز کم است (کلید فیلد یا نوع مدرک)
    missing: list[str] = []
    required_documents: list[str] = []


class DriverRejectRequest(BaseModel):
    reason: Text(3, 500) = Field(examples=["تصویر کارت ملی خوانا نیست."])
