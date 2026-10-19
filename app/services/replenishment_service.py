"""
نقطه سفارش (ROP) با فرمول و برآورد سرمایه لازم برای خرید ماه‌های آینده.

فرمول نقطه سفارش (برای هر کالا در هر انبار):
    تقاضای روزانه d از دفتر گردش: خروج بابت سفارش منهای برگشت از سفارش، به تفکیک روز محلی ایران
    (روزهای بدون فروش صفر حساب می‌شوند؛ انتقال بین انبارها، ضایعات و اصلاحات تقاضا نیستند).
    d̄ = میانگین، σd = انحراف معیار تقاضای روزانه در بازه تاریخچه (پیش‌فرض ۹۰ روز)
    L = زمان تأمین (روز)، σL = انحراف معیار زمان تأمین، z = ضریب سطح خدمت (توزیع نرمال؛ ۹۵٪ ← ۱٫۶۴۵)
    موجودی اطمینان      SS  = z × √(L·σd² + d̄²·σL²)
    نقطه سفارش          ROP = ⌈d̄·L + SS⌉
    مقدار سفارش اقتصادی EOQ = √(2·D·S / H)  — D تقاضای سالانه، S هزینه هر بار سفارش، H هزینه نگهداری سالانه هر واحد
                         (اگر S یا بهای واحد نامشخص باشد: تقاضای «روزهای پوشش» = d̄ × cover_days)
    حداکثر موجودی       Max = ROP + مقدار سفارش

برآورد سرمایه (plan): تقاضای هر ماه شمسی آینده با هموارسازی نمایی دوگانه (Holt، روند میرا) روی تقاضای ماهانه
گذشته پیش‌بینی می‌شود؛ سپس سیاست (ROP، تا Max) روز‌به‌روز شبیه‌سازی می‌شود: هر وقت «موجودی + در راه» به نقطه سفارش
برسد سفارش خرید ثبت و پس از زمان تأمین وارد انبار می‌شود. مبلغ هر سفارش با بهای خرید همان روز (قیمت آینده ثبت‌شده
در کاتالوگ، وگرنه آخرین بها × تورم ماهانه) در ماهِ ثبت سفارش منظور می‌شود.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from statistics import NormalDist

from sqlalchemy.orm import Session, joinedload

from app.core.iran import fa_digits, gregorian_to_jalali, jalali_to_gregorian
from app.models import Inventory, Organization, Product, ProductPrice, StockMovement, User, Warehouse
from app.services import audit_service, dispatch_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError

MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]

DEFAULT_POLICY = {
    "lead_time_days": 7.0,          # زمان تأمین پیش‌فرض
    "lead_time_std_days": 2.0,      # نوسان زمان تأمین
    "service_level": 0.95,          # احتمال نبود کمبود در دوره تأمین
    "history_days": 90,             # بازه تاریخچه تقاضا برای نقطه سفارش
    "min_history_days": 14,         # کمتر از این، داده کافی نیست و عدد دستی می‌ماند
    "ordering_cost": 0.0,           # هزینه ثابت هر سفارش خرید (ریال) — برای EOQ
    "holding_rate": 0.25,           # هزینه نگهداری سالانه به نسبت بهای کالا (۲۵٪)
    "cover_days": 30,               # مقدار سفارش وقتی EOQ قابل محاسبه نیست
    "price_growth_monthly": 0.03,   # تورم ماهانه بهای خرید (برآورد سرمایه)
    "demand_growth_monthly": 0.0,   # رشد ماهانه تقاضا (سناریو)
}
POLICY_LIMITS = {
    "lead_time_days": (0, 365), "lead_time_std_days": (0, 120), "service_level": (0.5, 0.999),
    "history_days": (14, 730), "min_history_days": (7, 120), "ordering_cost": (0, 1e13), "holding_rate": (0, 2),
    "cover_days": (1, 365), "price_growth_monthly": (-0.5, 1), "demand_growth_monthly": (-0.5, 1),
}
DEMAND_TYPES = ("order_out", "order_return")
MAX_PLAN_MONTHS = 12


def _role(user: User) -> str:
    return getattr(user.role, "value", user.role)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today_local() -> date:
    return dispatch_service.to_local(_now()).date()


def _ensure_staff(user: User) -> None:
    if _role(user) not in ("org_admin", "warehouse_manager"):
        raise ForbiddenError("نقطه سفارش و برنامه خرید فقط برای ادمین سازمان و مدیر انبار است.")


def _ensure_admin(user: User) -> None:
    if _role(user) != "org_admin":
        raise ForbiddenError("این بخش فقط برای ادمین سازمان است.")


def _warehouse_scope(user: User, warehouse_id: int | None) -> int | None:
    """مدیر انبار فقط انبار خودش را می‌بیند."""
    if _role(user) == "warehouse_manager":
        if not user.warehouse_id:
            raise ForbiddenError("حساب شما به هیچ انباری متصل نیست.")
        return user.warehouse_id
    return warehouse_id


# ---------------------------------------------------------------------------
# سیاست انبار سازمان
# ---------------------------------------------------------------------------
def policy_of(org: Organization | None) -> dict:
    stored = (org.inventory_policy if org else None) or {}
    return {key: stored.get(key, default) for key, default in DEFAULT_POLICY.items()}


def get_policy(db: Session, user: User) -> dict:
    _ensure_staff(user)
    return policy_of(db.get(Organization, user.organization_id))


def update_policy(db: Session, user: User, data: dict) -> dict:
    _ensure_admin(user)
    org = db.get(Organization, user.organization_id)
    policy = policy_of(org)
    for key, value in data.items():
        if key not in DEFAULT_POLICY or value is None:
            continue
        low, high = POLICY_LIMITS[key]
        if not low <= value <= high:
            raise ConflictError(f"مقدار «{key}» خارج از محدوده مجاز است.")
        policy[key] = int(value) if isinstance(DEFAULT_POLICY[key], int) else float(value)
    if policy["min_history_days"] > policy["history_days"]:
        raise ConflictError("حداقل تاریخچه لازم نمی‌تواند از بازه تاریخچه بیشتر باشد.")
    org.inventory_policy = policy
    audit_service.log(db, user, "inventory.policy", "سیاست نقطه سفارش و برنامه خرید سازمان به‌روز شد", details=policy)
    recalculate(db, user.organization_id)
    db.commit()
    return policy


# ---------------------------------------------------------------------------
# تقاضا
# ---------------------------------------------------------------------------
def _local_day(dt: datetime) -> date:
    return dispatch_service.to_local(dispatch_service.to_utc_naive(dt)).date()


def daily_demand(db: Session, inventory_ids: list[int], start: date, end: date) -> dict[int, dict[date, float]]:
    """تقاضای خالص هر روز (خروج سفارش − برگشت) برای هر ردیف موجودی، فقط روزهای دارای گردش."""
    if not inventory_ids:
        return {}
    lo = dispatch_service.local_to_utc(datetime.combine(start, time.min))
    hi = dispatch_service.local_to_utc(datetime.combine(end + timedelta(days=1), time.min))
    rows = db.query(StockMovement.inventory_id, StockMovement.created_at, StockMovement.quantity_change) \
        .filter(StockMovement.inventory_id.in_(inventory_ids), StockMovement.movement_type.in_(DEMAND_TYPES),
                StockMovement.created_at >= lo, StockMovement.created_at < hi).all()
    out: dict[int, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    for inventory_id, created_at, change in rows:
        out[inventory_id][_local_day(created_at)] -= change      # خروج منفی است ← تقاضای مثبت
    return out


def _first_activity(db: Session, inventory_ids: list[int]) -> dict[int, date]:
    """اولین گردش هر ردیف موجودی — کالای تازه نباید با صفرهای قبل از ورودش «کم‌فروش» دیده شود."""
    from sqlalchemy import func
    if not inventory_ids:
        return {}
    rows = db.query(StockMovement.inventory_id, func.min(StockMovement.created_at)) \
        .filter(StockMovement.inventory_id.in_(inventory_ids)).group_by(StockMovement.inventory_id).all()
    return {inventory_id: _local_day(first) for inventory_id, first in rows if first}


def _series(by_day: dict[date, float], start: date, end: date) -> list[float]:
    """سری روزانه کامل (روزهای بدون فروش صفر؛ روز خالص منفی، یعنی برگشت بیشتر از فروش، صفر)."""
    days = (end - start).days + 1
    return [max(0.0, by_day.get(start + timedelta(days=i), 0.0)) for i in range(max(days, 0))]


# ---------------------------------------------------------------------------
# فرمول
# ---------------------------------------------------------------------------
def z_score(service_level: float) -> float:
    return NormalDist().inv_cdf(min(max(service_level, 0.5), 0.999))


@dataclass
class RopResult:
    data_days: int
    sufficient: bool
    avg_daily: float
    std_daily: float
    lead_time: float
    lead_time_std: float
    service_level: float
    z: float
    safety_stock: int
    rop: int
    order_qty: int
    order_qty_method: str          # eoq | cover
    max_stock: int
    lead_time_demand: float
    annual_demand: float
    params_source: dict = field(default_factory=dict)


def compute_rop(series: list[float], *, lead_time: float, lead_time_std: float, service_level: float,
                policy: dict, unit_cost: float | None) -> RopResult:
    n = len(series)
    mean = sum(series) / n if n else 0.0
    std = math.sqrt(sum((x - mean) ** 2 for x in series) / (n - 1)) if n > 1 else 0.0
    z = z_score(service_level)
    safety = z * math.sqrt(lead_time * std ** 2 + mean ** 2 * lead_time_std ** 2)
    lead_demand = mean * lead_time
    rop = math.ceil(lead_demand + safety - 1e-9) if mean > 0 else 0
    annual = mean * 365
    holding = (unit_cost or 0) * policy["holding_rate"]
    if policy["ordering_cost"] > 0 and holding > 0 and annual > 0:
        order_qty, method = math.ceil(math.sqrt(2 * annual * policy["ordering_cost"] / holding)), "eoq"
    else:
        order_qty, method = math.ceil(mean * policy["cover_days"]), "cover"
    return RopResult(
        data_days=n, sufficient=n >= policy["min_history_days"], avg_daily=mean, std_daily=std, lead_time=lead_time,
        lead_time_std=lead_time_std, service_level=service_level, z=z, safety_stock=math.ceil(safety - 1e-9) if mean > 0 else 0,
        rop=rop, order_qty=order_qty, order_qty_method=method, max_stock=rop + order_qty, lead_time_demand=lead_demand,
        annual_demand=annual,
    )


def _params(inv: Inventory, policy: dict) -> tuple[float, float, float, dict]:
    source = {
        "lead_time_days": "item" if inv.lead_time_days is not None else "policy",
        "lead_time_std_days": "item" if inv.lead_time_std_days is not None else "policy",
        "service_level": "item" if inv.service_level is not None else "policy",
    }
    lead = inv.lead_time_days if inv.lead_time_days is not None else policy["lead_time_days"]
    lead_std = inv.lead_time_std_days if inv.lead_time_std_days is not None else policy["lead_time_std_days"]
    service = inv.service_level if inv.service_level is not None else policy["service_level"]
    return float(lead), float(lead_std), float(service), source


# ---------------------------------------------------------------------------
# بهای خرید
# ---------------------------------------------------------------------------
@dataclass
class CostBook:
    """بهای خرید هر کالا در هر روز: ردیف‌های قیمت (گذشته و آینده) + تورم بعد از آخرین قیمت معلوم."""
    rows: dict[int, list[ProductPrice]]
    fallback: dict[int, float]
    today: date
    growth: float

    def base(self, product_id: int, day: date) -> tuple[float, date, bool]:
        """(بها، تاریخ اعتبار آن بها، آیا تخمینی از قیمت فروش است)"""
        chosen = None
        for row in self.rows.get(product_id, []):
            if row.effective_from <= day:
                chosen = row
            else:
                break
        if chosen is None:
            return self.fallback.get(product_id, 0.0), self.today, True
        if chosen.cost_price is not None:
            return float(chosen.cost_price), chosen.effective_from, False
        return float(chosen.final_price or 0), chosen.effective_from, True

    def at(self, product_id: int, day: date) -> float:
        value, since, _ = self.base(product_id, day)
        months = max(0.0, (day - max(since, self.today)).days / 30.44)
        return value * (1 + self.growth) ** months

    def estimated(self, product_id: int) -> bool:
        return self.base(product_id, self.today)[2]


def cost_book(db: Session, product_ids: list[int], growth: float) -> CostBook:
    rows: dict[int, list[ProductPrice]] = defaultdict(list)
    if product_ids:
        for row in db.query(ProductPrice).filter(ProductPrice.product_id.in_(product_ids)).order_by(ProductPrice.effective_from).all():
            rows[row.product_id].append(row)
    fallback = {pid: price or 0.0 for pid, price in db.query(Product.id, Product.price).filter(Product.id.in_(product_ids)).all()} if product_ids else {}
    return CostBook(rows=rows, fallback=fallback, today=today_local(), growth=growth)


# ---------------------------------------------------------------------------
# فهرست اقلام و تنظیمات
# ---------------------------------------------------------------------------
def _inventories(db: Session, user: User, warehouse_id: int | None) -> list[Inventory]:
    query = db.query(Inventory).options(joinedload(Inventory.product), joinedload(Inventory.warehouse))
    if warehouse_id:
        query = query.filter(Inventory.warehouse_id == warehouse_id)
    return [inv for inv in query.all() if inv.product is not None and inv.product.is_active is not False]


def _evaluate(db: Session, invs: list[Inventory], policy: dict) -> dict[int, RopResult]:
    today = today_local()
    start = today - timedelta(days=int(policy["history_days"]))
    end = today - timedelta(days=1)                     # امروز هنوز کامل نشده
    ids = [i.id for i in invs]
    demand = daily_demand(db, ids, start, end)
    first = _first_activity(db, ids)
    costs = cost_book(db, list({i.product_id for i in invs}), policy["price_growth_monthly"])
    results = {}
    for inv in invs:
        s = max(start, first.get(inv.id, end + timedelta(days=1)))
        series = _series(demand.get(inv.id, {}), s, end)
        lead, lead_std, service, source = _params(inv, policy)
        result = compute_rop(series, lead_time=lead, lead_time_std=lead_std, service_level=service, policy=policy,
                             unit_cost=costs.at(inv.product_id, today))
        result.params_source = source
        results[inv.id] = result
    return results


def _status(qty: int, rop: int, safety: int) -> str:
    if qty <= 0:
        return "out"
    if qty <= safety:
        return "critical"
    if qty <= rop:
        return "reorder"
    return "ok"


def _row(inv: Inventory, r: RopResult) -> dict:
    qty = inv.quantity or 0
    effective_rop = inv.reorder_point if inv.reorder_point is not None else 0
    days_cover = qty / r.avg_daily if r.avg_daily > 0 else None
    p = inv.product
    return {
        "inventory_id": inv.id, "product_id": p.id, "sku": p.sku,
        "name": p.name + (f" ({p.variant_label})" if p.variant_label else ""), "category": p.category, "unit": p.unit or "عدد",
        "warehouse_id": inv.warehouse_id, "warehouse": inv.warehouse.name if inv.warehouse else None,
        "quantity": qty, "reorder_point": effective_rop, "rop_mode": inv.rop_mode or "manual",
        "lead_time_days": inv.lead_time_days, "lead_time_std_days": inv.lead_time_std_days, "service_level": inv.service_level,
        "effective": {"lead_time_days": r.lead_time, "lead_time_std_days": r.lead_time_std, "service_level": r.service_level,
                      "source": r.params_source},
        "calc": {
            "data_days": r.data_days, "sufficient": r.sufficient, "avg_daily_demand": round(r.avg_daily, 3),
            "demand_std": round(r.std_daily, 3), "z": round(r.z, 3), "lead_time_demand": round(r.lead_time_demand, 2),
            "safety_stock": r.safety_stock, "rop": r.rop, "order_qty": r.order_qty, "order_qty_method": r.order_qty_method,
            "max_stock": r.max_stock, "annual_demand": round(r.annual_demand),
        },
        "status": _status(qty, effective_rop, min(r.safety_stock, effective_rop)),
        "days_of_cover": round(days_cover, 1) if days_cover is not None else None,
        "stockout_date": (today_local() + timedelta(days=int(days_cover))).isoformat() if days_cover is not None else None,
        "suggested_purchase": max(0, (effective_rop + r.order_qty) - qty) if qty <= effective_rop else 0,
        "calculated_at": inv.rop_calculated_at,
    }


STATUS_ORDER = {"out": 0, "critical": 1, "reorder": 2, "ok": 3}


def list_items(db: Session, user: User, warehouse_id: int | None = None, status: str | None = None,
               q: str | None = None, mode: str | None = None) -> dict:
    _ensure_staff(user)
    wid = _warehouse_scope(user, warehouse_id)
    policy = policy_of(db.get(Organization, user.organization_id))
    invs = _inventories(db, user, wid)
    results = _evaluate(db, invs, policy)
    rows = [_row(inv, results[inv.id]) for inv in invs]
    summary = {key: sum(1 for r in rows if r["status"] == key) for key in STATUS_ORDER}
    summary["auto"] = sum(1 for r in rows if r["rop_mode"] == "auto")
    summary["insufficient"] = sum(1 for r in rows if not r["calc"]["sufficient"])
    summary["total"] = len(rows)
    if status:
        rows = [r for r in rows if r["status"] == status]
    if mode:
        rows = [r for r in rows if r["rop_mode"] == mode]
    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if needle in r["name"].lower() or needle in r["sku"].lower() or needle in (r["category"] or "").lower()]
    rows.sort(key=lambda r: (STATUS_ORDER[r["status"]], r["days_of_cover"] if r["days_of_cover"] is not None else 1e9, r["name"]))
    return {"policy": policy, "summary": summary, "items": rows}


def _apply(inv: Inventory, r: RopResult) -> None:
    """نتیجه فرمول را روی ردیف ذخیره می‌کند؛ در حالت خودکار نقطه سفارش هم عوض می‌شود (اگر داده کافی باشد)."""
    inv.avg_daily_demand, inv.demand_std = r.avg_daily, r.std_daily
    inv.safety_stock, inv.suggested_order_qty = r.safety_stock, r.order_qty
    inv.rop_calculated_at = _now()
    if inv.rop_mode == "auto" and r.sufficient:
        inv.reorder_point = r.rop
        # هشدار کمبود بعد از پر شدن دوباره فعال می‌شود (همان منطق دفتر گردش)
        if (inv.quantity or 0) > r.rop:
            inv.ever_exceeded_reorder = True
            inv.low_alerted = False


def update_item(db: Session, user: User, inventory_id: int, data: dict) -> dict:
    _ensure_staff(user)
    inv = db.get(Inventory, inventory_id)
    if inv is None:
        raise NotFoundError("ردیف موجودی یافت نشد.")
    if _role(user) == "warehouse_manager" and inv.warehouse_id != user.warehouse_id:
        raise ForbiddenError("فقط کالاهای انبار خودتان را می‌توانید تنظیم کنید.")
    for key in ("lead_time_days", "lead_time_std_days", "service_level"):
        if key in data:
            setattr(inv, key, data[key])
    if "rop_mode" in data and data["rop_mode"]:
        inv.rop_mode = data["rop_mode"]
    if data.get("reorder_point") is not None:
        if inv.rop_mode == "auto":
            raise ConflictError("در حالت خودکار نقطه سفارش با فرمول محاسبه می‌شود؛ برای عدد دستی حالت را «دستی» کنید.")
        inv.reorder_point = data["reorder_point"]
    policy = policy_of(db.get(Organization, user.organization_id))
    result = _evaluate(db, [inv], policy)[inv.id]
    if inv.rop_mode == "auto" and not result.sufficient:
        raise ConflictError(f"برای محاسبه خودکار دست‌کم {fa_digits(str(policy['min_history_days']))} روز سابقه فروش لازم است "
                            f"(این کالا {fa_digits(str(result.data_days))} روز دارد)؛ فعلاً عدد دستی را نگه دارید.")
    _apply(inv, result)
    audit_service.log(db, user, "inventory.rop", f"تنظیم نقطه سفارش «{inv.product.name}» ({'خودکار' if inv.rop_mode == 'auto' else 'دستی'}: "
                      f"{fa_digits(str(inv.reorder_point))})", target_type="product", target_id=inv.product_id,
                      target_label=inv.product.name)
    db.commit()
    db.refresh(inv)
    return _row(inv, result)


def apply_auto(db: Session, user: User, inventory_ids: list[int] | None, warehouse_id: int | None = None) -> dict:
    """حالت خودکار برای اقلام انتخابی (یا همه اقلام دارای داده کافی)؛ اقلام کم‌سابقه دستی می‌مانند."""
    _ensure_staff(user)
    wid = _warehouse_scope(user, warehouse_id)
    invs = _inventories(db, user, wid)
    if inventory_ids is not None:
        wanted = set(inventory_ids)
        invs = [i for i in invs if i.id in wanted]
    policy = policy_of(db.get(Organization, user.organization_id))
    results = _evaluate(db, invs, policy)
    switched, skipped = 0, 0
    for inv in invs:
        r = results[inv.id]
        if not r.sufficient:
            skipped += 1
            continue
        inv.rop_mode = "auto"
        _apply(inv, r)
        switched += 1
    audit_service.log(db, user, "inventory.rop_auto", f"نقطه سفارش {fa_digits(str(switched))} قلم خودکار شد")
    db.commit()
    return {"switched": switched, "skipped": skipped}


def recalculate(db: Session, organization_id: int) -> int:
    """محاسبه دوباره همه ردیف‌های یک سازمان (تسک شبانه Celery و بعد از تغییر سیاست). commit با فراخواننده."""
    org = db.get(Organization, organization_id)
    invs = [i for i in db.query(Inventory).options(joinedload(Inventory.product)).filter(Inventory.organization_id == organization_id).all()
            if i.product is not None]
    results = _evaluate(db, invs, policy_of(org))
    for inv in invs:
        _apply(inv, results[inv.id])
    return len(invs)


# ---------------------------------------------------------------------------
# برآورد سرمایه خرید ماه‌های آینده
# ---------------------------------------------------------------------------
def _jalali_month_start(day: date) -> tuple[int, int, date]:
    jy, jm, _ = gregorian_to_jalali(day.year, day.month, day.day)
    return jy, jm, date(*jalali_to_gregorian(jy, jm, 1))


def _next_jalali_month(jy: int, jm: int) -> tuple[int, int]:
    return (jy + 1, 1) if jm == 12 else (jy, jm + 1)


def future_months(start: date, count: int) -> list[dict]:
    """ماه‌های شمسی از امروز: ماه اول فقط روزهای باقی‌مانده را دارد."""
    jy, jm, _ = _jalali_month_start(start)
    months = []
    cursor = start
    for _ in range(count):
        ny, nm = _next_jalali_month(jy, jm)
        end_excl = date(*jalali_to_gregorian(ny, nm, 1))
        months.append({"key": f"{jy}-{jm:02d}", "label": f"{MONTHS[jm - 1]} {fa_digits(str(jy))}", "start": cursor,
                       "end": end_excl - timedelta(days=1), "days": (end_excl - cursor).days,
                       "full_days": (end_excl - date(*jalali_to_gregorian(jy, jm, 1))).days})
        cursor, jy, jm = end_excl, ny, nm
    return months


def holt_forecast(values: list[float], horizon: int, alpha: float = 0.5, beta: float = 0.3, phi: float = 0.9) -> list[float]:
    """هموارسازی نمایی دوگانه با روند میرا — روند اخیر را دنبال می‌کند ولی بی‌نهایت ادامه نمی‌دهد."""
    if not values:
        return [0.0] * horizon
    if len(values) == 1:
        return [max(0.0, values[0])] * horizon
    level, trend = values[0], values[1] - values[0]
    for value in values[1:]:
        previous = level
        level = alpha * value + (1 - alpha) * (level + phi * trend)
        trend = beta * (level - previous) + (1 - beta) * phi * trend
    out, damp = [], 0.0
    for h in range(1, horizon + 1):
        damp += phi ** h
        out.append(max(0.0, level + damp * trend))
    return out


def _monthly_rates(by_day: dict[date, float], first: date | None, today: date) -> list[float]:
    """تقاضای روزانه میانگین هر ماه شمسی کامل گذشته (حداکثر ۱۲ ماه، از اولین فعالیت کالا)."""
    _, _, current_start = _jalali_month_start(today)
    rates = []
    cursor_end = current_start
    for _ in range(12):
        prev_day = cursor_end - timedelta(days=1)
        _, _, month_start = _jalali_month_start(prev_day)
        if first is None or month_start < first:
            break
        days = (cursor_end - month_start).days
        total = sum(max(0.0, by_day.get(month_start + timedelta(days=i), 0.0)) for i in range(days))
        rates.append(total / days)
        cursor_end = month_start
    return list(reversed(rates))


def plan(db: Session, user: User, months: int = 6, warehouse_id: int | None = None,
         price_growth: float | None = None, demand_growth: float | None = None) -> dict:
    _ensure_admin(user)
    if not 1 <= months <= MAX_PLAN_MONTHS:
        raise ConflictError(f"افق برنامه بین ۱ تا {fa_digits(str(MAX_PLAN_MONTHS))} ماه است.")
    policy = policy_of(db.get(Organization, user.organization_id))
    if price_growth is not None:
        policy["price_growth_monthly"] = price_growth
    if demand_growth is not None:
        policy["demand_growth_monthly"] = demand_growth
    today = today_local()
    invs = _inventories(db, user, warehouse_id)
    rop_results = _evaluate(db, invs, policy)
    ids = [i.id for i in invs]
    history = daily_demand(db, ids, today - timedelta(days=380), today - timedelta(days=1))
    first = _first_activity(db, ids)
    costs = cost_book(db, list({i.product_id for i in invs}), policy["price_growth_monthly"])
    horizon = future_months(today, months)
    total_days = sum(m["days"] for m in horizon)
    month_of_day = []
    for index, m in enumerate(horizon):
        month_of_day += [index] * m["days"]

    month_totals = [{"capital": 0.0, "orders": 0, "units": 0, "demand_units": 0.0, "stock_value_end": 0.0,
                     "stockout_items": 0} for _ in horizon]
    items, estimated_cost, no_demand = [], [], 0
    for inv in invs:
        r = rop_results[inv.id]
        rates = _monthly_rates(history.get(inv.id, {}), first.get(inv.id), today)
        if len([x for x in rates if x > 0]) >= 3:
            forecast_rates, method = holt_forecast(rates, months), "holt"
        else:
            forecast_rates, method = [r.avg_daily] * months, "average"
        forecast_rates = [rate * (1 + policy["demand_growth_monthly"]) ** k for k, rate in enumerate(forecast_rates)]
        if all(rate <= 0 for rate in forecast_rates):
            no_demand += 1
            continue
        # نقطه سفارش شبیه‌سازی: فرمول (اگر داده کافی است) وگرنه همان عدد فعلی
        rop = r.rop if r.sufficient else (inv.reorder_point or 0)
        order_qty = max(r.order_qty, 1)
        lead = max(0, math.ceil(r.lead_time))
        on_hand = float(inv.quantity or 0)
        pipeline: dict[int, float] = defaultdict(float)
        item_months = [{"capital": 0.0, "units": 0, "orders": 0} for _ in horizon]
        stockout_days = [0] * len(horizon)
        for d in range(total_days):
            day = today + timedelta(days=d)
            mi = month_of_day[d]
            on_hand += pipeline.pop(d, 0.0)
            position = on_hand + sum(pipeline.values())
            if position <= rop:
                qty = math.ceil(rop + order_qty - position)
                unit_cost = costs.at(inv.product_id, day)
                pipeline[d + lead] += qty
                if d + lead == d:
                    on_hand += pipeline.pop(d)
                item_months[mi]["capital"] += qty * unit_cost
                item_months[mi]["units"] += qty
                item_months[mi]["orders"] += 1
            on_hand -= forecast_rates[mi]
            if on_hand < 0:
                stockout_days[mi] += 1
                on_hand = 0.0               # فروش ازدست‌رفته (پس‌افت نگه داشته نمی‌شود)
            if d == total_days - 1 or month_of_day[d + 1] != mi:
                month_totals[mi]["stock_value_end"] += on_hand * costs.at(inv.product_id, day)
        for mi, m in enumerate(item_months):
            month_totals[mi]["capital"] += m["capital"]
            month_totals[mi]["orders"] += m["orders"]
            month_totals[mi]["units"] += m["units"]
            month_totals[mi]["demand_units"] += forecast_rates[mi] * horizon[mi]["days"]
            month_totals[mi]["stockout_items"] += 1 if stockout_days[mi] else 0
        if costs.estimated(inv.product_id):
            estimated_cost.append(inv.product.name)
        p = inv.product
        items.append({
            "inventory_id": inv.id, "sku": p.sku, "name": p.name + (f" ({p.variant_label})" if p.variant_label else ""),
            "category": p.category, "warehouse": inv.warehouse.name if inv.warehouse else None, "quantity": inv.quantity or 0,
            "rop": rop, "order_qty": order_qty, "lead_time_days": r.lead_time, "forecast_method": method,
            "avg_daily_forecast": round(sum(forecast_rates) / len(forecast_rates), 3),
            "unit_cost_now": round(costs.at(p.id, today)), "cost_estimated": costs.estimated(p.id),
            "months": [{"capital": round(m["capital"]), "units": m["units"], "orders": m["orders"]} for m in item_months],
            "total_capital": round(sum(m["capital"] for m in item_months)),
            "total_units": sum(m["units"] for m in item_months),
            "stockout_risk": any(stockout_days),
        })
    items.sort(key=lambda i: -i["total_capital"])
    month_rows = [{
        "key": m["key"], "label": m["label"], "start": m["start"].isoformat(), "end": m["end"].isoformat(), "days": m["days"],
        "partial": m["days"] < m["full_days"], "capital": round(t["capital"]), "orders": t["orders"], "units": t["units"],
        "demand_units": round(t["demand_units"]), "stock_value_end": round(t["stock_value_end"]), "stockout_items": t["stockout_items"],
    } for m, t in zip(horizon, month_totals)]
    running = 0
    for row in month_rows:
        running += row["capital"]
        row["cumulative"] = running
    total = sum(r["capital"] for r in month_rows)
    peak = max(month_rows, key=lambda r: r["capital"]) if month_rows else None
    by_category: dict[str, int] = defaultdict(int)
    by_warehouse: dict[str, int] = defaultdict(int)
    for item in items:
        by_category[item["category"] or "بدون گروه"] += item["total_capital"]
        by_warehouse[item["warehouse"] or "—"] += item["total_capital"]
    return {
        "generated_at": _now(), "months": month_rows, "items": items,
        "assumptions": {**policy, "horizon_months": months, "warehouse_id": warehouse_id},
        "summary": {
            "total_capital": total, "peak_month": peak["label"] if peak and peak["capital"] else None,
            "peak_capital": peak["capital"] if peak else 0, "average_monthly": round(total / len(month_rows)) if month_rows else 0,
            "items_planned": len(items), "items_without_demand": no_demand,
            "items_cost_estimated": len(estimated_cost), "cost_estimated_names": estimated_cost[:20],
            "stockout_risk_items": sum(1 for i in items if i["stockout_risk"]),
            "current_stock_value": round(sum((inv.quantity or 0) * costs.at(inv.product_id, today) for inv in invs)),
        },
        "by_category": [{"label": k, "capital": v} for k, v in sorted(by_category.items(), key=lambda kv: -kv[1])],
        "by_warehouse": [{"label": k, "capital": v} for k, v in sorted(by_warehouse.items(), key=lambda kv: -kv[1])],
    }
