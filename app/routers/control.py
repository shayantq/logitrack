"""
کنترل، تحلیل و آمادگی راه‌اندازی (فصل‌های ۱۶ تا ۳۵): مجوزهای ریز نقش‌ها، داشبورد شاخص‌ها، ارزش‌گذاری و سلامت
موجودی، برچسب و اسکن، گردش‌کار اسناد، چک‌لیست راه‌اندازی و ورود داده از اکسل.
"""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Form, HTTPException, Path, Query, UploadFile
from fastapi.responses import Response

from app.core.workflows import workflows
from app.database import db_dependency
from app.dependencies import user_dependency
from app.schemas.control import (
    ControlSettings, ControlSettingsIn, DataImportReport, HealthOut, KpiDashboard, LabelPrintIn, LabelPrintOut,
    ManualCheckIn, PermissionMatrix, PermissionUpdate, ReadinessOut, ReasonBody, ScanResult, ValuationOut, WorkflowOut,
)
from app.services import (
    analytics_service, control_settings, label_service, migration_io, permission_service, readiness_service, scan_service,
    valuation_service,
)
from app.services.exceptions import DomainError

permissions = APIRouter(prefix="/permissions", tags=["🔐 مجوزهای نقش‌ها"])
analytics = APIRouter(prefix="/analytics", tags=["📈 شاخص‌های عملکرد"])
valuation = APIRouter(prefix="/valuation", tags=["💎 ارزش‌گذاری و سلامت موجودی"])
labels = APIRouter(prefix="/labels", tags=["🏷️ برچسب و بارکد"])
scan = APIRouter(prefix="/scan", tags=["🏷️ برچسب و بارکد"])
readiness = APIRouter(prefix="/readiness", tags=["🚀 آمادگی راه‌اندازی و ورود داده"])
workflow = APIRouter(prefix="/workflows", tags=["🔄 گردش‌کار اسناد"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


# ---------------------------------------------------------------- مجوزها
@permissions.get("/", response_model=PermissionMatrix, summary="🔐 ماتریس مجوزهای نقش‌ها (پیش‌فرض و تغییرات سازمان)")
def matrix(db: db_dependency, user: user_dependency):
    return _call(permission_service.matrix, db, user)


@permissions.put("/{role}/{key}", response_model=PermissionMatrix, summary="✏️ دادن یا گرفتن یک مجوز از یک نقش (با دلیل)")
def update_permission(data: PermissionUpdate, db: db_dependency, user: user_dependency,
                      role: Literal["org_admin", "warehouse_manager"] = Path(),
                      key: str = Path(pattern=r"^[a-z_.]{3,48}$")):
    return _call(permission_service.update, db, user, role, key, data.allowed, data.reason)


@permissions.post("/reset", response_model=PermissionMatrix, summary="↩️ بازگشت همه مجوزها به پیش‌فرض")
def reset_permissions(data: ReasonBody, db: db_dependency, user: user_dependency):
    return _call(permission_service.reset, db, user, data.reason)


# ---------------------------------------------------------------- شاخص‌ها
@analytics.get("/kpis", response_model=KpiDashboard,
               summary="📈 دقت موجودی، تحقق سفارش، دقت برداشت، رسید تا قفسه، گردش موجودی، ضایعات و بهره‌وری ظرفیت")
def kpis(db: db_dependency, user: user_dependency, date_from: Optional[date] = None, date_to: Optional[date] = None,
         warehouse_id: Optional[int] = Query(None, gt=0)):
    return _call(analytics_service.kpis, db, user, date_from=date_from, date_to=date_to, warehouse_id=warehouse_id)


# ---------------------------------------------------------------- ارزش‌گذاری
@valuation.get("/settings", response_model=ControlSettings, summary="⚙️ روش ارزش‌گذاری و آستانه‌های کنترل موجودی")
def get_settings(db: db_dependency, user: user_dependency):
    return _call(control_settings.get, db, user)


@valuation.put("/settings", response_model=ControlSettings, summary="⚙️ تغییر روش ارزش‌گذاری و آستانه‌ها (ادمین، با دلیل)")
def update_settings(data: ControlSettingsIn, db: db_dependency, user: user_dependency):
    return _call(control_settings.update, db, user, data.model_dump(exclude={"reason"}, exclude_none=True), data.reason)


@valuation.get("/", response_model=ValuationOut, summary="💎 ارزش موجودی به سه روش (FIFO، میانگین موزون، استاندارد) و بهای فروش رفته")
def get_valuation(db: db_dependency, user: user_dependency, warehouse_id: Optional[int] = Query(None, gt=0),
                  date_from: Optional[date] = None, date_to: Optional[date] = None):
    return _call(valuation_service.valuation, db, user, warehouse_id=warehouse_id, date_from=date_from, date_to=date_to)


@valuation.get("/health", response_model=HealthOut, summary="🩺 کالای کم‌گردش، راکد و بی‌فروش؛ اقلام نزدیک به انقضا و منقضی")
def get_health(db: db_dependency, user: user_dependency, warehouse_id: Optional[int] = Query(None, gt=0)):
    return _call(valuation_service.health, db, user, warehouse_id=warehouse_id)


# ---------------------------------------------------------------- برچسب و اسکن
@labels.post("/print", summary="🖨️ برچسب PDF با بارکد Code128 و QR (چاپ مجدد با دلیل)",
             response_class=Response, responses={200: {"content": {"application/pdf": {}}}})
def print_labels(data: LabelPrintIn, db: db_dependency, user: user_dependency):
    content, filename = _call(label_service.print_labels, db, user, label_type=data.label_type, ids=data.ids,
                              copies=data.copies, reason=data.reason)
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename}"', "Access-Control-Expose-Headers": "Content-Disposition"})


@labels.get("/history", response_model=list[LabelPrintOut], summary="📜 سابقه چاپ برچسب‌ها")
def label_history(db: db_dependency, user: user_dependency,
                  label_type: Optional[Literal["product", "location", "package"]] = None, limit: int = Query(100, ge=1, le=500)):
    return _call(label_service.history, db, user, label_type=label_type, limit=limit)


@scan.get("/resolve", response_model=ScanResult, summary="🔎 این بارکد/QR چیست؟ (کالا، محل، بسته، سفارش، سند، بچ)")
def resolve(db: db_dependency, user: user_dependency, code: str = Query(min_length=1, max_length=300)):
    return _call(scan_service.resolve, db, user, code)


# ---------------------------------------------------------------- گردش‌کار
@workflow.get("/", response_model=list[WorkflowOut], summary="🔄 ماشین وضعیت اسناد: وضعیت‌ها، انتقال‌ها و انجام‌دهنده")
def list_workflows(user: user_dependency):
    return workflows()


# ---------------------------------------------------------------- آمادگی و ورود داده
@readiness.get("/", response_model=ReadinessOut, summary="🚀 چک‌لیست راه‌اندازی: بررسی خودکار سلامت داده + موارد دستی")
def get_readiness(db: db_dependency, user: user_dependency):
    return _call(readiness_service.overview, db, user)


@readiness.put("/manual/{key}", response_model=ReadinessOut, summary="✅ ثبت انجام یک مورد دستی چک‌لیست")
def set_manual(data: ManualCheckIn, db: db_dependency, user: user_dependency, key: str = Path(pattern=r"^[a-z_]{3,48}$")):
    return _call(readiness_service.set_manual, db, user, key, data.done, data.note)


@readiness.get("/import/{kind}/template", summary="📄 قالب اکسل ورود محل‌ها یا موجودی اول دوره",
               response_class=Response, responses={200: {"content": {XLSX: {}}}})
def import_template(db: db_dependency, user: user_dependency, kind: Literal["locations", "opening"] = Path()):
    content = _call(migration_io.template, db, user, kind)
    name = "Pasineh_Locations_Template.xlsx" if kind == "locations" else "Pasineh_Opening_Balance_Template.xlsx"
    return Response(content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"',
                                                       "Access-Control-Expose-Headers": "Content-Disposition"})


@readiness.post("/import/{kind}", response_model=DataImportReport,
                summary="📥 ورود محل‌ها یا موجودی اول دوره: پیش‌نمایش (dry_run) و ثبت نهایی همه یا هیچ")
async def import_data(db: db_dependency, user: user_dependency, file: UploadFile,
                      kind: Literal["locations", "opening"] = Path(), dry_run: bool = Form(True)):
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="حجم فایل حداکثر ۱۰ مگابایت است.")
    fn = migration_io.import_locations if kind == "locations" else migration_io.import_opening
    return _call(fn, db, user, content, dry_run=dry_run)
