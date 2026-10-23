"""
انبارهای سازمان: فهرست برای همه کاربران سازمان، ساخت/ویرایش/حذف فقط برای ادمین سازمان (مرحله ۱۰).
نوع انبار، کد یکتا و سلسله‌مراتب (انبار مادر) — قواعد در app/services/warehouse_service.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import func

from app.core import geo
from app.database import db_dependency
from app.dependencies import require_role, user_dependency
from app.models import Inventory, Order, RoleEnum, StockMovement, User, Warehouse
from app.schemas.route import GeoCity, WarehouseIn, WarehouseOut
from app.services import audit_service, warehouse_service
from app.services.exceptions import DomainError

router = APIRouter(
    prefix="/warehouses",
    tags=["🏬 انبارها"]
)
org_admin = require_role([RoleEnum.ORG_ADMIN])


def _out(db, warehouse: Warehouse, names: dict[int, str] | None = None, depths: dict[int, int] | None = None) -> WarehouseOut:
    city, _ = geo.resolve(warehouse.city or warehouse.location, warehouse.province)
    products = db.query(func.count(func.distinct(Inventory.product_id))).filter(Inventory.warehouse_id == warehouse.id).scalar() or 0
    managers = db.query(func.count(User.id)).filter(User.warehouse_id == warehouse.id).scalar() or 0
    kind = warehouse_service.type_of(warehouse)
    parent_name = (names or {}).get(warehouse.parent_id) if names is not None else (
        warehouse.parent.name if warehouse.parent_id and warehouse.parent else None)
    return WarehouseOut(id=warehouse.id, name=warehouse.name, location=warehouse.location, province=warehouse.province,
                        city=warehouse.city, on_map=city is not None, map_city=city.name if city else None,
                        products_count=products, managers_count=managers, code=warehouse.code, type=kind.code,
                        type_label=kind.label, parent_id=warehouse.parent_id, parent_name=parent_name,
                        depth=(depths or {}).get(warehouse.id, 0), is_active=warehouse.is_active is not False,
                        holds_stock=kind.holds_stock, ships_orders=kind.ships_orders,
                        on_hand=warehouse_service.on_hand(db, warehouse.id))


def _get(db, warehouse_id: int) -> Warehouse:
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "انبار یافت نشد.")
    return warehouse


def _ensure_unique_name(db, name: str, exclude_id: int | None = None) -> None:
    query = db.query(Warehouse).filter(func.lower(Warehouse.name) == name.lower())
    if exclude_id:
        query = query.filter(Warehouse.id != exclude_id)
    if query.first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "انباری با این نام از قبل وجود دارد.")


def _validated(db, data: WarehouseIn, warehouse: Warehouse | None = None) -> dict:
    try:
        return warehouse_service.validate(db, data.model_dump(), warehouse)
    except DomainError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get("/", response_model=list[WarehouseOut], summary="📋 دریافت لیست انبارها (به ترتیب درختی)")
def list_warehouses(db: db_dependency, user: user_dependency):
    warehouses = db.query(Warehouse).all()
    names = {w.id: w.name for w in warehouses}
    depths = warehouse_service.depth_map(warehouses)
    return [_out(db, w, names, depths) for w in warehouse_service.ordered_tree(warehouses)]


@router.get("/cities", response_model=list[GeoCity], summary="🗺️ شهرهای شناخته‌شده روی نقشه (برای انتخاب شهر انبار)")
def list_cities(user: user_dependency, province: str | None = None):
    return [GeoCity(name=c.name, province=c.province, capital=c.capital) for c in geo.cities_of(province)]


@router.post("/", response_model=WarehouseOut, status_code=status.HTTP_201_CREATED, summary="➕ ساخت انبار")
def create_warehouse(data: WarehouseIn, db: db_dependency, user=Depends(org_admin)):
    _ensure_unique_name(db, data.name)
    warehouse = Warehouse(**_validated(db, data))
    db.add(warehouse)
    db.flush()
    audit_service.log(db, user, "warehouse.create", f"انبار «{warehouse.name}» ({warehouse.code}) ساخته شد", target_type="warehouse",
                      target_id=warehouse.id, target_label=warehouse.name)
    db.commit()
    db.refresh(warehouse)
    return _out(db, warehouse)


@router.put("/{warehouse_id}", response_model=WarehouseOut, summary="✏️ ویرایش انبار")
def update_warehouse(data: WarehouseIn, db: db_dependency, warehouse_id: int = Path(gt=0), user=Depends(org_admin)):
    warehouse = _get(db, warehouse_id)
    _ensure_unique_name(db, data.name, warehouse.id)
    for key, value in _validated(db, data, warehouse).items():
        setattr(warehouse, key, value)
    audit_service.log(db, user, "warehouse.update", f"انبار «{warehouse.name}» ویرایش شد", target_type="warehouse",
                      target_id=warehouse.id, target_label=warehouse.name)
    db.commit()
    db.refresh(warehouse)
    return _out(db, warehouse)


@router.delete("/{warehouse_id}", status_code=status.HTTP_204_NO_CONTENT, summary="🗑️ حذف انبار خالی")
def delete_warehouse(db: db_dependency, warehouse_id: int = Path(gt=0), user=Depends(org_admin)):
    warehouse = _get(db, warehouse_id)
    if db.query(Inventory.id).filter(Inventory.warehouse_id == warehouse.id).first() or \
            db.query(StockMovement.id).filter(StockMovement.warehouse_id == warehouse.id).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "این انبار کالا یا سابقه گردش دارد؛ به‌جای حذف، آن را غیرفعال کنید.")
    if db.query(Order.id).filter(Order.warehouse_id == warehouse.id).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "از این انبار سفارش ارسال شده است؛ برای حفظ سوابق قابل حذف نیست.")
    if db.query(User.id).filter(User.warehouse_id == warehouse.id).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "مدیر انباری به این انبار متصل است؛ ابتدا او را به انبار دیگری منتقل کنید.")
    if db.query(Warehouse.id).filter(Warehouse.parent_id == warehouse.id).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "این انبار زیرمجموعه دارد؛ ابتدا انبارهای زیرمجموعه را جابه‌جا یا حذف کنید.")
    audit_service.log(db, user, "warehouse.delete", f"انبار «{warehouse.name}» حذف شد", target_type="warehouse",
                      target_id=warehouse.id, target_label=warehouse.name)
    db.delete(warehouse)
    db.commit()
