from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.schemas.base import BaseModelWithDateFormatting
from app.schemas.geo_fields import city_in_province
from app.schemas.order import AddressText, CityName, PostalCode, Province

Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class ReturnCountIn(BaseModel):
    product_id: int = Field(gt=0)
    received_quantity: int = Field(ge=0, le=100000)
    shortage_reason: Optional[Note] = None


class ReceiveReturnIn(BaseModel):
    lines: list[ReturnCountIn] = Field(min_length=1, max_length=100)
    location_id: Optional[int] = Field(None, gt=0, description="محل دریافت کالا؛ کالا تا پایان بازرسی موجود آزاد نمی‌شود")
    note: Optional[Note] = None


class ReturnLineOut(BaseModel):
    product_id: int
    product_name: str
    expected_quantity: int
    received_quantity: Optional[int] = None
    shortage_reason: Optional[str] = None


class DriverReturnOut(BaseModelWithDateFormatting):
    id: int
    order_id: int
    status: str
    reason: str
    created_at: datetime
    received_at: Optional[datetime] = None
    received_by: Optional[str] = None
    received_location_code: Optional[str] = None
    note: Optional[str] = None
    lines: list[ReturnLineOut]


class ContactIn(BaseModel):
    method: Literal["call", "sms", "door"] = "call"
    outcome: Literal["answered", "no_answer", "busy", "wrong_number", "off"]
    note: Optional[Note] = None


class ContactOut(BaseModelWithDateFormatting):
    id: int
    at: datetime
    method: str
    method_label: str
    outcome: str
    outcome_label: str
    note: Optional[str] = None
    user_name: Optional[str] = None


class MissionIn(BaseModel):
    accept: bool
    reason: Optional[Note] = None


class OutOfServiceIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class OutOfServiceOut(BaseModel):
    reassigned: list[str]
    unassigned: list[str]
    handover_needed: list[str]


class HandoverIn(BaseModel):
    to_vehicle_id: int = Field(gt=0)
    note: Optional[Note] = None


class HandoverRespondIn(BaseModel):
    accept: bool
    note: Optional[Note] = None


class HandoverItem(BaseModel):
    name: str
    quantity: int


class HandoverOut(BaseModelWithDateFormatting):
    id: int
    order_id: int
    tracking_code: Optional[str] = None
    status: str
    from_driver: Optional[str] = None
    to_driver: Optional[str] = None
    to_vehicle_plate: Optional[str] = None
    note: Optional[str] = None
    response_note: Optional[str] = None
    created_at: datetime
    responded_at: Optional[datetime] = None
    items: list[HandoverItem]


class NewAddress(BaseModel):
    destination_province: Province
    destination_city: CityName
    destination_address: AddressText
    destination_postal_code: Optional[PostalCode] = None

    @model_validator(mode="after")
    def _known_city(self):
        city_in_province(self, "destination_city", "destination_province")
        return self


class ReturnItemIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100000)


class CustomerRequestIn(BaseModel):
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=8)]
    kind: Literal["address_change", "cancel", "return", "dispute"]
    note: Optional[Note] = None
    address: Optional[NewAddress] = None
    items: Optional[list[ReturnItemIn]] = Field(None, max_length=100)


class CustomerRequestPublicOut(BaseModelWithDateFormatting):
    id: int
    kind: str
    kind_label: str
    status: str
    status_label: str
    created_at: datetime
    decision_note: Optional[str] = None


class CustomerRequestOut(CustomerRequestPublicOut):
    order_id: int
    note: Optional[str] = None
    payload: dict[str, Any] = {}
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None


class CustomerDecisionIn(BaseModel):
    approve: bool
    note: Optional[Note] = None
