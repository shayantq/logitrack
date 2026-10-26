"""
برچسب و بارکد (فصل ۲۷): برچسب PDF کالا، محل و بسته با بارکد Code128 و QR، و کنترل چاپ دوباره.

  • هر برچسب یک صفحه ۱۰۰×۶۰ میلی‌متر (مناسب چاپگر حرارتی؛ روی A4 هم قابل چاپ است).
  • بارکد Code128 همان رشته‌ای است که اسکن‌ها می‌پذیرند (بارکد/کد کالا، بارکد محل، کد بسته) و QR همان رشته
    را دارد — برای بسته، QR لینک رهگیری عمومی سفارش است.
  • اولین چاپ هر برچسب با مجوز «چاپ برچسب» آزاد است؛ چاپ دوباره همان برچسب «چاپ مجدد» حساب می‌شود، مجوز
    جدا و دلیل لازم دارد و در سابقه چاپ و گزارش فعالیت ثبت می‌شود (جلوی برچسب تکراری روی کالای اشتباه را می‌گیرد).
"""
from __future__ import annotations

import io

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128, qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from sqlalchemy.orm import Session

from app.core.iran import fa_digits
from app.core.wms import LOCATION_TYPES
from app.models import LabelPrint, Location, Order, Package, Product, User, Warehouse
from app.services import audit_service, location_service, messaging, permission_service
from app.services.exceptions import ConflictError, NotFoundError
from app.services.report_builder import _rtl  # noqa: F401  (ثبت فونت Vazirmatn هنگام import)

LABEL_TYPES = {"product": "کالا", "location": "محل", "package": "بسته"}
PAGE = (100 * mm, 60 * mm)


def _code(label_type: str, obj) -> str:
    if label_type == "product":
        return (obj.barcode or obj.sku).strip()
    if label_type == "location":
        return obj.barcode
    return obj.code


def _targets(db: Session, user: User, label_type: str, ids: list[int]) -> list:
    model = {"product": Product, "location": Location, "package": Package}[label_type]
    rows = db.query(model).filter(model.id.in_(set(ids))).all()
    if len(rows) != len(set(ids)):
        raise NotFoundError(f"بعضی از {LABEL_TYPES[label_type]}های انتخاب‌شده یافت نشدند.")
    if label_type == "location":
        for loc in rows:
            location_service.scope_warehouse(user, loc.warehouse_id)
    if label_type == "package":
        orders = {o.id: o for o in db.query(Order).filter(Order.id.in_({p.order_id for p in rows})).all()}
        for p in rows:
            location_service.scope_warehouse(user, orders[p.order_id].warehouse_id if orders.get(p.order_id) else None)
    order = {i: n for n, i in enumerate(ids)}
    return sorted(rows, key=lambda r: order.get(r.id, 0))


def _barcode(c, value: str, x: float, y: float, width: float, height: float) -> None:
    bar = code128.Code128(value, barHeight=height, humanReadable=True, fontSize=7)
    scale = min(1.0, width / bar.width) if bar.width else 1.0
    c.saveState()
    c.translate(x, y)
    c.scale(scale, 1)
    bar.drawOn(c, 0, 0)
    c.restoreState()


def _qr(c, value: str, x: float, y: float, size: float) -> None:
    widget = qr.QrCodeWidget(value)
    x1, y1, x2, y2 = widget.getBounds()
    drawing = Drawing(size, size, transform=[size / (x2 - x1), 0, 0, size / (y2 - y1), 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, c, x, y)


def _text(c, text: str, x_right: float, y: float, size: float) -> None:
    c.setFont("Vazirmatn", size)
    c.drawRightString(x_right, y, _rtl(fa_digits(text)) if text else "")


def _draw(db: Session, c, label_type: str, obj, org_name: str, copy_no: int, copies: int, reprint: bool) -> None:
    w, h = PAGE
    right = w - 4 * mm
    code = _code(label_type, obj)
    c.setLineWidth(0.6)
    c.roundRect(2 * mm, 2 * mm, w - 4 * mm, h - 4 * mm, 2 * mm)
    _text(c, org_name, right, h - 8 * mm, 7)
    if reprint:
        c.setFont("Vazirmatn", 7)
        c.drawString(5 * mm, h - 8 * mm, _rtl("چاپ مجدد"))
    if label_type == "product":
        _text(c, (obj.short_name or obj.name)[:40], right, h - 15 * mm, 11)
        _text(c, f"کد کالا: {obj.sku}", right, h - 21 * mm, 8)
        if obj.unit:
            _text(c, f"واحد: {obj.unit}", right, h - 26 * mm, 7)
        qr_value = code
    elif label_type == "location":
        c.setFont("Vazirmatn", 20)
        c.drawRightString(right, h - 18 * mm, obj.code)
        warehouse = db.get(Warehouse, obj.warehouse_id)
        _text(c, f"{warehouse.name if warehouse else ''} — {LOCATION_TYPES[obj.location_type].label}", right, h - 24 * mm, 8)
        qr_value = code
    else:
        order = db.get(Order, obj.order_id)
        total = db.query(Package).filter(Package.order_id == obj.order_id).count()
        _text(c, f"سفارش {order.tracking_code if order else ''}", right, h - 15 * mm, 11)
        _text(c, f"بسته {obj.sequence} از {total} — {obj.weight_kg:g} کیلوگرم", right, h - 21 * mm, 8)
        if order:
            _text(c, f"مقصد: {order.destination_city}", right, h - 26 * mm, 8)
        qr_value = f"{messaging.base_url()}/track/{order.tracking_code}" if order else code
    _barcode(c, code, 5 * mm, 7 * mm, w - 34 * mm, 12 * mm)
    _qr(c, qr_value, w - 26 * mm, 5 * mm, 22 * mm)
    if copies > 1:
        c.setFont("Vazirmatn", 6)
        c.drawString(5 * mm, h - 12 * mm, f"{copy_no}/{copies}")
    c.showPage()


def print_labels(db: Session, user: User, *, label_type: str, ids: list[int], copies: int = 1,
                 reason: str | None = None) -> tuple[bytes, str]:
    if label_type not in LABEL_TYPES:
        raise ConflictError("نوع برچسب معتبر نیست.")
    if not ids:
        raise ConflictError("دست‌کم یک مورد برای چاپ برچسب انتخاب کنید.")
    if len(ids) * copies > 500:
        raise ConflictError("در هر بار حداکثر ۵۰۰ برچسب چاپ می‌شود.")
    permission_service.ensure(db, user, "labels.print")
    targets = _targets(db, user, label_type, ids)
    printed = {tid for (tid,) in db.query(LabelPrint.target_id).filter(
        LabelPrint.label_type == label_type, LabelPrint.target_id.in_([t.id for t in targets])).distinct().all()}
    reprints = [t for t in targets if t.id in printed]
    if reprints:
        permission_service.ensure(db, user, "labels.reprint",
                                  f"برچسب {_code(label_type, reprints[0])} قبلاً چاپ شده؛ چاپ مجدد مجوز جدا دارد.")
        if not (reason or "").strip():
            raise ConflictError(f"برچسب {_code(label_type, reprints[0])} قبلاً چاپ شده است؛ دلیل چاپ مجدد را بنویسید.")
    org_name = user.organization.name if user.organization else ""
    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=PAGE)
    c.setTitle(f"labels-{label_type}")
    for t in targets:
        reprint = t.id in printed
        for n in range(1, copies + 1):
            _draw(db, c, label_type, t, org_name, n, copies, reprint)
        db.add(LabelPrint(organization_id=user.organization_id, label_type=label_type, target_id=t.id,
                          target_code=_code(label_type, t)[:64], copies=copies, is_reprint=reprint,
                          reason=((reason or "").strip()[:300] or None) if reprint else None, printed_by_id=user.id))
    c.save()
    codes = ", ".join(_code(label_type, t) for t in targets[:5]) + ("…" if len(targets) > 5 else "")
    if reprints:
        audit_service.log(db, user, "label.reprint",
                          f"چاپ مجدد {len(reprints)} برچسب {LABEL_TYPES[label_type]} ({codes})",
                          target_type=label_type, target_id=reprints[0].id, target_label=_code(label_type, reprints[0]),
                          reason=reason.strip(), details={"ids": [t.id for t in reprints], "copies": copies})
    else:
        audit_service.log(db, user, "label.print", f"چاپ {len(targets) * copies} برچسب {LABEL_TYPES[label_type]} ({codes})",
                          target_type=label_type, target_id=targets[0].id, target_label=_code(label_type, targets[0]),
                          details={"ids": [t.id for t in targets], "copies": copies})
    db.commit()
    return buffer.getvalue(), f"labels-{label_type}-{len(targets)}.pdf"


def history(db: Session, user: User, *, label_type: str | None = None, limit: int = 100) -> list[dict]:
    permission_service.ensure(db, user, "labels.print")
    query = db.query(LabelPrint)
    if label_type:
        query = query.filter(LabelPrint.label_type == label_type)
    rows = query.order_by(LabelPrint.printed_at.desc(), LabelPrint.id.desc()).limit(min(limit, 500)).all()
    names = {u.id: u.full_name or u.username for u in db.query(User).filter(User.id.in_({r.printed_by_id for r in rows} or {-1})).all()}
    return [{"id": r.id, "label_type": r.label_type, "target_id": r.target_id, "target_code": r.target_code, "copies": r.copies,
             "is_reprint": r.is_reprint, "reason": r.reason, "printed_at": r.printed_at,
             "printed_by": names.get(r.printed_by_id)} for r in rows]
