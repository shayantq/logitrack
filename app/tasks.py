"""
تسک‌های پس‌زمینه (Celery Tasks)
این توابع در کانتینر celery_worker اجرا می‌شوند، نه در کانتینر web — یعنی
تولید یک گزارش سنگین (اکسل یا PDF) هرگز درخواست‌های دیگر کاربران را کند
نمی‌کند.

چون worker یک پردازش کاملاً جدا از FastAPI است، خودش یک Session مستقل
دیتابیس می‌سازد (SessionLocal) و نتیجه نهایی (فایل، به‌صورت base64) را
به‌عنوان خروجی task برمی‌گرداند. Celery خودش این خروجی را در Redis
(result backend) ذخیره می‌کند و روتر گزارشات بعداً آن را از آنجا می‌خواند.
"""
import io
import logging
import os
import base64
import pandas as pd

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import arabic_reshaper
from bidi.algorithm import get_display

from sqlalchemy.orm import joinedload, selectinload

from app.celery_app import celery_app
from app.core.tenancy import set_tenant
from app.database import SessionLocal
from app.models import Product, Order, Inventory
from app.services import notification_service
from app.services.order_service import STATUS_LABELS, expire_overdue_orders
from app.services.spreadsheet_safety import neutralize_workbook

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# راه‌اندازی فونت فارسی برای PDF (فقط یک‌بار در زمان import این ماژول)
# ---------------------------------------------------------------------------
_FONT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "assets", "fonts", "Vazirmatn-Regular.ttf")
if not os.path.exists(_FONT_PATH):
    _FONT_PATH = os.path.join(os.path.dirname(__file__), "assets", "fonts", "Vazirmatn-Regular.ttf")
pdfmetrics.registerFont(TTFont("Vazirmatn", _FONT_PATH))


def _rtl(text) -> str:
    """متن فارسی را برای نمایش صحیح (حروف به‌هم‌چسبیده + راست‌به‌چپ) در PDF آماده می‌کند."""
    if text is None:
        return ""
    reshaped = arabic_reshaper.reshape(str(text))
    return get_display(reshaped)


def _dataframe_to_base64_xlsx(df: pd.DataFrame, sheet_name: str) -> str:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
        neutralize_workbook(writer.book)
        worksheet = writer.sheets[sheet_name]
        for col in worksheet.columns:
            max_len = max((len(str(cell.value or "")) for cell in col), default=10)
            worksheet.column_dimensions[col[0].column_letter].width = max(max_len + 5, 12)
    output.seek(0)
    return base64.b64encode(output.read()).decode("utf-8")


def _tenant_session(organization_id: int):
    """Session محدود به یک سازمان — گزارش هر سازمان فقط داده‌های خودش را دارد."""
    db = SessionLocal()
    set_tenant(db, organization_id)
    return db


def _inventory_rows(db, warehouse_id=None):
    """(کالا، موجودی) برای گزارش‌ها؛ اگر warehouse_id داده شود فقط کالاها و موجودی همان انبار."""
    products = db.query(Product).options(selectinload(Product.inventories)).order_by(Product.id).all()
    rows = []
    for p in products:
        invs = p.inventories if warehouse_id is None else [i for i in p.inventories if i.warehouse_id == warehouse_id]
        if warehouse_id is not None and not invs:
            continue
        rows.append((p, sum(inv.quantity or 0 for inv in invs)))
    return rows


def _orders_with_relations(db):
    return db.query(Order).options(
        joinedload(Order.vehicle), joinedload(Order.customer), selectinload(Order.items),
    ).order_by(Order.id).all()


def _items_summary(order) -> str:
    return "، ".join(f"{item.product_name} ×{item.quantity}" for item in order.items) or "—"


def _destination(order) -> str:
    return " / ".join(part for part in (order.destination_province, order.destination_city) if part)


def _build_pdf_base64(title: str, headers: list, rows: list) -> str:
    """یک PDF فارسی (راست‌به‌چپ، با فونت Vazirmatn) از عنوان و جدول می‌سازد."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=1.5 * cm, bottomMargin=1.5 * cm)

    title_style = ParagraphStyle(name="PersianTitle", fontName="Vazirmatn", fontSize=16, alignment=1, spaceAfter=14)
    elements = [Paragraph(_rtl(title), title_style), Spacer(1, 10)]

    table_data = [[_rtl(h) for h in headers]] + [[_rtl(c) for c in row] for row in rows]
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Vazirmatn"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(table)

    doc.build(elements)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# تسک‌های اکسل (از فاز ۲)
# ---------------------------------------------------------------------------

@celery_app.task(name="tasks.generate_inventory_excel")
def generate_inventory_excel_task(organization_id, warehouse_id=None):
    db = _tenant_session(organization_id)
    try:
        data = []
        for index, (p, stock) in enumerate(_inventory_rows(db, warehouse_id), start=1):
            data.append({
                "ردیف": index, "کد شناسه (SKU)": p.sku, "نام کالا": p.name,
                "موجودی فعلی": stock, "وزن واحد (کیلوگرم)": p.weight_kg, "قیمت واحد": p.price,
            })
        df = pd.DataFrame(data) if data else pd.DataFrame(
            columns=["ردیف", "کد شناسه (SKU)", "نام کالا", "موجودی فعلی", "وزن واحد (کیلوگرم)", "قیمت واحد"]
        )
        return {
            "organization_id": organization_id,
            "filename": "Pasineh_Inventory.xlsx",
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "content_b64": _dataframe_to_base64_xlsx(df, "موجودی انبار")
        }
    finally:
        db.close()


@celery_app.task(name="tasks.generate_orders_excel")
def generate_orders_excel_task(organization_id):
    db = _tenant_session(organization_id)
    try:
        data = []
        columns = ["ردیف", "کد پیگیری", "تاریخ ثبت", "مشتری", "موبایل", "اقلام", "تعداد کل", "وزن کل (کیلوگرم)",
                   "مبلغ کل", "استان / شهر مقصد", "نشانی", "وضعیت", "خودرو", "اولویت"]
        for index, o in enumerate(_orders_with_relations(db), start=1):
            data.append(dict(zip(columns, [
                index, o.tracking_code, o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "",
                o.customer.name if o.customer else (o.recipient_name or "—"), o.recipient_mobile or "",
                _items_summary(o), o.total_quantity, o.total_weight_kg, o.total_price, _destination(o),
                o.destination_address or "", STATUS_LABELS.get(o.status, o.status),
                o.vehicle.license_plate if o.vehicle else "—", "بله" if o.priority else "خیر",
            ], strict=False)))
        df = pd.DataFrame(data) if data else pd.DataFrame(columns=columns)
        return {
            "organization_id": organization_id,
            "filename": "Pasineh_Orders.xlsx",
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "content_b64": _dataframe_to_base64_xlsx(df, "سفارشات")
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# تسک‌های PDF فارسی (جدید) — کاملاً سمت سرور و ناهمگام، با فونت Vazirmatn
# ---------------------------------------------------------------------------

@celery_app.task(name="tasks.generate_inventory_pdf")
def generate_inventory_pdf_task(organization_id, warehouse_id=None):
    db = _tenant_session(organization_id)
    try:
        rows = [[p.sku, p.name, stock, p.weight_kg, p.price] for p, stock in _inventory_rows(db, warehouse_id)]
        content_b64 = _build_pdf_base64(
            "گزارش موجودی انبار پسینه",
            ["SKU", "نام کالا", "موجودی", "وزن (کیلوگرم)", "قیمت"],
            rows
        )
        return {"organization_id": organization_id, "filename": "Pasineh_Inventory.pdf", "content_type": "application/pdf", "content_b64": content_b64}
    finally:
        db.close()


@celery_app.task(name="tasks.generate_orders_pdf")
def generate_orders_pdf_task(organization_id):
    db = _tenant_session(organization_id)
    try:
        rows = []
        for o in _orders_with_relations(db):
            rows.append([
                o.tracking_code, _items_summary(o), o.total_quantity, _destination(o),
                o.vehicle.license_plate if o.vehicle else "—", STATUS_LABELS.get(o.status, o.status),
            ])
        content_b64 = _build_pdf_base64(
            "گزارش سفارشات پسینه",
            ["کد پیگیری", "اقلام", "تعداد", "مقصد", "خودرو", "وضعیت"],
            rows
        )
        return {"organization_id": organization_id, "filename": "Pasineh_Orders.pdf", "content_type": "application/pdf", "content_b64": content_b64}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# بررسی خودکار دوره‌ای موجودی رو‌به‌اتمام (Celery Beat — بدون نیاز به باز
# کردن دستی صفحه انبار). طبق زمان‌بندی celery_app.py هر ساعت اجرا می‌شود.
# ---------------------------------------------------------------------------

@celery_app.task(name="tasks.check_low_stock")
def check_low_stock_task():
    """
    هر ردیف موجودی (هر کالا در هر انبار) جداگانه با حد آستانه خودش سنجیده
    می‌شود. کالایی که کاملاً تمام شده (موجودی ۰) هم اعلان می‌گیرد.
    این تسک سیستمی است و برای همه سازمان‌ها اجرا می‌شود؛ هر اعلان به سازمان
    همان ردیف موجودی تعلق می‌گیرد.
    """
    db = SessionLocal()
    created_count = 0
    try:
        inventories = db.query(Inventory).options(
            joinedload(Inventory.product), joinedload(Inventory.warehouse)
        ).all()
        for inv in inventories:
            # فقط کالایی که قبلاً بالای حد آستانه بوده و حالا به آن رسیده (نه کالایی که از اول کم بوده)؛
            # هر دور کمبود یک‌بار (low_alerted) — معمولاً همان لحظه خروج کالا در دفتر گردش اعلان ساخته شده است
            if notification_service.low_stock(db, inv):
                created_count += 1
        notification_service.purge_old(db)
        db.commit()
        return {"checked_inventories": len(inventories), "notifications_created": created_count}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# انقضای خودکار سفارش‌هایی که بازه تحویلشان گذشته (Celery Beat، هر ساعت)
# ---------------------------------------------------------------------------

@celery_app.task(name="tasks.expire_overdue_orders")
def expire_overdue_orders_task():
    """سیستمی و برای همه سازمان‌ها: موجودی برمی‌گردد، خودرو آزاد و تاریخچه ثبت می‌شود."""
    db = SessionLocal()
    try:
        return {"expired_orders": expire_overdue_orders(db)}
    finally:
        db.close()


@celery_app.task(name="tasks.refresh_current_prices")
def refresh_current_prices_task():
    """قیمت‌های تاریخ‌داری که امروز شروع می‌شوند در قیمت فعلی کالاها (کش) قرار گیرند — همه سازمان‌ها."""
    from app.services import catalog_service
    db = SessionLocal()
    try:
        return {"updated_products": catalog_service.refresh_all_cached_prices(db)}
    finally:
        db.close()


@celery_app.task(name="tasks.recalculate_reorder_points")
def recalculate_reorder_points_task():
    """هر شب: نقطه سفارش اقلام «خودکار» از تقاضای تازه دوباره محاسبه می‌شود — هر سازمان با Session جدای خودش."""
    from app.models import Organization
    from app.services import replenishment_service
    db = SessionLocal()
    try:
        org_ids = [o.id for o in db.query(Organization.id).filter(Organization.is_active.is_(True)).all()]
    finally:
        db.close()
    total = 0
    for org_id in org_ids:
        db = _tenant_session(org_id)
        try:
            total += replenishment_service.recalculate(db, org_id)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("محاسبه نقطه سفارش سازمان %s ناموفق بود", org_id)
        finally:
            db.close()
    return {"organizations": len(org_ids), "inventories": total}


def _each_organization(work, label: str) -> dict:
    from app.models import Organization
    db = SessionLocal()
    try:
        org_ids = [o.id for o in db.query(Organization.id).filter(Organization.is_active.is_(True)).all()]
    finally:
        db.close()
    done = 0
    for org_id in org_ids:
        db = _tenant_session(org_id)
        try:
            work(db)
            done += 1
        except Exception:
            db.rollback()
            logger.exception("%s سازمان %s ناموفق بود", label, org_id)
        finally:
            db.close()
    return {"organizations": done}


@celery_app.task(name="tasks.check_replenishment_rules")
def check_replenishment_rules_task():
    """هر ساعت (پشتیبان بررسی پس از هر برداشت): محل‌های برداشت زیر حداقل وظیفه تأمین مجدد می‌گیرند."""
    from app.models import ReplenishmentRule
    from app.services import replenishment_rule_service

    def work(db):
        ids = {lid for (lid,) in db.query(ReplenishmentRule.location_id).filter(ReplenishmentRule.is_active.is_(True)).all()}
        replenishment_rule_service.check(db, None, ids)
        db.commit()
    return _each_organization(work, "تأمین مجدد")


@celery_app.task(name="tasks.classify_abc")
def classify_abc_task():
    """هر هفته: طبقه‌بندی ABC کالاها از ارزش مصرف یک سال اخیر (مبنای دوره شمارش)."""
    from app.services import replenishment_rule_service
    return _each_organization(lambda db: replenishment_rule_service.classify(db, None), "طبقه‌بندی ABC")


# ---------------------------------------------------------------------------
# گزارش با برند سازمان (مرحله ۱۴): موجودی، سفارش‌ها، دفتر گردش، مالی حمل‌ونقل — اکسل یا PDF
# ---------------------------------------------------------------------------
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def build_report_file(db, organization_id: int, user, report: str, fmt: str, params: dict) -> dict:
    """هم در Celery و هم در تست‌ها استفاده می‌شود."""
    from datetime import date as _date
    from app.services import report_builder, report_data
    clean = {k: (_date.fromisoformat(v) if k.startswith("date_") and isinstance(v, str) else v) for k, v in (params or {}).items() if v not in (None, "")}
    rep = report_data.BUILDERS[report](db, user, **clean)
    org = report_data.organization(db, organization_id)
    now = report_data.now_local()
    branding = report_builder.Branding.of(org, user)
    stamp = report_builder.jalali(now).replace("/", "-")
    if fmt == "pdf":
        content, ext, ctype = report_builder.to_pdf(rep, branding, now), "pdf", "application/pdf"
    elif fmt == "csv":
        content, ext, ctype = report_builder.to_csv(rep, branding, now), "csv", "text/csv; charset=utf-8"
    else:
        content, ext, ctype = report_builder.to_excel(rep, branding, now), "xlsx", XLSX_TYPE
    return {"organization_id": organization_id, "filename": f"{rep.filename}_{stamp}.{ext}", "content_type": ctype,
            "content_b64": base64.b64encode(content).decode("utf-8")}


@celery_app.task(name="tasks.generate_report")
def generate_report_task(organization_id, user_id, report, fmt, params=None):
    from app.models import User
    db = _tenant_session(organization_id)
    try:
        return build_report_file(db, organization_id, db.get(User, user_id), report, fmt, params or {})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# پیامک و ایمیل خودکار (app/services/messaging.py) — با چند تلاش دوباره اگر سرویس بیرونی موقتاً جواب نداد
# ---------------------------------------------------------------------------
@celery_app.task(name="tasks.send_sms", autoretry_for=(Exception,), retry_backoff=30, max_retries=3)
def send_sms_task(mobile: str, text: str):
    from app.services import messaging
    return messaging.deliver_sms(mobile, text)


@celery_app.task(name="tasks.send_email", autoretry_for=(Exception,), retry_backoff=30, max_retries=3)
def send_email_task(to: str, subject: str, text: str):
    from app.services import messaging
    return messaging.deliver_email(to, subject, text)


@celery_app.task(name="tasks.reset_demo")
def reset_demo_task():
    """نسخه نمایشی خصوصی هر ۳۰ دقیقه از روی قالب از نو ساخته می‌شود (تا DEMO_ACCESS_TOKEN تنظیم نشود، کاری نمی‌کند)."""
    from app import demo_db
    from app.core import demo
    if not demo.enabled():
        return {"demo": "disabled"}
    demo_db.reset()
    return {"demo": "reset"}
