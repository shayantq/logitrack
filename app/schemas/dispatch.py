"""اسکیماهای زمان‌بندی رانندگان و پیشنهاد هوشمند راننده برای سفارش (مرحله ۷)."""
from datetime import date, datetime, time
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.schemas.order import CityName
from app.schemas.organization import Province, Text

EmploymentType = Literal["full_time", "part_time"]


class ShiftIn(BaseModel):
    weekday: int = Field(ge=0, le=6, description="دوشنبه=۰ ... یکشنبه=۶ (شنبه=۵)")
    start_time: time = Field(examples=["08:00"])
    end_time: time = Field(examples=["17:00"])

    @model_validator(mode="after")
    def check(self):
        if self.end_time <= self.start_time:
            raise ValueError("پایان شیفت باید بعد از شروع آن باشد (شیفت شبانه را دو بخش کنید).")
        return self


class ShiftOut(ShiftIn):
    id: int


class ScheduleUpdate(BaseModel):
    employment_type: EmploymentType = "full_time"
    max_daily_orders: Optional[int] = Field(None, ge=1, le=50)
    intercity: bool = False
    shifts: list[ShiftIn] = Field(default_factory=list, max_length=21)

    @model_validator(mode="after")
    def no_overlap(self):
        by_day: dict[int, list[ShiftIn]] = {}
        for s in self.shifts:
            by_day.setdefault(s.weekday, []).append(s)
        for items in by_day.values():
            items.sort(key=lambda s: s.start_time)
            for a, b in zip(items, items[1:], strict=False):
                if b.start_time < a.end_time:
                    raise ValueError("شیفت‌های یک روز نباید هم‌پوشانی داشته باشند.")
        return self


class TimeOffCreate(BaseModel):
    starts_at: datetime = Field(examples=["2026-10-14T00:00:00+03:30"])
    ends_at: datetime = Field(examples=["2026-10-16T00:00:00+03:30"])
    reason: Optional[Text(0, 200)] = Field(None, examples=["مرخصی"])

    @model_validator(mode="after")
    def check(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("پایان مرخصی باید بعد از شروع آن باشد.")
        return self


class TimeOffOut(BaseModel):
    id: int
    starts_at: datetime
    ends_at: datetime
    reason: Optional[str] = None


class ScheduleVehicle(BaseModel):
    id: int
    license_plate: Optional[str] = None
    type: Optional[str] = None
    model: Optional[str] = None
    capacity_kg: Optional[int] = None
    status: Optional[str] = None


class DayLoad(BaseModel):
    date: date
    orders: int
    load_kg: float
    shifts: list[str]          # «۰۸:۰۰–۱۷:۰۰»
    off: bool                  # مرخصی در این روز


class DriverScheduleResponse(BaseModel):
    driver_id: int
    driver_name: str
    driver_code: Optional[str] = None
    driver_status: str
    city: Optional[str] = None
    employment_type: EmploymentType
    max_daily_orders: Optional[int] = None
    intercity: bool
    vehicle: Optional[ScheduleVehicle] = None
    shifts: list[ShiftOut]
    time_off: list[TimeOffOut]
    day: DayLoad


class SuggestRequest(BaseModel):
    total_weight_kg: float = Field(gt=0, examples=[150])
    delivery_window_start: datetime = Field(examples=["2026-10-14T10:00:00+03:30"])
    delivery_window_end: datetime = Field(examples=["2026-10-14T12:00:00+03:30"])
    destination_city: CityName = Field(examples=["قزوین"])
    destination_province: Optional[Province] = None

    @model_validator(mode="after")
    def check(self):
        if self.delivery_window_end <= self.delivery_window_start:
            raise ValueError("پایان بازه تحویل باید بعد از شروع آن باشد.")
        return self


class Candidate(BaseModel):
    vehicle_id: int
    license_plate: Optional[str] = None
    vehicle_type: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_status: Optional[str] = None
    capacity_kg: Optional[int] = None
    city: Optional[str] = None
    driver_id: Optional[int] = None
    driver_name: Optional[str] = None
    driver_code: Optional[str] = None
    score: float
    reasons: list[str]
    reason: Optional[str] = None      # دلیل کنار گذاشته شدن
    load_kg: float
    free_kg: float
    day_orders: int
    same_city: bool
    has_schedule: bool


class SuggestResponse(BaseModel):
    candidates: list[Candidate]
    excluded: list[Candidate]


class MyScheduleResponse(BaseModel):
    employment_type: EmploymentType
    max_daily_orders: Optional[int] = None
    intercity: bool
    shifts: list[ShiftOut]
    time_off: list[TimeOffOut]
