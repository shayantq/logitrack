from pydantic import BaseModel, ConfigDict, Field, constr
from app.schemas.base import BaseModelWithDateFormatting
from datetime import datetime
from typing import Literal, Optional
from app.schemas.geo_fields import KnownCity

VehicleType = Literal["motorcycle", "sedan", "pickup", "van", "truck"]
VehicleStatus = Literal["available", "on_route", "maintenance", "inactive", "busy"]


class VehicleRequest(BaseModel):
    license_plate: constr(min_length=3, max_length=15, strip_whitespace=True) = Field(examples=['abc123'])
    vehicle_type: VehicleType = Field(examples=['van'])
    vehicle_name: Optional[str] = Field(None, examples=['پژو ۴۰۵'])
    capacity_kg: int = Field(gt=0, examples=[1500])
    # «busy» فقط توسط سیستم (هنگام تخصیص سفارش) تنظیم می‌شود
    vehicle_status: Literal["available", "on_route", "maintenance", "inactive"] = Field("available", examples=['available'])
    driver_id: int = Field(gt=0, examples=[1])
    city: Optional[KnownCity] = Field(None, examples=['تهران'])


class VehicleStatusRequest(BaseModel):
    vehicle_status: Literal["available", "on_route", "maintenance", "inactive"] = Field(examples=['available'])


class VehicleDriverRequest(BaseModel):
    driver_id: int = Field(gt=0, examples=[1])


class VehicleResponse(BaseModelWithDateFormatting):
    model_config = ConfigDict(from_attributes=True)

    id: int
    updated_at: Optional[datetime] = None
    license_plate: Optional[str] = None
    plate_number: Optional[str] = None
    type: Optional[str] = None
    model: Optional[str] = None
    capacity_kg: Optional[int] = None
    status: Optional[str] = None
    driver_id: Optional[int] = None
    city: Optional[str] = None
