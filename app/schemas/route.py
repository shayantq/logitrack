"""مسیر سفارش روی نقشه ایران، گزارش موقعیت راننده و انبارها (مرحله ۱۰)."""
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import model_validator, BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from app.core.iran import normalize_persian_text
from app.core.wms import WAREHOUSE_TYPES
from app.schemas.geo_fields import city_in_province
from app.schemas.organization import Province


class RoutePoint(BaseModel):
    seq: int
    city: str
    label: str                 # نام نمایشی (اگر شهر مقصد در فهرست نباشد، همان نامی که در سفارش آمده)
    province: str
    lat: float
    lon: float
    km: int                    # کیلومتر تجمعی از مبدأ
    approx: bool = False       # نقطه به مرکز استان نگاشت شده است


class LastReport(BaseModel):
    seq: int
    city: str
    at: datetime


class RouteProgress(BaseModel):
    fraction: float = Field(description="۰ تا ۱")
    km_done: int
    remaining_km: Optional[int] = None
    passed_seq: int = Field(description="آخرین شهری که رد شده (-۱ = هنوز حرکت نکرده)")
    next_seq: Optional[int] = None
    estimated: bool = Field(description="بخشی از پیشرفت با زمان تخمین زده شده (نه گزارش راننده)")
    eta: Optional[datetime] = None
    last_report: Optional[LastReport] = None


class CheckpointOut(BaseModel):
    seq: int
    city: str
    reached_at: datetime
    reported_by: Optional[str] = None


class OrderRoute(BaseModel):
    order_id: int
    tracking_code: str
    status: str
    available: bool
    reason: Optional[str] = None
    frozen: bool = False
    total_km: Optional[int] = None
    points: list[RoutePoint] = []
    warehouse_name: Optional[str] = None
    departed_at: Optional[datetime] = None
    progress: RouteProgress
    checkpoints: list[CheckpointOut] = []
    speed_kmh: int


class MapOrder(OrderRoute):
    priority: bool = False
    destination_city: Optional[str] = None
    destination_province: Optional[str] = None
    delivery_window_start: Optional[datetime] = None
    delivery_window_end: Optional[datetime] = None
    driver_name: Optional[str] = None
    plate: Optional[str] = None


class MapOrders(BaseModel):
    orders: list[MapOrder]
    unmapped: int = Field(description="سفارش‌هایی که مبدأ یا مقصدشان روی نقشه معلوم نیست")
    speed_kmh: int


class PublicRoute(BaseModel):
    """نسخه عمومی مسیر برای صفحه پیگیری مشتری (بدون نام گزارش‌دهنده)."""
    available: bool
    total_km: Optional[int] = None
    points: list[RoutePoint] = []
    progress: RouteProgress
    checkpoints: list[CheckpointOut] = []


class CheckpointIn(BaseModel):
    seq: int = Field(ge=1, description="شماره شهر در مسیر (مبدأ = ۰)")


MapScope = Literal["active", "in_transit", "today"]


# ---------------------------------------------------------------------------
# انبارها
# ---------------------------------------------------------------------------
City = Annotated[str, BeforeValidator(lambda v: normalize_persian_text(v) if isinstance(v, str) else v),
                 StringConstraints(min_length=2, max_length=64)]


class WarehouseIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
    province: Province
    city: City
    location: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]] = None
    # کد یکتا در سازمان (خالی = ساخت خودکار WH-01، WH-02، ...)؛ نوع و انبار مادر (app/core/wms.WAREHOUSE_TYPES)
    code: Optional[Annotated[str, BeforeValidator(lambda v: v.strip().upper() if isinstance(v, str) else v),
                             StringConstraints(min_length=2, max_length=16, pattern=r"^[A-Z0-9][A-Z0-9-]*$")]] = None
    type: Literal[tuple(WAREHOUSE_TYPES)] = "general"
    parent_id: Optional[int] = Field(None, gt=0)
    is_active: bool = True

    @model_validator(mode="after")
    def _known_city(self):
        city_in_province(self, "city", "province")
        return self


class WarehouseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    location: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    on_map: bool = False            # شهرش روی نقشه شناخته می‌شود
    map_city: Optional[str] = None  # نقطه‌ای که روی نقشه برای آن استفاده می‌شود
    products_count: int = 0
    managers_count: int = 0
    code: str = ""
    type: str = "general"
    type_label: str = ""
    parent_id: Optional[int] = None
    parent_name: Optional[str] = None
    depth: int = 0
    is_active: bool = True
    holds_stock: bool = True
    ships_orders: bool = True
    on_hand: int = 0


class GeoCity(BaseModel):
    name: str
    province: str
    capital: bool
