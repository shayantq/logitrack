"""
آمادگی راه‌اندازی و انتقال (فصل‌های ۳۴ و ۳۵): بررسی‌های خودکار سلامت داده + موارد دستی چک‌لیست با ثبت «کی و چرا».

بررسی خودکار فقط می‌خواند (هیچ داده‌ای را عوض نمی‌کند): نسخه دیتابیس، سازگاری دفتر گردش، انبار و محل، کاتالوگ
(بارکد، بها، ابعاد)، موجودی اول دوره، کاربران و دسترسی، کارهای باز، برچسب محل‌ها، کالای منقضی و ناوگان.
موارد دستی (آموزش، تأیید بکاپ، اجرای موازی، امضای شروع) در cutover_checks می‌مانند و هر تغییرشان در گزارش فعالیت ثبت می‌شود.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.wms import AVAILABLE
from app.models import (
    CutoverCheck, InboundReceipt, LabelPrint, Location, Product, ProductPrice, PutawayTask, StockBalance, StockMovement,
    Stocktake, User, Vehicle, Warehouse,
)
from app.services import audit_service, catalog_service, location_service, permission_service, stock_ledger
from app.services.exceptions import ConflictError, NotFoundError

MANUAL_ITEMS = (
    ("permissions_reviewed", "مجوزهای نقش‌ها بازبینی و تأیید شد", "سیستم و دسترسی"),
    ("training_done", "آموزش کاربران انبار و رانندگان انجام شد", "آموزش"),
    ("opening_signed", "موجودی اول دوره با شمارش فیزیکی تطبیق و امضا شد", "داده"),
    ("labels_applied", "برچسب محل‌ها و کالاها چاپ و نصب شد", "انبار"),
    ("backup_verified", "بکاپ شبانه بازیابی آزمایشی شد (scripts/verify-backup.sh)", "زیرساخت"),
    ("parallel_run", "یک دوره اجرای موازی با سیستم قبلی بدون مغایرت گذشت", "انتقال"),
    ("go_live_signoff", "مدیر سازمان شروع رسمی کار با سامانه را تأیید کرد", "انتقال"),
)
MANUAL_LABELS = {k: (label, group) for k, label, group in MANUAL_ITEMS}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _check(key, group, label, status, detail, path=None) -> dict:
    return {"key": key, "group": group, "label": label, "status": status, "detail": detail, "path": path}


def _schema(db: Session) -> dict:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        root = Path(__file__).resolve().parents[2]
        head = ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_current_head()
        current = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        return _check("schema", "زیرساخت", "نسخه دیتابیس", "warn", "نسخه دیتابیس در این محیط قابل بررسی نیست.")
    if current == head:
        return _check("schema", "زیرساخت", "نسخه دیتابیس", "pass", f"به‌روز ({current})")
    return _check("schema", "زیرساخت", "نسخه دیتابیس", "fail", f"دیتابیس روی {current} است ولی آخرین نسخه {head} است.")


def checks(db: Session, user: User) -> list[dict]:
    items = [_schema(db)]
    mismatches = stock_ledger.find_mismatches(db)
    items.append(_check("ledger", "داده", "سازگاری دفتر گردش کالا", "pass" if not mismatches else "fail",
                        "مانده همه ردیف‌ها با گردش‌ها برابر است." if not mismatches else f"{len(mismatches)} ناسازگاری پیدا شد.",
                        "/app/ledger"))

    warehouses = db.query(Warehouse).filter(Warehouse.is_active.is_not(False)).all()
    with_locations = {wid for (wid,) in db.query(Location.warehouse_id).distinct().all()}
    no_loc = [w.name for w in warehouses if w.id not in with_locations]
    items.append(_check("warehouses", "انبار", "انبارها و محل‌بندی",
                        "fail" if not warehouses else "warn" if no_loc else "pass",
                        "هیچ انبار فعالی تعریف نشده است." if not warehouses else
                        f"بدون محل‌بندی: {'، '.join(no_loc[:4])}" if no_loc else f"{len(warehouses)} انبار با محل‌بندی",
                        "/app/locations"))

    products = db.query(Product).filter(Product.is_active.is_not(False)).all()
    no_barcode = sum(1 for p in products if not p.barcode)
    costed = {pid for (pid,) in db.query(ProductPrice.product_id).filter(ProductPrice.cost_price.is_not(None)).distinct().all()}
    no_cost = sum(1 for p in products if p.id not in costed)
    no_dims = sum(1 for p in products if not (p.length_cm and p.width_cm and p.height_cm))
    items.append(_check("catalog", "داده", "کاتالوگ کالا", "fail" if not products else "warn" if no_barcode else "pass",
                        "کاتالوگ خالی است." if not products else
                        f"{len(products)} کالا؛ بدون بارکد: {no_barcode}", "/app/inventory"))
    items.append(_check("costs", "داده", "بهای تمام‌شده برای ارزش‌گذاری", "pass" if products and not no_cost else "warn",
                        f"{no_cost} کالا بهای تمام‌شده ندارد (ارزش‌گذاری با قیمت فروش تخمین زده می‌شود)." if no_cost else
                        "همه کالاها بهای تمام‌شده دارند.", "/app/inventory"))
    items.append(_check("dimensions", "داده", "ابعاد کالا برای ظرفیت محل و خودرو", "pass" if not no_dims else "warn",
                        f"{no_dims} کالا ابعاد ندارد." if no_dims else "همه کالاها ابعاد دارند.", "/app/inventory"))

    opening = db.query(StockMovement.id).filter(StockMovement.movement_type.in_(("initial", "receipt"))).first()
    items.append(_check("opening", "داده", "موجودی اول دوره", "pass" if opening else "fail",
                        "موجودی ثبت شده است." if opening else "هنوز هیچ موجودی ثبت نشده؛ از «ورود موجودی اول دوره» استفاده کنید.",
                        "/app/readiness"))

    users = db.query(User).filter(User.is_active.is_not(False)).all()
    roles = {getattr(u.role, "value", u.role) for u in users}
    no_mobile = sum(1 for u in users if not u.mobile)
    items.append(_check("users", "سیستم و دسترسی", "کاربران و نقش‌ها", "pass" if "warehouse_manager" in roles else "warn",
                        f"{len(users)} کاربر فعال؛ بدون موبایل (بازیابی رمز): {no_mobile}" if "warehouse_manager" in roles else
                        "هنوز مدیر انباری تعریف نشده است.", "/app/users"))

    week_ago = _now() - timedelta(days=7)
    stale_receipts = db.query(InboundReceipt).filter(InboundReceipt.status.in_(("open", "receiving")),
                                                     InboundReceipt.created_at < week_ago).count()
    open_tasks = db.query(PutawayTask).filter(PutawayTask.status.in_(("open", "partial"))).count()
    active_counts = db.query(Stocktake).filter(Stocktake.status.in_(("counting", "review"))).count()
    busy = stale_receipts or active_counts
    items.append(_check("open_work", "عملیات", "کارهای باز پیش از شروع",
                        "warn" if busy else "pass",
                        f"رسید باز قدیمی: {stale_receipts}، جانمایی باز: {open_tasks}، انبارگردانی فعال: {active_counts}",
                        "/app/receipts"))

    leaves = set()
    for w in warehouses:
        leaves |= set(location_service.leaf_ids(db, w.id)) if w.id in with_locations else set()
    labeled = {tid for (tid,) in db.query(LabelPrint.target_id).filter(LabelPrint.label_type == "location").distinct().all()}
    covered = len(leaves & labeled)
    items.append(_check("labels", "انبار", "برچسب محل‌ها", "pass" if leaves and covered >= 0.8 * len(leaves) else "warn",
                        f"{covered} از {len(leaves)} محل برچسب چاپ‌شده دارد." if leaves else "محلی برای برچسب نیست.",
                        "/app/labels"))

    today = catalog_service.today_local()
    expired = int(db.query(func.coalesce(func.sum(StockBalance.quantity), 0)).filter(
        StockBalance.stock_status == AVAILABLE, StockBalance.expiry_date.is_not(None), StockBalance.expiry_date < today).scalar() or 0)
    items.append(_check("expired", "انبار", "کالای منقضی در موجودی سالم", "pass" if not expired else "warn",
                        f"{expired} واحد منقضی هنوز «سالم» است؛ تعیین تکلیف کنید." if expired else "کالای منقضی سالمی نیست.",
                        "/app/valuation"))

    vehicles = db.query(Vehicle).filter(Vehicle.status.notin_(("inactive", "maintenance"))).count()
    items.append(_check("fleet", "عملیات", "ناوگان ارسال", "pass" if vehicles else "warn",
                        f"{vehicles} خودروی فعال" if vehicles else "خودروی فعالی برای ارسال نیست.", "/app/vehicles"))
    return items


def overview(db: Session, user: User) -> dict:
    permission_service.ensure(db, user, "cutover.manage")
    auto = checks(db, user)
    stored = {c.item_key: c for c in db.query(CutoverCheck).all()}
    names = {u.id: u.full_name or u.username for u in db.query(User).filter(
        User.id.in_({c.updated_by_id for c in stored.values()} or {-1})).all()}
    manual = [{"key": k, "label": label, "group": group, "done": bool(stored.get(k) and stored[k].done),
               "note": stored[k].note if k in stored else None, "updated_at": stored[k].updated_at if k in stored else None,
               "updated_by": names.get(stored[k].updated_by_id) if k in stored else None}
              for k, label, group in MANUAL_ITEMS]
    passed = sum(1 for c in auto if c["status"] == "pass") + sum(1 for m in manual if m["done"])
    total = len(auto) + len(manual)
    blockers = [c["label"] for c in auto if c["status"] == "fail"]
    return {"checks": auto, "manual": manual, "score": round(100 * passed / total), "passed": passed, "total": total,
            "blockers": blockers, "ready": not blockers and all(m["done"] for m in manual), "checked_at": _now()}


def set_manual(db: Session, user: User, key: str, done: bool, note: str | None) -> dict:
    permission_service.ensure(db, user, "cutover.manage")
    if key not in MANUAL_LABELS:
        raise NotFoundError("مورد چک‌لیست یافت نشد.")
    if key == "go_live_signoff" and done:
        if getattr(user.role, "value", user.role) != "org_admin":
            raise ConflictError("تأیید شروع رسمی با ادمین سازمان است.")
        pending = [MANUAL_LABELS[k][0] for k, *_ in MANUAL_ITEMS if k != key and not (
            (row := db.query(CutoverCheck).filter(CutoverCheck.item_key == k).first()) and row.done)]
        if pending:
            raise ConflictError(f"پیش از امضای شروع، این موارد را تکمیل کنید: {pending[0]}")
    row = db.query(CutoverCheck).filter(CutoverCheck.item_key == key).first()
    if row is None:
        row = CutoverCheck(organization_id=user.organization_id, item_key=key)
        db.add(row)
    row.done, row.note, row.updated_by_id, row.updated_at = done, (note or "").strip() or None, user.id, _now()
    audit_service.log(db, user, "cutover.check", f"چک‌لیست راه‌اندازی: «{MANUAL_LABELS[key][0]}» {'انجام شد' if done else 'برگشت خورد'}",
                      target_type="cutover", target_label=key, reason=row.note)
    db.commit()
    return overview(db, user)
