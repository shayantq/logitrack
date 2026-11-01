"""خروجی صفحه خانه نقش‌ها (app/services/home_service.py)."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class HomeKpi(BaseModel):
    key: str
    label: str
    value: Optional[float] = None
    previous: Optional[float] = None
    unit: str
    target: float
    status: str
    hint: str
    higher_better: bool
    link: str


class DelayCause(BaseModel):
    key: str
    label: str
    count: int
    link: str


class DelaySummary(BaseModel):
    late: int
    at_risk: int
    causes: list[DelayCause]


class ExceptionSummary(BaseModel):
    critical: int
    high: int
    link: str


class StockSummary(BaseModel):
    out: int
    low: int
    link: str


class MarginProduct(BaseModel):
    product_id: int
    name: str
    margin: int


class MoneyEstimate(BaseModel):
    estimated: bool
    window_days: int
    trips: int
    fare: int
    driver_share: int
    company_share: int
    goods_sales: int
    goods_margin: int
    cost_coverage_lines: int
    total_lines: int
    top_products: list[MarginProduct]


class SetupStep(BaseModel):
    key: str
    label: str
    done: bool
    link: str


class BusinessHome(BaseModel):
    generated_at: datetime
    kpis: list[HomeKpi]
    delays: DelaySummary
    exceptions: ExceptionSummary
    stock: StockSummary
    money: MoneyEstimate
    setup: list[SetupStep]


class WarehouseTodayItem(BaseModel):
    key: str
    label: str
    count: int
    link: str


class WarehouseToday(BaseModel):
    generated_at: datetime
    warehouse_id: Optional[int] = None
    items: list[WarehouseTodayItem]
