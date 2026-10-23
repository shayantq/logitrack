"""طرف‌های تجاری: تأمین‌کننده، مشتری (حقوقی/عمده) و شرکت حمل — با اعتبارسنجی ساختاری شناسه‌ها."""
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import AfterValidator, BaseModel, BeforeValidator, EmailStr, Field, StringConstraints, model_validator

from app.core.iran import normalize_digits
from app.core.wms import CARRIER_SERVICES, PARTNER_KINDS
from app.schemas.geo_fields import city_in_province
from app.schemas.organization import Province
from app.schemas.route import City

Str = lambda n: Annotated[str, StringConstraints(strip_whitespace=True, max_length=n)]  # noqa: E731


def _national_code_ok(value: str) -> bool:
    """کد ملی ۱۰ رقمی اشخاص حقیقی (الگوریتم رسمی ثبت احوال)."""
    if len(value) != 10 or len(set(value)) == 1:
        return False
    remainder = sum(int(value[i]) * (10 - i) for i in range(9)) % 11
    check = int(value[9])
    return check == remainder if remainder < 2 else check == 11 - remainder


def _legal_id_ok(value: str) -> bool:
    """شناسه ملی ۱۱ رقمی اشخاص حقوقی (رقم کنترل با ضرایب ۲۹،۲۷،۲۳،۱۹،۱۷ و رقم دهگان)."""
    if len(value) != 11:
        return False
    tens = int(value[9]) + 2
    weights = (29, 27, 23, 19, 17, 29, 27, 23, 19, 17)
    total = sum((int(value[i]) + tens) * weights[i] for i in range(10)) % 11
    return int(value[10]) == (0 if total == 10 else total)


def _iban(value: str) -> str:
    """شماره شبا: IR + ۲۴ رقم با کنترل mod-97 (ISO 13616)."""
    value = value.replace(" ", "").replace("-", "").upper()
    if not value.startswith("IR"):
        value = "IR" + value
    if len(value) != 26 or not value[2:].isdigit():
        raise ValueError("شماره شبا باید IR و ۲۴ رقم باشد.")
    rearranged = value[4:] + "1827" + value[2:4]          # I=18, R=27
    if int(rearranged) % 97 != 1:
        raise ValueError("شماره شبا نامعتبر است (رقم کنترل مطابقت ندارد).")
    return value


def _digits(n_min: int, n_max: int, label: str):
    def check(value: str) -> str:
        if not value.isdigit() or not (n_min <= len(value) <= n_max):
            raise ValueError(f"{label} باید {n_min if n_min == n_max else f'{n_min} تا {n_max}'} رقم باشد.")
        return value
    return check


def _mobile(value: str) -> str:
    if not (len(value) == 11 and value.startswith("09") and value.isdigit()):
        raise ValueError("شماره همراه باید ۱۱ رقم و با ۰۹ شروع شود.")
    return value


def _tracking_url(value: str) -> str:
    if not value.startswith("https://") or "{code}" not in value:
        raise ValueError("لینک رهگیری باید با https:// شروع شود و {code} (جای کد مرسوله) را داشته باشد.")
    return value


Digits = lambda a, b, label: Annotated[str, BeforeValidator(normalize_digits), AfterValidator(_digits(a, b, label))]  # noqa: E731
Mobile = Annotated[str, BeforeValidator(normalize_digits), AfterValidator(_mobile)]
Iban = Annotated[str, BeforeValidator(normalize_digits), AfterValidator(_iban)]
PartnerCode = Annotated[str, BeforeValidator(lambda v: v.strip().upper() if isinstance(v, str) else v),
                        StringConstraints(min_length=2, max_length=16, pattern=r"^[A-Z0-9][A-Z0-9-]*$")]


class PartnerIn(BaseModel):
    code: Optional[PartnerCode] = None                 # خالی = ساخت خودکار (SUP-001، CUS-001، CAR-001)
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
    kind: Literal[PARTNER_KINDS] = "legal"
    is_supplier: bool = False
    is_customer: bool = False
    is_carrier: bool = False
    legal_name: Optional[Str(200)] = None
    national_id: Optional[Annotated[str, BeforeValidator(normalize_digits)]] = None
    economic_code: Optional[Digits(12, 14, "کد اقتصادی")] = None
    registration_number: Optional[Digits(1, 32, "شماره ثبت")] = None
    phone: Optional[Digits(8, 12, "تلفن")] = None
    mobile: Optional[Mobile] = None
    email: Optional[EmailStr] = None
    website: Optional[Str(200)] = None
    province: Optional[Province] = None
    city: Optional[City] = None
    address: Optional[Str(500)] = None
    postal_code: Optional[Digits(10, 10, "کد پستی")] = None
    contact_name: Optional[Str(100)] = None
    contact_mobile: Optional[Mobile] = None
    iban: Optional[Iban] = None
    payment_terms_days: Optional[int] = Field(None, ge=0, le=365)
    lead_time_days: Optional[int] = Field(None, ge=0, le=365)
    carrier_service: Optional[Literal[CARRIER_SERVICES]] = None
    tracking_url: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=300), AfterValidator(_tracking_url)]] = None
    notes: Optional[Str(2000)] = None

    @model_validator(mode="after")
    def _rules(self):
        if not (self.is_supplier or self.is_customer or self.is_carrier):
            raise ValueError("دست‌کم یک نقش (تأمین‌کننده، مشتری یا شرکت حمل) را انتخاب کنید.")
        if self.national_id:
            ok = _legal_id_ok(self.national_id) if self.kind == "legal" else _national_code_ok(self.national_id)
            if not ok:
                raise ValueError("شناسه ملی (۱۱ رقم) نامعتبر است." if self.kind == "legal" else "کد ملی (۱۰ رقم) نامعتبر است.")
        if self.city and not self.province:
            raise ValueError("برای انتخاب شهر، استان را هم مشخص کنید.")
        if self.city:
            city_in_province(self, "city", "province")
        if not self.is_carrier:
            self.carrier_service = self.tracking_url = None
        if not self.is_supplier:
            self.lead_time_days = None
        return self


class PartnerOut(BaseModel):
    id: int
    code: str
    name: str
    kind: str
    is_supplier: bool
    is_customer: bool
    is_carrier: bool
    roles: list[str]
    legal_name: Optional[str] = None
    national_id: Optional[str] = None       # برای غیرادمین پوشانده می‌شود
    economic_code: Optional[str] = None
    registration_number: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    contact_name: Optional[str] = None
    contact_mobile: Optional[str] = None
    iban: Optional[str] = None              # برای غیرادمین پوشانده می‌شود
    payment_terms_days: Optional[int] = None
    lead_time_days: Optional[int] = None
    carrier_service: Optional[str] = None
    tracking_url: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool
    masked: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    products_count: int = 0
    documents_count: int = 0
