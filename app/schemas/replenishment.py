"""نقطه سفارش با فرمول و برآورد سرمایه خرید (app/services/replenishment_service.py)."""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class InventoryPolicy(BaseModel):
    lead_time_days: float
    lead_time_std_days: float
    service_level: float
    history_days: int
    min_history_days: int
    ordering_cost: float
    holding_rate: float
    cover_days: int
    price_growth_monthly: float
    demand_growth_monthly: float


class InventoryPolicyUpdate(BaseModel):
    lead_time_days: Optional[float] = Field(None, ge=0, le=365)
    lead_time_std_days: Optional[float] = Field(None, ge=0, le=120)
    service_level: Optional[float] = Field(None, ge=0.5, le=0.999)
    history_days: Optional[int] = Field(None, ge=14, le=730)
    min_history_days: Optional[int] = Field(None, ge=7, le=120)
    ordering_cost: Optional[float] = Field(None, ge=0)
    holding_rate: Optional[float] = Field(None, ge=0, le=2)
    cover_days: Optional[int] = Field(None, ge=1, le=365)
    price_growth_monthly: Optional[float] = Field(None, ge=-0.5, le=1)
    demand_growth_monthly: Optional[float] = Field(None, ge=-0.5, le=1)


class ParamSource(BaseModel):
    lead_time_days: Literal["item", "policy"]
    lead_time_std_days: Literal["item", "policy"]
    service_level: Literal["item", "policy"]


class EffectiveParams(BaseModel):
    lead_time_days: float
    lead_time_std_days: float
    service_level: float
    source: ParamSource


class RopCalc(BaseModel):
    data_days: int
    sufficient: bool
    avg_daily_demand: float
    demand_std: float
    z: float
    lead_time_demand: float
    safety_stock: int
    rop: int
    order_qty: int
    order_qty_method: Literal["eoq", "cover"]
    max_stock: int
    annual_demand: int


RopStatus = Literal["out", "critical", "reorder", "ok"]


class RopItem(BaseModel):
    inventory_id: int
    product_id: int
    sku: str
    name: str
    category: Optional[str] = None
    unit: str
    warehouse_id: Optional[int] = None
    warehouse: Optional[str] = None
    quantity: int
    reorder_point: int
    rop_mode: Literal["manual", "auto"]
    lead_time_days: Optional[float] = None
    lead_time_std_days: Optional[float] = None
    service_level: Optional[float] = None
    effective: EffectiveParams
    calc: RopCalc
    status: RopStatus
    days_of_cover: Optional[float] = None
    stockout_date: Optional[date] = None
    suggested_purchase: int
    calculated_at: Optional[datetime] = None


class RopSummary(BaseModel):
    out: int
    critical: int
    reorder: int
    ok: int
    auto: int
    insufficient: int
    total: int


class RopList(BaseModel):
    policy: InventoryPolicy
    summary: RopSummary
    items: list[RopItem]


class RopItemUpdate(BaseModel):
    rop_mode: Optional[Literal["manual", "auto"]] = None
    # null یعنی «پیش‌فرض سازمان»
    lead_time_days: Optional[float] = Field(None, ge=0, le=365)
    lead_time_std_days: Optional[float] = Field(None, ge=0, le=120)
    service_level: Optional[float] = Field(None, ge=0.5, le=0.999)
    reorder_point: Optional[int] = Field(None, ge=0)


class ApplyAutoIn(BaseModel):
    inventory_ids: Optional[list[int]] = None     # خالی = همه اقلام دارای داده کافی
    warehouse_id: Optional[int] = Field(None, gt=0)


class ApplyAutoOut(BaseModel):
    switched: int
    skipped: int


class PlanMonth(BaseModel):
    key: str
    label: str
    start: date
    end: date
    days: int
    partial: bool
    capital: int
    cumulative: int
    orders: int
    units: int
    demand_units: int
    stock_value_end: int
    stockout_items: int


class PlanItemMonth(BaseModel):
    capital: int
    units: int
    orders: int


class PlanItem(BaseModel):
    inventory_id: int
    sku: str
    name: str
    category: Optional[str] = None
    warehouse: Optional[str] = None
    quantity: int
    rop: int
    order_qty: int
    lead_time_days: float
    forecast_method: Literal["holt", "average"]
    avg_daily_forecast: float
    unit_cost_now: int
    cost_estimated: bool
    months: list[PlanItemMonth]
    total_capital: int
    total_units: int
    stockout_risk: bool


class PlanSummary(BaseModel):
    total_capital: int
    peak_month: Optional[str] = None
    peak_capital: int
    average_monthly: int
    items_planned: int
    items_without_demand: int
    items_cost_estimated: int
    cost_estimated_names: list[str]
    stockout_risk_items: int
    current_stock_value: int


class PlanBreakdown(BaseModel):
    label: str
    capital: int


class PlanAssumptions(InventoryPolicy):
    horizon_months: int
    warehouse_id: Optional[int] = None


class CapitalPlan(BaseModel):
    generated_at: datetime
    months: list[PlanMonth]
    items: list[PlanItem]
    assumptions: PlanAssumptions
    summary: PlanSummary
    by_category: list[PlanBreakdown]
    by_warehouse: list[PlanBreakdown]
