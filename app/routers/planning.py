"""درخواست خرید، مقایسه انبارها و تیم‌ها، و نمای ظرفیت."""
from datetime import date, datetime
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, StringConstraints

from app.database import db_dependency
from app.dependencies import user_dependency
from app.services import planning_service, purchase_request_service
from app.services.exceptions import DomainError

purchase = APIRouter(prefix="/purchase-requests", tags=["🛒 درخواست خرید"])
planning = APIRouter(prefix="/planning", tags=["📐 مقایسه و ظرفیت"])
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


class PurchaseLineIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=10_000_000)


class PurchaseRequestIn(BaseModel):
    warehouse_id: Optional[int] = Field(None, gt=0)
    note: Optional[Note] = None
    lines: list[PurchaseLineIn] = Field(min_length=1, max_length=100)


class PurchaseDecisionIn(BaseModel):
    approve: bool
    note: Optional[Note] = None


class PurchaseCancelIn(BaseModel):
    note: Optional[Note] = None


class PurchaseLineOut(BaseModel):
    product_id: Optional[int] = None
    product_name: str
    quantity: int
    estimated_unit_cost: Optional[float] = None


class PurchaseEventOut(BaseModel):
    action: str
    action_label: str
    note: Optional[str] = None
    actor: Optional[str] = None
    at: datetime


class PurchaseRequestOut(BaseModel):
    id: int
    code: str
    warehouse_id: int
    warehouse_name: Optional[str] = None
    status: str
    status_label: str
    note: Optional[str] = None
    requested_by_id: Optional[int] = None
    requested_by: Optional[str] = None
    created_at: datetime
    estimated_total: Optional[int] = None
    estimate_complete: bool
    lines: list[PurchaseLineOut]
    events: list[PurchaseEventOut]


@purchase.get("/", response_model=list[PurchaseRequestOut], summary="📋 درخواست‌های خرید")
def list_requests(db: db_dependency, user: user_dependency, status_: Optional[Literal["pending", "approved", "rejected", "canceled"]] = Query(None, alias="status")):
    return _call(purchase_request_service.list_requests, db, user, status_)


@purchase.post("/", response_model=PurchaseRequestOut, status_code=status.HTTP_201_CREATED, summary="➕ درخواست خرید تازه")
def create_request(data: PurchaseRequestIn, db: db_dependency, user: user_dependency):
    return _call(purchase_request_service.create, db, user, data)


@purchase.post("/{request_id}/decide", response_model=PurchaseRequestOut, summary="✅ تأیید یا رد (ادمین سازمان، غیر از درخواست‌دهنده)")
def decide_request(data: PurchaseDecisionIn, db: db_dependency, user: user_dependency, request_id: int = Path(gt=0)):
    return _call(purchase_request_service.decide, db, user, request_id, data.approve, data.note)


@purchase.post("/{request_id}/cancel", response_model=PurchaseRequestOut, summary="✖️ لغو درخواست منتظر تصمیم")
def cancel_request(data: PurchaseCancelIn, db: db_dependency, user: user_dependency, request_id: int = Path(gt=0)):
    return _call(purchase_request_service.cancel, db, user, request_id, data.note)


class MetricOut(BaseModel):
    key: str
    label: str
    unit: str
    definition: str
    target: float
    higher_better: bool


class MetricValueOut(BaseModel):
    value: Optional[float] = None
    status: str
    detail: Optional[str] = None
    insufficient: bool


class WarehouseRowOut(BaseModel):
    warehouse_id: int
    name: str
    values: dict[str, MetricValueOut]
    link: str


class TeamRowOut(BaseModel):
    team: str
    label: str
    opened: int
    closed: int
    open_now: int
    overdue_now: int
    avg_close_hours: Optional[float] = None
    link: str


class ComparisonOut(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    generated_at: datetime
    metrics: list[MetricOut]
    warehouses: list[WarehouseRowOut]
    teams: list[TeamRowOut]
    notes: list[str]


class VehicleLoadOut(BaseModel):
    vehicle_id: int
    plate: str
    orders: int
    weight_kg: float
    max_weight_kg: Optional[float] = None
    weight_pct: Optional[float] = None
    volume_m3: Optional[float] = None
    max_volume_m3: Optional[float] = None
    volume_pct: Optional[float] = None
    over: bool


class DriverLoadOut(BaseModel):
    driver_id: int
    name: str
    orders: int
    max_daily_orders: Optional[int] = None
    over: bool
    time_off: bool


class FullLocationOut(BaseModel):
    location_id: int
    code: str
    weight_kg: float
    max_weight_kg: Optional[float] = None
    volume_m3: float
    max_volume_m3: Optional[float] = None


class WorkloadOut(BaseModel):
    key: str
    label: str
    count: int


class CapacityWarningOut(BaseModel):
    kind: str
    severity: str
    text: str
    link: str


class CapacityOut(BaseModel):
    day: date
    generated_at: datetime
    orders: int
    unassigned_orders: int
    vehicles: list[VehicleLoadOut]
    drivers: list[DriverLoadOut]
    full_locations: list[FullLocationOut]
    workload: list[WorkloadOut]
    warnings: list[CapacityWarningOut]
    assumptions: list[str]


@planning.get("/comparison", response_model=ComparisonOut, summary="📊 مقایسه انبارها و تیم‌ها")
def comparison(db: db_dependency, user: user_dependency, date_from: Optional[date] = None, date_to: Optional[date] = None):
    return _call(planning_service.comparison, db, user, date_from, date_to)


@planning.get("/capacity", response_model=CapacityOut, summary="📐 نمای ظرفیت یک روز (فقط‌خواندنی)")
def capacity(db: db_dependency, user: user_dependency, day: date):
    return _call(planning_service.capacity, db, user, day)
