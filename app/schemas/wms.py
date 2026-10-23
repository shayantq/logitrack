"""اسکیماهای اسناد انبار، رزرو، ردیف‌های موجودی به تفکیک وضعیت و رویدادها."""
from datetime import datetime
from typing import Annotated, Any, Optional

from pydantic import BaseModel, StringConstraints

from app.schemas.product import StockMovementResponse

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class ReverseRequest(BaseModel):
    reason: Reason


class StockDocumentOut(BaseModel):
    id: int
    code: str
    doc_type: str
    doc_type_label: str
    status: str
    warehouse_id: Optional[int] = None
    warehouse_name: Optional[str] = None
    partner_id: Optional[int] = None
    partner_name: Optional[str] = None
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    external_ref: Optional[str] = None
    note: Optional[str] = None
    created_at: Optional[datetime] = None
    created_by_name: Optional[str] = None
    reversal_of_id: Optional[int] = None
    reversal_of_code: Optional[str] = None
    reversed_by_id: Optional[int] = None
    reversed_by_code: Optional[str] = None
    can_reverse: bool = False
    total_in: int = 0
    total_out: int = 0
    movements: list[StockMovementResponse] = []


class StockBucketOut(BaseModel):
    """یک ردیف موجودی: کالا × انبار × وضعیت کیفی."""
    inventory_id: int
    product_id: int
    product_name: str
    product_sku: str
    unit: str
    warehouse_id: int
    warehouse_name: str
    stock_status: str
    stock_status_label: str
    quantity: int
    reserved: int
    free: int


class ReservationOut(BaseModel):
    id: int
    product_id: int
    product_name: Optional[str] = None
    product_sku: Optional[str] = None
    warehouse_id: int
    warehouse_name: Optional[str] = None
    quantity: int
    status: str
    reference_type: str
    reference_id: int
    reference_label: Optional[str] = None
    created_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    close_reason: Optional[str] = None


class DomainEventOut(BaseModel):
    id: int
    occurred_at: datetime
    event_type: str
    aggregate_type: str
    aggregate_id: int
    actor_name: Optional[str] = None
    payload: dict[str, Any]
