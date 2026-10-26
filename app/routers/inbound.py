"""رسید و دریافت کالا (فصل ۷)، بازرسی کیفی (فصل ۸) و جانمایی (فصل ۹)."""
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Path, Query, status

from app.core.wms import PUTAWAY_STATUSES, RECEIPT_STATUSES, RECEIPT_TYPES, TASK_TYPES
from app.database import db_dependency
from app.dependencies import IdempotencyKey, user_dependency
from app.schemas.operations import (
    InspectionCreate, InspectionOut, PutawayExecute, PutawayProblemIn, PutawaySuggestionOut, PutawayTaskCreate, PutawayTaskOut,
    QualityTransitionOut, ReasonIn, ReceiptCloseIn, ReceiptCreate, ReceiptOut, ReceiveIn,
)
from app.services import putaway_service, quality_service, receiving_service
from app.services.exceptions import DomainError

router = APIRouter(prefix="/inbound", tags=["📥 رسید و دریافت کالا"])
quality_router = APIRouter(prefix="/quality", tags=["🧪 بازرسی کیفی"])
putaway_router = APIRouter(prefix="/putaway", tags=["🏷️ جانمایی"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


# ---------------------------------------------------------------------------
# رسید دریافت
# ---------------------------------------------------------------------------
@router.get("/receipts", response_model=list[ReceiptOut], summary="📋 رسیدهای دریافت")
def list_receipts(
    db: db_dependency, user: user_dependency,
    status_: Optional[Literal[RECEIPT_STATUSES]] = Query(None, alias="status"),
    receipt_type: Optional[Literal[RECEIPT_TYPES]] = Query(None), warehouse_id: Optional[int] = Query(None, gt=0),
    q: Optional[str] = Query(None, max_length=64, description="کد رسید، شماره بارنامه یا سفارش خرید"),
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
):
    return _call(receiving_service.list_receipts, db, user, status=status_, receipt_type=receipt_type,
                 warehouse_id=warehouse_id, q=q, skip=skip, limit=limit)


@router.post("/receipts", response_model=ReceiptOut, status_code=status.HTTP_201_CREATED,
             summary="➕ رسید جدید (خرید، انتقال، مرجوعی، پیش‌بینی‌نشده)")
def create_receipt(data: ReceiptCreate, db: db_dependency, user: user_dependency, idempotency_key: IdempotencyKey = None):
    return _call(receiving_service.create_receipt, db, user, data, idempotency_key)


@router.get("/receipts/{receipt_id}", response_model=ReceiptOut, summary="📄 جزئیات رسید")
def get_receipt(db: db_dependency, user: user_dependency, receipt_id: int = Path(gt=0)):
    return _call(receiving_service.get_receipt, db, user, receipt_id)


@router.post("/receipts/{receipt_id}/receive", response_model=ReceiptOut, status_code=status.HTTP_201_CREATED,
             summary="📦 ثبت دریافت فیزیکی (شمارش، بچ، انقضا، سریال، وضعیت)")
def receive(data: ReceiveIn, db: db_dependency, user: user_dependency, receipt_id: int = Path(gt=0),
            idempotency_key: IdempotencyKey = None):
    return _call(receiving_service.receive, db, user, receipt_id, data, idempotency_key)


@router.post("/receipts/{receipt_id}/close", response_model=ReceiptOut, summary="✅ بستن رسید و ثبت مغایرت‌ها")
def close_receipt(data: ReceiptCloseIn, db: db_dependency, user: user_dependency, receipt_id: int = Path(gt=0)):
    return _call(receiving_service.close, db, user, receipt_id, data)


@router.post("/receipts/{receipt_id}/cancel", response_model=ReceiptOut, summary="✖️ لغو رسید (پیش از دریافت)")
def cancel_receipt(data: ReasonIn, db: db_dependency, user: user_dependency, receipt_id: int = Path(gt=0)):
    return _call(receiving_service.cancel, db, user, receipt_id, data.reason)


# ---------------------------------------------------------------------------
# بازرسی کیفی
# ---------------------------------------------------------------------------
@quality_router.get("/inspections", response_model=list[InspectionOut], summary="📋 سوابق بازرسی کیفی")
def list_inspections(db: db_dependency, user: user_dependency, warehouse_id: Optional[int] = Query(None, gt=0),
                     product_id: Optional[int] = Query(None, gt=0), receipt_id: Optional[int] = Query(None, gt=0)):
    return _call(quality_service.list_inspections, db, user, warehouse_id=warehouse_id, product_id=product_id,
                 receipt_id=receipt_id)


@quality_router.post("/inspections", response_model=InspectionOut, status_code=status.HTTP_201_CREATED,
                     summary="🧪 ثبت نتیجه بازرسی (تأیید، قرنطینه، مردود، معیوب، آسیب‌دیده)")
def inspect(data: InspectionCreate, db: db_dependency, user: user_dependency, idempotency_key: IdempotencyKey = None):
    return _call(quality_service.inspect, db, user, data, idempotency_key)


@quality_router.get("/inspections/{inspection_id}", response_model=InspectionOut, summary="📄 جزئیات بازرسی")
def get_inspection(db: db_dependency, user: user_dependency, inspection_id: int = Path(gt=0)):
    return _call(quality_service.get_inspection, db, user, inspection_id)


@quality_router.get("/transitions", response_model=list[QualityTransitionOut], response_model_by_alias=True,
                    summary="🔐 تغییرهای مجاز وضعیت کیفی برای کاربر جاری")
def transitions(user: user_dependency):
    return quality_service.transitions_for(user)


# ---------------------------------------------------------------------------
# جانمایی
# ---------------------------------------------------------------------------
@putaway_router.get("/tasks", response_model=list[PutawayTaskOut], summary="📋 وظایف جانمایی")
def list_tasks(db: db_dependency, user: user_dependency,
               status_: Optional[Literal[PUTAWAY_STATUSES + ("active",)]] = Query(None, alias="status"),
               warehouse_id: Optional[int] = Query(None, gt=0), receipt_id: Optional[int] = Query(None, gt=0),
               task_type: Optional[Literal[TASK_TYPES]] = Query(None, description="جانمایی یا تأمین مجدد")):
    return _call(putaway_service.list_tasks, db, user, status=status_, warehouse_id=warehouse_id, receipt_id=receipt_id,
                 task_type=task_type)


@putaway_router.post("/tasks", response_model=PutawayTaskOut, status_code=status.HTTP_201_CREATED,
                     summary="➕ وظیفه جانمایی دستی")
def create_task(data: PutawayTaskCreate, db: db_dependency, user: user_dependency):
    return _call(putaway_service.create_task, db, user, data)


@putaway_router.get("/tasks/{task_id}", response_model=PutawayTaskOut, summary="📄 جزئیات وظیفه")
def get_task(db: db_dependency, user: user_dependency, task_id: int = Path(gt=0)):
    return _call(putaway_service.get_task, db, user, task_id)


@putaway_router.post("/tasks/{task_id}/execute", response_model=PutawayTaskOut,
                     summary="📲 اجرای جانمایی با اسکن کالا، محل مبدأ و محل مقصد")
def execute_task(data: PutawayExecute, db: db_dependency, user: user_dependency, task_id: int = Path(gt=0),
                 idempotency_key: IdempotencyKey = None):
    return _call(putaway_service.execute, db, user, task_id, data, idempotency_key)


@putaway_router.post("/tasks/{task_id}/problem", response_model=PutawayTaskOut,
                     summary="⚠️ گزارش مشکل (مقصد پر/مسدود، کالای آسیب‌دیده یا ناموجود)")
def report_problem(data: PutawayProblemIn, db: db_dependency, user: user_dependency, task_id: int = Path(gt=0)):
    return _call(putaway_service.report_problem, db, user, task_id, data)


@putaway_router.post("/tasks/{task_id}/suggest", response_model=PutawayTaskOut, summary="🔄 پیشنهاد دوباره مقصد")
def refresh_suggestion(db: db_dependency, user: user_dependency, task_id: int = Path(gt=0)):
    return _call(putaway_service.refresh_suggestion, db, user, task_id)


@putaway_router.get("/tasks/{task_id}/suggestions", response_model=list[PutawaySuggestionOut],
                    summary="🧠 مقصدهای برتر با دلیل (تجمیع، محل خالی، نزدیکی مسیر بر اساس ABC)")
def task_suggestions(db: db_dependency, user: user_dependency, task_id: int = Path(gt=0)):
    return _call(putaway_service.suggestions, db, user, task_id)


@putaway_router.post("/tasks/{task_id}/cancel", response_model=PutawayTaskOut, summary="✖️ لغو وظیفه")
def cancel_task(data: ReasonIn, db: db_dependency, user: user_dependency, task_id: int = Path(gt=0)):
    return _call(putaway_service.cancel, db, user, task_id, data.reason)
