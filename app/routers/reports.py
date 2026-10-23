import io
import base64
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from celery.result import AsyncResult

from app.database import db_dependency
from app.core.wms import AVAILABLE
from app.models import Product, Order, Vehicle, Inventory, RoleEnum
from app.dependencies import require_role
from app.celery_app import celery_app
from app.tasks import generate_report_task
from app.schemas.report import FinanceSummary, ReportRequest
from app.services import report_data
from app.services.exceptions import DomainError
from app.services import audit_service

router = APIRouter(
    prefix="/reports",
    tags=["📊 گزارش‌گیری و پردازش ناهمگام (Celery)"]
)


@router.get("/stats", summary="📊 آمار کلی برای کارت‌ها و نمودارهای داشبورد")
def get_dashboard_stats(
    db: db_dependency,
    current_user=Depends(require_role([RoleEnum.ORG_ADMIN, RoleEnum.WAREHOUSE_MANAGER]))
):
    # شمارش‌ها مستقیماً در دیتابیس (GROUP BY) انجام می‌شود، نه با بارگذاری همه رکوردها در حافظه
    orders_by_status = dict(db.query(Order.status, func.count(Order.id)).group_by(Order.status).all())
    vehicles_by_status = {
        (s or "نامشخص"): c
        for s, c in db.query(Vehicle.status, func.count(Vehicle.id)).group_by(Vehicle.status).all()
    }

    # کمبود موجودی به تفکیک هر انبار سنجیده می‌شود (هر ردیف موجودی، حد آستانه خودش را دارد)
    inventory_query = db.query(Inventory).options(joinedload(Inventory.product), joinedload(Inventory.warehouse)) \
        .filter(Inventory.stock_status == AVAILABLE)
    products_query = db.query(Product)
    if current_user.role == RoleEnum.WAREHOUSE_MANAGER:
        inventory_query = inventory_query.filter(Inventory.warehouse_id == current_user.warehouse_id)
        products_query = products_query.filter(Product.inventories.any(Inventory.warehouse_id == current_user.warehouse_id))

    low_stock = []
    for inv in inventory_query.all():
        if inv.product is None:
            continue
        stock = inv.quantity or 0
        reorder_point = inv.reorder_point if inv.reorder_point is not None else 10
        if stock <= reorder_point:
            low_stock.append({
                "name": inv.product.name, "sku": inv.product.sku, "stock": stock,
                "reorder_point": reorder_point, "warehouse": inv.warehouse.name if inv.warehouse else None,
            })

    return {
        "orders_by_status": orders_by_status,
        "vehicles_by_status": vehicles_by_status,
        "low_stock_products": low_stock,
        "total_orders": sum(orders_by_status.values()),
        "total_products": products_query.count(),
        "total_vehicles": sum(vehicles_by_status.values()),
    }


# =========================================================================
# پردازش ناهمگام گزارش‌ها (Celery + Redis)
# این خروجی‌ها (اکسل و حالا PDF فارسی هم) در همان درخواست HTTP ساخته
# نمی‌شوند — کار به یک صف (Redis) سپرده می‌شود و توسط یک کانتینر مجزا
# (celery_worker) پردازش می‌شود. ترد اصلی FastAPI هرگز بلاک نمی‌شود.
# جریان کار: ۱) POST برای شروع  ۲) GET task-status برای پایش  ۳) GET
# task-result برای دریافت فایل نهایی وقتی آماده شد.
# =========================================================================

def _all_orders_params() -> dict:
    """خروجی سریع صفحه سفارش‌ها: دو سال گذشته تا یک سال آینده (سقف بازه گزارش سه سال است)."""
    from datetime import timedelta
    from app.services.catalog_service import today_local
    today = today_local()
    return {"date_from": (today - timedelta(days=730)).isoformat(), "date_to": (today + timedelta(days=365)).isoformat()}


def _export_warehouse_scope(user) -> int | None:
    """مدیر انبار فقط گزارش موجودی انبار خودش را می‌گیرد؛ ادمین همه انبارها را."""
    if user.role == RoleEnum.WAREHOUSE_MANAGER:
        if not user.warehouse_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="حساب کاربری شما به هیچ انباری متصل نشده است.")
        return user.warehouse_id
    return None


@router.post("/export/inventory/excel", status_code=status.HTTP_202_ACCEPTED, summary="📥 (ناهمگام) شروع تولید خروجی اکسل موجودی انبار")
def start_inventory_excel_export(
    current_user=Depends(require_role([RoleEnum.ORG_ADMIN, RoleEnum.WAREHOUSE_MANAGER]))
):
    task = generate_report_task.delay(current_user.organization_id, current_user.id, "inventory", "excel", {"warehouse_id": _export_warehouse_scope(current_user)})
    return {"task_id": task.id, "message": "✅ تولید گزارش در پس‌زمینه آغاز شد."}


@router.post("/export/orders/excel", status_code=status.HTTP_202_ACCEPTED, summary="📥 (ناهمگام) شروع تولید خروجی اکسل سفارشات")
def start_orders_excel_export(
    current_user=Depends(require_role([RoleEnum.ORG_ADMIN, RoleEnum.WAREHOUSE_MANAGER]))
):
    task = generate_report_task.delay(current_user.organization_id, current_user.id, "orders", "excel", _all_orders_params())
    return {"task_id": task.id, "message": "✅ تولید گزارش در پس‌زمینه آغاز شد."}


@router.post("/export/inventory/pdf", status_code=status.HTTP_202_ACCEPTED, summary="📥 (ناهمگام) شروع تولید خروجی PDF فارسی موجودی انبار")
def start_inventory_pdf_export(
    current_user=Depends(require_role([RoleEnum.ORG_ADMIN, RoleEnum.WAREHOUSE_MANAGER]))
):
    task = generate_report_task.delay(current_user.organization_id, current_user.id, "inventory", "pdf", {"warehouse_id": _export_warehouse_scope(current_user)})
    return {"task_id": task.id, "message": "✅ تولید گزارش PDF در پس‌زمینه آغاز شد."}


@router.post("/export/orders/pdf", status_code=status.HTTP_202_ACCEPTED, summary="📥 (ناهمگام) شروع تولید خروجی PDF فارسی سفارشات")
def start_orders_pdf_export(
    current_user=Depends(require_role([RoleEnum.ORG_ADMIN, RoleEnum.WAREHOUSE_MANAGER]))
):
    task = generate_report_task.delay(current_user.organization_id, current_user.id, "orders", "pdf", _all_orders_params())
    return {"task_id": task.id, "message": "✅ تولید گزارش PDF در پس‌زمینه آغاز شد."}


def _result_for_user(task_id: str, user) -> AsyncResult:
    """
    هر گزارش آماده، شناسه سازمانش را همراه دارد؛ کاربر سازمان دیگر حتی با
    داشتن task_id هم به آن دسترسی ندارد (۴۰۴ تا وجود گزارش فاش نشود).
    """
    result = AsyncResult(task_id, app=celery_app)
    if result.state == "SUCCESS":
        payload = result.result
        if not isinstance(payload, dict) or payload.get("organization_id") != user.organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="گزارش مورد نظر یافت نشد.")
    return result


@router.get("/task-status/{task_id}", summary="📡 بررسی وضعیت یک کار پس‌زمینه")
def get_task_status(
    task_id: str,
    current_user=Depends(require_role([RoleEnum.ORG_ADMIN, RoleEnum.WAREHOUSE_MANAGER]))
):
    result = _result_for_user(task_id, current_user)
    if result.state == "PENDING":
        return {"status": "pending"}
    if result.state == "SUCCESS":
        return {"status": "success"}
    if result.state == "FAILURE":
        return {"status": "failed", "error": "خطا در تولید گزارش."}
    return {"status": result.state.lower()}


@router.get("/task-result/{task_id}", summary="📥 دریافت فایل نهایی یک کار پس‌زمینه تمام‌شده (اکسل یا PDF)")
def get_task_result(
    task_id: str,
    current_user=Depends(require_role([RoleEnum.ORG_ADMIN, RoleEnum.WAREHOUSE_MANAGER]))
):
    result = _result_for_user(task_id, current_user)
    if result.state != "SUCCESS":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="گزارش هنوز آماده نشده است.")

    payload = result.result
    file_bytes = base64.b64decode(payload["content_b64"])
    headers = {
        "Content-Disposition": f'attachment; filename="{payload["filename"]}"',
        "Access-Control-Expose-Headers": "Content-Disposition"
    }
    return StreamingResponse(
        io.BytesIO(file_bytes), headers=headers,
        media_type=payload.get("content_type", "application/octet-stream")
    )



# ---------------------------------------------------------------------------
# مرحله ۱۴: گزارش با برند سازمان و داشبورد مالی حمل‌ونقل
# ---------------------------------------------------------------------------
@router.post("/generate", status_code=status.HTTP_202_ACCEPTED,
             summary="📑 (ناهمگام) گزارش اکسل/PDF با لوگو و رنگ سازمان: موجودی، سفارش‌ها، دفتر گردش، مالی حمل‌ونقل")
def generate_report(data: ReportRequest, db: db_dependency, current_user=Depends(require_role([RoleEnum.ORG_ADMIN, RoleEnum.WAREHOUSE_MANAGER]))):
    try:
        report_data.check_access(current_user, data.report)
        if data.date_from and data.date_to and data.date_to < data.date_from:
            raise HTTPException(status_code=400, detail="تاریخ پایان باید بعد از تاریخ شروع باشد.")
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    params = {"date_from": data.date_from.isoformat() if data.date_from else None,
              "date_to": data.date_to.isoformat() if data.date_to else None,
              "warehouse_id": data.warehouse_id, "status": data.status, "months": data.months}
    task = generate_report_task.delay(current_user.organization_id, current_user.id, data.report, data.format, params)
    audit_service.record(db, current_user, "report.generate",
                         f"{report_data.TITLES[data.report]} ({'PDF' if data.format == 'pdf' else 'اکسل'}) گرفته شد",
                         details={k: v for k, v in params.items() if v})
    return {"task_id": task.id, "message": "✅ تولید گزارش در پس‌زمینه آغاز شد."}


@router.get("/finance", response_model=FinanceSummary, summary="💰 داشبورد مالی حمل‌ونقل (کرایه، سهم سازمان و رانندگان)")
def finance_summary(db: db_dependency, current_user=Depends(require_role([RoleEnum.ORG_ADMIN])),
                    date_from: date | None = None, date_to: date | None = None):
    try:
        data = report_data.finance_data(db, current_user, date_from, date_to)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    data["details"] = data["details"][-200:]
    return data
