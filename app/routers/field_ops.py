"""عملیات میدانی تحویل: برگشت از راننده، تماس، مأموریت، تحویل بین رانندگان، خودروی خارج از سرویس و درخواست‌های مشتری."""
from fastapi import APIRouter, HTTPException, Path, Request

from app.database import db_dependency
from app.dependencies import user_dependency
from app.schemas.field import (
    ContactIn, ContactOut, CustomerDecisionIn, CustomerRequestIn, CustomerRequestOut, CustomerRequestPublicOut, DriverReturnOut,
    HandoverIn, HandoverOut, HandoverRespondIn, MissionIn, OutOfServiceIn, OutOfServiceOut, ReceiveReturnIn,
)
from app.core.rate_limit import RateLimiter
from app.schemas.platform_ops import PlanSummary
from app.services import customer_request_service, field_service, platform_service
from app.services.exceptions import DomainError

router = APIRouter(tags=["🚚 عملیات میدانی تحویل"])
public_router = APIRouter(prefix="/public/track", tags=["📍 پیگیری عمومی سفارش"])
request_limiter = RateLimiter("track-request", max_requests=20, window_seconds=600)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/orders/{order_id}/driver-returns", response_model=list[DriverReturnOut], summary="📦 کالای در انتظار برگشت از راننده")
def driver_returns(db: db_dependency, user: user_dependency, order_id: int = Path(gt=0)):
    return _call(field_service.list_returns, db, user, order_id)


@router.post("/orders/{order_id}/driver-returns/{return_id}/receive", response_model=DriverReturnOut, summary="✅ شمارش و ثبت برگشت در انبار")
def receive_return(data: ReceiveReturnIn, db: db_dependency, user: user_dependency, order_id: int = Path(gt=0), return_id: int = Path(gt=0)):
    return _call(field_service.receive_return, db, user, order_id, return_id, data)


@router.get("/orders/{order_id}/contacts", response_model=list[ContactOut], summary="📞 تماس‌های ثبت‌شده با گیرنده")
def contacts(db: db_dependency, user: user_dependency, order_id: int = Path(gt=0)):
    return _call(field_service.list_contacts, db, user, order_id)


@router.post("/orders/{order_id}/contacts", response_model=ContactOut, summary="📞 ثبت تماس با گیرنده")
def add_contact(data: ContactIn, db: db_dependency, user: user_dependency, order_id: int = Path(gt=0)):
    return _call(field_service.add_contact, db, user, order_id, data)


@router.post("/orders/{order_id}/mission", summary="🚦 قبول یا رد مأموریت توسط راننده")
def mission(data: MissionIn, db: db_dependency, user: user_dependency, order_id: int = Path(gt=0)) -> dict:
    order = _call(field_service.respond_mission, db, user, order_id, data)
    return {"order_id": order_id, "status": order.status, "assignment_state": order.assignment_state}


@router.get("/orders/{order_id}/handovers", response_model=list[HandoverOut], summary="🤝 تحویل‌های بین رانندگان")
def handovers(db: db_dependency, user: user_dependency, order_id: int = Path(gt=0)):
    return _call(field_service.order_handovers, db, user, order_id)


@router.post("/orders/{order_id}/handovers", response_model=HandoverOut, summary="🤝 درخواست تحویل بار به راننده دیگر")
def request_handover(data: HandoverIn, db: db_dependency, user: user_dependency, order_id: int = Path(gt=0)):
    return _call(field_service.request_handover, db, user, order_id, data)


@router.get("/handovers/mine", response_model=list[HandoverOut], summary="🤝 تحویل‌های منتظر تأیید من")
def my_handovers(db: db_dependency, user: user_dependency):
    return _call(field_service.my_handovers, db, user)


@router.post("/handovers/{handover_id}/respond", response_model=HandoverOut, summary="🤝 تأیید یا رد تحویل گرفتن بار")
def respond_handover(data: HandoverRespondIn, db: db_dependency, user: user_dependency, handover_id: int = Path(gt=0)):
    return _call(field_service.respond_handover, db, user, handover_id, data)


@router.post("/vehicles/{vehicle_id}/out-of-service", response_model=OutOfServiceOut, summary="🛠️ خروج خودرو از سرویس و جابه‌جایی سفارش‌ها")
def out_of_service(data: OutOfServiceIn, db: db_dependency, user: user_dependency, vehicle_id: int = Path(gt=0)):
    return _call(field_service.out_of_service, db, user, vehicle_id, data)


@router.get("/orders/{order_id}/customer-requests", response_model=list[CustomerRequestOut], summary="🙋 درخواست‌های مشتری برای این سفارش")
def customer_requests(db: db_dependency, user: user_dependency, order_id: int = Path(gt=0)):
    return _call(customer_request_service.for_order, db, user, order_id)


@router.post("/customer-requests/{request_id}/decide", response_model=CustomerRequestOut, summary="🙋 تأیید یا رد درخواست مشتری")
def decide(data: CustomerDecisionIn, db: db_dependency, user: user_dependency, request_id: int = Path(gt=0)):
    return _call(customer_request_service.decide, db, user, request_id, data)


@router.get("/organization/plan", response_model=PlanSummary, summary="📦 پلن و مصرف سازمان من")
def my_plan(db: db_dependency, user: user_dependency):
    if user.role != "org_admin":
        raise HTTPException(status_code=403, detail="فقط ادمین سازمان پلن را می‌بیند.")
    return _call(platform_service.plan_summary, db, user.organization_id)


@public_router.post("/{code}/requests", response_model=CustomerRequestPublicOut, summary="🙋 درخواست مشتری (نیازمند ۴ رقم موبایل)")
def submit_request(code: str, data: CustomerRequestIn, request: Request, db: db_dependency):
    if not request_limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="تعداد درخواست‌ها زیاد است؛ چند دقیقه دیگر امتحان کنید.")
    return _call(customer_request_service.submit, db, code, data)
