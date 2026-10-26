"""اجرای سفارش و جابه‌جایی (فصل‌های ۱۱ تا ۱۵): سفارش معوق، سفارش انتقال، تأمین مجدد و ABC، پیکینگ، بسته‌بندی و ارسال، تعیین تکلیف."""
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Path, Query, status

from app.core.wms import BACKORDER_STATUSES, DISPOSITION_ACTIONS, PICK_LIST_STATUSES, SHIPMENT_STATUSES, TRANSFER_STATUSES
from app.database import db_dependency
from app.dependencies import IdempotencyKey, user_dependency
from app.schemas.fulfillment import (
    AbcRowOut, AbcRunIn, AbcRunOut, AllocateIn, AllocateOut, BackorderOut, DispatchIn, DispositionCreate, DispositionOut,
    FulfillIn, GenerateOut, PackIn, PackingQueueOut, PackingSlipOut, PickCandidateOut, PickIn, PickListCreate, PickListOut,
    ReasonIn, ReplenishmentRuleIn, ReplenishmentRuleOut, ShipmentCreate, ShipmentOut, ShortIn, TransferCloseIn,
    TransferCreate, TransferOut, TransferReceiveIn,
)
from app.schemas.order import OrderResponse
from app.services import (
    audit_service, backorder_service, disposition_service, picking_service, replenishment_rule_service, shipping_service,
    transfer_order_service,
)
from app.services.exceptions import DomainError

backorders = APIRouter(prefix="/backorders", tags=["⏳ سفارش معوق و تخصیص"])
transfers = APIRouter(prefix="/transfer-orders", tags=["🚚 سفارش انتقال"])
replenishment = APIRouter(prefix="/replenishment-rules", tags=["🔁 تأمین مجدد و ABC"])
picking = APIRouter(prefix="/picking", tags=["🧺 پیکینگ"])
shipping = APIRouter(prefix="/shipping", tags=["📦 بسته‌بندی و ارسال"])
dispositions = APIRouter(prefix="/dispositions", tags=["♻️ تعیین تکلیف کالای مرجوعی/معیوب"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


# ---------------------------------------------------------------- سفارش معوق
@backorders.get("/", response_model=list[BackorderOut], summary="📋 سفارش‌های معوق (به ترتیب اولویت تخصیص)")
def list_backorders(db: db_dependency, user: user_dependency,
                    status_: Optional[Literal[BACKORDER_STATUSES + ("active",)]] = Query("active", alias="status"),
                    order_id: Optional[int] = Query(None, gt=0), warehouse_id: Optional[int] = Query(None, gt=0)):
    return _call(backorder_service.list_backorders, db, user, status=status_, order_id=order_id, warehouse_id=warehouse_id)


@backorders.post("/allocate", response_model=AllocateOut, summary="⚖️ تخصیص موجودی به سفارش‌های معوق با اولویت")
def allocate(data: AllocateIn, db: db_dependency, user: user_dependency):
    return _call(backorder_service.allocate, db, user, warehouse_id=data.warehouse_id, product_id=data.product_id)


@backorders.post("/orders/{order_id}/fulfill", response_model=OrderResponse, status_code=status.HTTP_201_CREATED,
                 summary="🚀 سفارش تکمیلی از معوق‌های تخصیص‌یافته یک سفارش")
def fulfill(data: FulfillIn, db: db_dependency, user: user_dependency, order_id: int = Path(gt=0)):
    return _call(backorder_service.fulfill, db, user, order_id, data.delivery_window_start, data.delivery_window_end)


@backorders.post("/{backorder_id}/cancel", response_model=BackorderOut, summary="✖️ لغو سفارش معوق")
def cancel_backorder(data: ReasonIn, db: db_dependency, user: user_dependency, backorder_id: int = Path(gt=0)):
    return _call(backorder_service.cancel, db, user, backorder_id, data.reason)


# ---------------------------------------------------------------- سفارش انتقال
@transfers.get("/", response_model=list[TransferOut], summary="📋 سفارش‌های انتقال")
def list_transfers(db: db_dependency, user: user_dependency,
                   status_: Optional[Literal[TRANSFER_STATUSES]] = Query(None, alias="status")):
    return _call(transfer_order_service.list_transfers, db, user, status=status_)


@transfers.post("/", response_model=TransferOut, status_code=status.HTTP_201_CREATED, summary="➕ سفارش انتقال دومرحله‌ای")
def create_transfer(data: TransferCreate, db: db_dependency, user: user_dependency, idempotency_key: IdempotencyKey = None):
    return _call(transfer_order_service.create, db, user, data, idempotency_key)


@transfers.get("/{transfer_id}", response_model=TransferOut, summary="📄 جزئیات سفارش انتقال")
def get_transfer(db: db_dependency, user: user_dependency, transfer_id: int = Path(gt=0)):
    return _call(transfer_order_service.get, db, user, transfer_id)


@transfers.post("/{transfer_id}/ship", response_model=TransferOut, summary="🚚 ارسال: کالا از مبدأ خارج و «در راه» می‌شود")
def ship_transfer(db: db_dependency, user: user_dependency, transfer_id: int = Path(gt=0), idempotency_key: IdempotencyKey = None):
    return _call(transfer_order_service.ship, db, user, transfer_id, idempotency_key)


@transfers.post("/{transfer_id}/receive", response_model=TransferOut, summary="📥 دریافت در مقصد (سالم و آسیب‌دیده)")
def receive_transfer(data: TransferReceiveIn, db: db_dependency, user: user_dependency, transfer_id: int = Path(gt=0),
                     idempotency_key: IdempotencyKey = None):
    return _call(transfer_order_service.receive, db, user, transfer_id, data, idempotency_key)


@transfers.post("/{transfer_id}/close", response_model=TransferOut, summary="✅ بستن و تکلیف کسری در راه")
def close_transfer(data: TransferCloseIn, db: db_dependency, user: user_dependency, transfer_id: int = Path(gt=0)):
    return _call(transfer_order_service.close, db, user, transfer_id, data)


@transfers.post("/{transfer_id}/cancel", response_model=TransferOut, summary="✖️ لغو پیش از ارسال")
def cancel_transfer(db: db_dependency, user: user_dependency, transfer_id: int = Path(gt=0)):
    return _call(transfer_order_service.cancel, db, user, transfer_id)


# ---------------------------------------------------------------- تأمین مجدد و ABC
@replenishment.get("/", response_model=list[ReplenishmentRuleOut], summary="📋 قواعد حداقل/حداکثر محل‌های برداشت")
def list_rules(db: db_dependency, user: user_dependency, warehouse_id: Optional[int] = Query(None, gt=0)):
    return _call(replenishment_rule_service.list_rules, db, user, warehouse_id)


@replenishment.post("/", response_model=ReplenishmentRuleOut, status_code=status.HTTP_201_CREATED, summary="➕ قاعده تأمین مجدد")
def create_rule(data: ReplenishmentRuleIn, db: db_dependency, user: user_dependency):
    return _call(replenishment_rule_service.save_rule, db, user, data)


@replenishment.put("/{rule_id}", response_model=ReplenishmentRuleOut, summary="✏️ ویرایش قاعده")
def update_rule(data: ReplenishmentRuleIn, db: db_dependency, user: user_dependency, rule_id: int = Path(gt=0)):
    return _call(replenishment_rule_service.save_rule, db, user, data, rule_id)


@replenishment.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, summary="🗑️ حذف قاعده")
def delete_rule(db: db_dependency, user: user_dependency, rule_id: int = Path(gt=0)):
    _call(replenishment_rule_service.delete_rule, db, user, rule_id)


@replenishment.post("/generate", response_model=GenerateOut, summary="⚙️ ساخت وظایف تأمین مجدد برای محل‌های زیر حداقل")
def generate(db: db_dependency, user: user_dependency, warehouse_id: Optional[int] = Query(None, gt=0)):
    return _call(replenishment_rule_service.generate, db, user, warehouse_id)


@replenishment.get("/abc", response_model=list[AbcRowOut], summary="🔤 طبقه‌بندی ABC و سررسید شمارش")
def abc_report(db: db_dependency, user: user_dependency, warehouse_id: Optional[int] = Query(None, gt=0)):
    return _call(replenishment_rule_service.abc_report, db, user, warehouse_id)


@replenishment.post("/abc", response_model=AbcRunOut, summary="🔄 محاسبه دوباره ABC از ارزش مصرف")
def abc_classify(data: AbcRunIn, db: db_dependency, user: user_dependency):
    if getattr(user.role, "value", user.role) != "org_admin":
        raise HTTPException(status_code=403, detail="محاسبه ABC فقط با ادمین سازمان است.")
    return _call(replenishment_rule_service.classify, db, user, data.days)


# ---------------------------------------------------------------- پیکینگ
@picking.get("/candidates", response_model=list[PickCandidateOut], summary="🧾 سفارش‌های آماده برداشت")
def pick_candidates(db: db_dependency, user: user_dependency, warehouse_id: Optional[int] = Query(None, gt=0)):
    return _call(picking_service.candidates, db, user, warehouse_id)


@picking.get("/lists", response_model=list[PickListOut], summary="📋 فهرست‌های برداشت")
def list_pick_lists(db: db_dependency, user: user_dependency, warehouse_id: Optional[int] = Query(None, gt=0),
                    status_: Optional[Literal[PICK_LIST_STATUSES + ("active",)]] = Query(None, alias="status")):
    return _call(picking_service.list_pick_lists, db, user, warehouse_id=warehouse_id, status=status_)


@picking.post("/lists", response_model=PickListOut, status_code=status.HTTP_201_CREATED,
              summary="➕ فهرست برداشت (تک‌سفارشی، دسته‌ای، موجی، منطقه‌ای)")
def create_pick_list(data: PickListCreate, db: db_dependency, user: user_dependency):
    return _call(picking_service.create_pick_list, db, user, data)


@picking.get("/lists/{pick_list_id}", response_model=PickListOut, summary="📄 جزئیات فهرست برداشت")
def get_pick_list(db: db_dependency, user: user_dependency, pick_list_id: int = Path(gt=0)):
    return _call(picking_service.get_pick_list, db, user, pick_list_id)


@picking.post("/lines/{line_id}/pick", response_model=PickListOut, summary="📲 برداشت با اسکن محل، کالا و بچ")
def pick_line(data: PickIn, db: db_dependency, user: user_dependency, line_id: int = Path(gt=0),
              idempotency_key: IdempotencyKey = None):
    return _call(picking_service.pick, db, user, line_id, data, idempotency_key)


@picking.post("/lines/{line_id}/short", response_model=PickListOut, summary="⚠️ کمبود در محل و برنامه‌ریزی دوباره")
def short_line(data: ShortIn, db: db_dependency, user: user_dependency, line_id: int = Path(gt=0)):
    return _call(picking_service.short, db, user, line_id, data)


@picking.post("/lists/{pick_list_id}/cancel", response_model=PickListOut, summary="✖️ لغو فهرست برداشت")
def cancel_pick_list(data: ReasonIn, db: db_dependency, user: user_dependency, pick_list_id: int = Path(gt=0)):
    return _call(picking_service.cancel_list, db, user, pick_list_id, data.reason)


# ---------------------------------------------------------------- بسته‌بندی و ارسال
@shipping.get("/queue", response_model=list[PackingQueueOut], summary="🧾 سفارش‌های آماده بسته‌بندی و ارسال")
def packing_queue(db: db_dependency, user: user_dependency, warehouse_id: Optional[int] = Query(None, gt=0)):
    return _call(shipping_service.packing_queue, db, user, warehouse_id)


@shipping.post("/orders/{order_id}/pack", response_model=PackingSlipOut, summary="📦 بسته‌بندی سفارش (ابعاد، وزن، محتوا)")
def pack(data: PackIn, db: db_dependency, user: user_dependency, order_id: int = Path(gt=0)):
    return _call(shipping_service.pack, db, user, order_id, data)


@shipping.get("/orders/{order_id}/packing-slip", response_model=PackingSlipOut, summary="🧾 برگه بسته‌بندی")
def packing_slip(db: db_dependency, user: user_dependency, order_id: int = Path(gt=0)):
    return _call(shipping_service.packing_slip, db, user, order_id)


@shipping.get("/shipments", response_model=list[ShipmentOut], summary="📋 محموله‌ها")
def list_shipments(db: db_dependency, user: user_dependency, warehouse_id: Optional[int] = Query(None, gt=0),
                   status_: Optional[Literal[SHIPMENT_STATUSES]] = Query(None, alias="status")):
    return _call(shipping_service.list_shipments, db, user, warehouse_id=warehouse_id, status=status_)


@shipping.post("/shipments", response_model=ShipmentOut, status_code=status.HTTP_201_CREATED,
               summary="🚛 محموله با کنترل ظرفیت وزنی و حجمی خودرو")
def create_shipment(data: ShipmentCreate, db: db_dependency, user: user_dependency):
    return _call(shipping_service.create_shipment, db, user, data)


@shipping.get("/shipments/{shipment_id}", response_model=ShipmentOut, summary="📄 جزئیات محموله")
def get_shipment(db: db_dependency, user: user_dependency, shipment_id: int = Path(gt=0)):
    return _call(shipping_service.get_shipment, db, user, shipment_id)


@shipping.delete("/shipments/{shipment_id}/orders/{order_id}", response_model=ShipmentOut, summary="➖ برداشتن سفارش از محموله")
def remove_order(db: db_dependency, user: user_dependency, shipment_id: int = Path(gt=0), order_id: int = Path(gt=0)):
    return _call(shipping_service.remove_order, db, user, shipment_id, order_id)


@shipping.post("/shipments/{shipment_id}/dispatch", response_model=ShipmentOut, summary="🤝 تحویل به راننده و خروج کالا")
def dispatch(data: DispatchIn, db: db_dependency, user: user_dependency, shipment_id: int = Path(gt=0)):
    return _call(shipping_service.dispatch, db, user, shipment_id, data.note)


@shipping.post("/shipments/{shipment_id}/cancel", response_model=ShipmentOut, summary="✖️ لغو محموله پیش از تحویل")
def cancel_shipment(db: db_dependency, user: user_dependency, shipment_id: int = Path(gt=0)):
    return _call(shipping_service.cancel, db, user, shipment_id)


# ---------------------------------------------------------------- تعیین تکلیف
@dispositions.get("/", response_model=list[DispositionOut], summary="📋 سوابق تعیین تکلیف")
def list_dispositions(db: db_dependency, user: user_dependency, warehouse_id: Optional[int] = Query(None, gt=0),
                      action: Optional[Literal[DISPOSITION_ACTIONS]] = Query(None)):
    return _call(disposition_service.list_dispositions, db, user, warehouse_id=warehouse_id, action=action)


@dispositions.post("/", response_model=DispositionOut, status_code=status.HTTP_201_CREATED,
                   summary="♻️ امحا، تعمیر، برگشت به تأمین‌کننده یا بازرسی دوباره")
def dispose(data: DispositionCreate, db: db_dependency, user: user_dependency):
    result = _call(disposition_service.dispose, db, user, data)
    audit_service.record(db, user, "stock.disposition", f"تعیین تکلیف {result.get('code')}: {data.action} — {data.quantity} واحد",
                         target_type="disposition", target_id=result.get("id"), target_label=result.get("code"), reason=data.reason)
    return result
