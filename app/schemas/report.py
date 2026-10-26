"""گزارش‌ها (مرحله ۱۴)."""
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ReportRequest(BaseModel):
    report: Literal["inventory", "orders", "ledger", "finance", "reorder", "capital", "kpi", "valuation", "health", "audit"]
    format: Literal["excel", "pdf", "csv"] = "excel"
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    warehouse_id: Optional[int] = Field(None, gt=0)
    months: Optional[int] = Field(None, ge=1, le=12)        # فقط برآورد سرمایه
    status: Optional[Literal["pending", "assigned", "picking_up", "picked_up", "in_transit", "delivered", "failed", "canceled", "expired"]] = None


class FinanceKpis(BaseModel):
    trips: int
    fare: int
    company: int
    driver: int
    km: int
    avg_fare: int
    fare_per_km: int
    take_rate: float
    failed: int


class FinanceDriver(BaseModel):
    driver: str
    trips: int
    km: int
    weight: int
    fare: int
    company: int
    driver_share: int


class FinanceProvince(BaseModel):
    province: str
    trips: int
    km: int
    fare: int
    company: int


class FinanceMonth(BaseModel):
    month: str
    trips: int
    fare: int
    company: int
    driver_share: int


class FinanceDetail(BaseModel):
    day: str
    code: str
    driver: str
    plate: str
    dest: str
    km: Optional[int] = None
    level: str
    trip: Optional[int] = None
    percent: Optional[float] = None
    fare: float
    company: float
    driver_share: float
    goods: float


class FinanceSummary(BaseModel):
    start: date
    end: date
    kpis: FinanceKpis
    by_driver: list[FinanceDriver]
    by_province: list[FinanceProvince]
    by_month: list[FinanceMonth]
    details: list[FinanceDetail]
