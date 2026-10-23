"""مرحله ۱۳: کاتالوگ کالا — مشخصات، تنوع، قیمت تاریخ‌دار با یارانه، ورود و خروج اکسل."""
from typing import Literal

from fastapi import APIRouter, Form, HTTPException, Path, UploadFile
from fastapi.responses import Response

from app.database import db_dependency
from app.dependencies import user_dependency
from app.schemas.catalog import ImportReport, PriceIn, ProductDetail, ProductUpdate, SupplierLinkIn, UomIn, VariantIn
from app.services import catalog_io, catalog_service
from app.services.exceptions import DomainError
from app.services import audit_service
from app.services.report_builder import jalali
from app.core.iran import fa_digits

router = APIRouter(prefix="/catalog", tags=["🏷️ کاتالوگ کالا"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_UPLOAD = 10 * 1024 * 1024


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


def _xlsx(content: bytes, filename: str) -> Response:
    return Response(content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/categories", response_model=list[str], summary="📂 گروه‌های کالا")
def categories(db: db_dependency, user: user_dependency):
    return catalog_service.categories(db)


@router.get("/template", summary="📄 قالب اکسل کاتالوگ (با راهنما و نمونه)")
def template(db: db_dependency, user: user_dependency):
    return _xlsx(catalog_io.template(db), "Pasineh_Catalog_Template.xlsx")


@router.get("/export", summary="📥 خروجی اکسل کل کاتالوگ (قابل ویرایش و ورود دوباره)")
def export(db: db_dependency, user: user_dependency):
    return _xlsx(catalog_io.export(db, user), "Pasineh_Catalog.xlsx")


@router.post("/import", response_model=ImportReport, summary="📤 ورود کاتالوگ از اکسل (پیش‌نمایش یا ثبت نهایی)")
async def import_catalog(db: db_dependency, user: user_dependency, file: UploadFile,
                         stock_mode: Literal["ignore", "set", "add"] = Form("ignore"), dry_run: bool = Form(True)):
    content = await file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise HTTPException(status_code=400, detail="حجم فایل نباید بیشتر از ۱۰ مگابایت باشد.")
    report = _call(catalog_io.import_catalog, db, user, content, stock_mode=stock_mode, dry_run=dry_run)
    if report["applied"] if isinstance(report, dict) else report.applied:
        r = report if isinstance(report, dict) else report.model_dump()
        audit_service.record(db, user, "catalog.import",
                             f"ورود کاتالوگ از اکسل «{file.filename}»: {fa_digits(str(r['create']))} کالای جدید، {fa_digits(str(r['update']))} به‌روزرسانی",
                             details={"rows": r["rows"], "create": r["create"], "update": r["update"], "stock_mode": stock_mode})
    return report


@router.get("/products/{product_id}", response_model=ProductDetail, summary="📄 مشخصات کامل، قیمت‌ها، تنوع‌ها و موجودی")
def product_detail(db: db_dependency, user: user_dependency, product_id: int = Path(gt=0)):
    return _call(catalog_service.detail, db, user, product_id)


@router.put("/products/{product_id}", response_model=ProductDetail, summary="✏️ ویرایش مشخصات کالا")
def update_product(data: ProductUpdate, db: db_dependency, user: user_dependency, product_id: int = Path(gt=0)):
    result = _call(catalog_service.update, db, user, product_id, data.model_dump(exclude_unset=True))
    audit_service.record(db, user, "catalog.update", f"مشخصات کالای «{result['name']}» ویرایش شد", target_type="product",
                         target_id=product_id, target_label=result["sku"])
    return result


@router.put("/products/{product_id}/uoms", response_model=ProductDetail, summary="📏 واحدهای فرعی کالا (جایگزینی کامل فهرست)")
def set_uoms(data: list[UomIn], db: db_dependency, user: user_dependency, product_id: int = Path(gt=0)):
    result = _call(catalog_service.set_uoms, db, user, product_id, [u.model_dump() for u in data])
    audit_service.record(db, user, "catalog.uoms", f"واحدهای فرعی کالای «{result['name']}» به‌روز شد", target_type="product",
                         target_id=product_id, target_label=result["sku"], details={"uoms": [f"{u.name}={u.factor}" for u in data]})
    return result


@router.put("/products/{product_id}/suppliers", response_model=ProductDetail, summary="🤝 تأمین‌کننده‌های کالا (جایگزینی کامل فهرست)")
def set_suppliers(data: list[SupplierLinkIn], db: db_dependency, user: user_dependency, product_id: int = Path(gt=0)):
    result = _call(catalog_service.set_suppliers, db, user, product_id, [s.model_dump() for s in data])
    audit_service.record(db, user, "catalog.suppliers", f"تأمین‌کننده‌های کالای «{result['name']}» به‌روز شد",
                         target_type="product", target_id=product_id, target_label=result["sku"])
    return result


@router.post("/products/{product_id}/prices", response_model=ProductDetail, summary="💲 قیمت جدید از یک تاریخ به بعد")
def add_price(data: PriceIn, db: db_dependency, user: user_dependency, product_id: int = Path(gt=0)):
    result = _call(catalog_service.add_price, db, user, product_id, **data.model_dump())
    subsidy = f" با {data.subsidy_percent:g}٪ یارانه" if data.subsidy_percent else ""
    audit_service.record(db, user, "catalog.price", f"قیمت «{result['name']}» از {fa_digits(jalali(data.effective_from))}: "
                         f"{fa_digits(f'{round(data.base_price):,}'.replace(',', '٬'))} ریال{fa_digits(subsidy)}", target_type="product", target_id=product_id, target_label=result["sku"])
    return result


@router.delete("/prices/{price_id}", response_model=ProductDetail, summary="🗑️ حذف قیمت (آینده، یا استفاده‌نشده)")
def delete_price(db: db_dependency, user: user_dependency, price_id: int = Path(gt=0)):
    result = _call(catalog_service.delete_price, db, user, price_id)
    audit_service.record(db, user, "catalog.price_delete", f"یک قیمت تاریخ‌دار کالای «{result['name']}» حذف شد",
                         target_type="product", target_id=result["id"], target_label=result["sku"])
    return result


@router.post("/products/{product_id}/variants", response_model=ProductDetail, status_code=201,
             summary="🧬 تنوع جدید (کد، مبدأ و قیمت جدید با مشخصات کالای اصلی)")
def create_variant(data: VariantIn, db: db_dependency, user: user_dependency, product_id: int = Path(gt=0)):
    return _call(catalog_service.create_variant, db, user, product_id, data.model_dump())
