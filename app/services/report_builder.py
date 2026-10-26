"""
سازنده گزارش با برند سازمان (مرحله ۱۴) — یک ساختار داده، دو خروجی: اکسل و PDF.

سربرگ همه گزارش‌ها: لوگو، نام و نام ثبتی سازمان، شناسه ملی و کد اقتصادی، عنوان و بازه گزارش، زمان تولید و کاربر.
جدول‌ها با رنگ سازمان، ارقام فارسی (PDF)، ردیف جمع، شماره صفحه و پانویس «تولیدشده با پسینه».
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from datetime import date, datetime

import arabic_reshaper
from bidi.algorithm import get_display
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import CondPageBreak, PageBreak, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core import storage
from app.core.iran import fa_digits, gregorian_to_jalali

DEFAULT_COLOR = "#0D9488"
_FONT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts", "Vazirmatn-Regular.ttf")
if "Vazirmatn" not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(TTFont("Vazirmatn", _FONT))


# ---------------------------------------------------------------------------
# ساختار گزارش
# ---------------------------------------------------------------------------
@dataclass
class Col:
    key: str
    title: str
    kind: str = "text"            # text | number | money | percent | date
    width: float = 14             # عرض در اکسل (کاراکتر)؛ PDF به نسبت همین
    total: bool = False


@dataclass
class Section:
    title: str
    columns: list[Col]
    rows: list[dict]
    totals: bool = True


@dataclass
class Report:
    title: str
    period: str | None
    sections: list[Section]
    kpis: list[tuple[str, str]] = field(default_factory=list)
    landscape: bool = False
    filename: str = "Pasineh_Report"


@dataclass
class Branding:
    name: str
    legal_name: str | None = None
    national_id: str | None = None
    economic_code: str | None = None
    address: str | None = None
    phone: str | None = None
    logo_path: str | None = None          # مسیر واقعی فایل
    color: str = DEFAULT_COLOR
    generated_by: str | None = None

    @classmethod
    def of(cls, org, user=None) -> "Branding":
        logo = storage.path_of(org.logo_path) if org.logo_path else None
        return cls(name=org.name, legal_name=getattr(org, "legal_name", None), national_id=getattr(org, "national_id", None),
                   economic_code=getattr(org, "economic_code", None), address=getattr(org, "address", None),
                   phone=getattr(org, "phone", None), logo_path=str(logo) if logo else None,
                   color=org.brand_color or DEFAULT_COLOR,
                   generated_by=(user.full_name or user.username) if user is not None else None)


def jalali(d: date | datetime | None, with_time: bool = False) -> str:
    if d is None:
        return ""
    jy, jm, jd = gregorian_to_jalali(d.year, d.month, d.day)
    text = f"{jy}/{jm:02d}/{jd:02d}"
    if with_time and isinstance(d, datetime):
        text += f" {d.hour:02d}:{d.minute:02d}"
    return text


def _meta_lines(b: Branding, report: Report, now_local: datetime) -> list[str]:
    ids = " · ".join(x for x in (f"شناسه ملی {b.national_id}" if b.national_id else "",
                                 f"کد اقتصادی {b.economic_code}" if b.economic_code else "") if x)
    lines = [b.legal_name or "", ids, report.title + (f" — {report.period}" if report.period else ""),
             f"تاریخ تهیه: {jalali(now_local, True)}" + (f" — {b.generated_by}" if b.generated_by else "")]
    return [l for l in lines if l]


def _hex(color: str) -> str:
    return color.lstrip("#").upper()


def _light(color: str, ratio: float = 0.9) -> str:
    c = _hex(color)
    r, g, bl = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return "".join(f"{int(v + (255 - v) * ratio):02X}" for v in (r, g, bl))


def _logo_png(path: str | None, max_px: int = 180) -> io.BytesIO | None:
    if not path:
        return None
    try:
        img = PILImage.open(path).convert("RGBA")
        img.thumbnail((max_px, max_px))
        out = io.BytesIO()
        img.save(out, format="PNG")
        out.seek(0)
        return out
    except Exception:
        return None


def _total(section: Section, col: Col):
    values = [r.get(col.key) for r in section.rows if isinstance(r.get(col.key), (int, float))]
    return sum(values) if values else None


# ---------------------------------------------------------------------------
# اکسل
# ---------------------------------------------------------------------------
def to_excel(report: Report, b: Branding, now_local: datetime) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    color = _hex(b.color)
    thin = Side(style="thin", color="D1D5DB")
    for index, section in enumerate(report.sections):
        ws = wb.create_sheet(section.title[:31])
        ws.sheet_view.rightToLeft = True
        ncols = max(len(section.columns), 4)
        for i, col in enumerate(section.columns, start=1):
            ws.column_dimensions[get_column_letter(i)].width = col.width
        # سربرگ
        row = 1
        ws.cell(row=row, column=1, value=b.name).font = Font(bold=True, size=16, color=color)
        for line in _meta_lines(b, report, now_local):
            row += 1
            ws.cell(row=row, column=1, value=line).font = Font(size=10, color="4B5563")
        for r in range(1, row + 1):
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=max(ncols - 1, 1))
        logo = _logo_png(b.logo_path, 120)
        if logo:
            img = XLImage(logo)
            img.height, img.width = 64, 64 * img.width / max(img.height, 1)
            ws.add_image(img, f"{get_column_letter(ncols)}1")
        row += 1
        if index == 0 and report.kpis:
            row += 1
            for i, (label, value) in enumerate(report.kpis):
                c = 1 + (i % 4) * 2
                r = row + (i // 4) * 2
                ws.cell(row=r, column=c, value=label).font = Font(size=9, color="6B7280")
                cell = ws.cell(row=r + 1, column=c, value=value)
                cell.font = Font(bold=True, size=12, color=color)
            row += ((len(report.kpis) + 3) // 4) * 2 + 1
        row += 1
        ws.cell(row=row, column=1, value=section.title).font = Font(bold=True, size=12)
        row += 1
        header_row = row
        for i, col in enumerate(section.columns, start=1):
            cell = ws.cell(row=row, column=i, value=col.title)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor=color)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
        ws.row_dimensions[row].height = 28
        zebra = PatternFill("solid", fgColor=_light(b.color, 0.92))
        for n, data in enumerate(section.rows):
            row += 1
            for i, col in enumerate(section.columns, start=1):
                value = data.get(col.key)
                cell = ws.cell(row=row, column=i, value=value if value != "" else None)
                cell.border = Border(bottom=thin)
                if col.kind in ("money", "number") and isinstance(value, (int, float)):
                    cell.number_format = "#,##0" if col.kind == "money" or float(value).is_integer() else "#,##0.0"
                elif col.kind == "percent" and isinstance(value, (int, float)):
                    cell.number_format = '0.0"٪"'
                if n % 2:
                    cell.fill = zebra
        if section.totals and section.rows and any(c.total for c in section.columns):
            row += 1
            ws.cell(row=row, column=1, value="جمع").font = Font(bold=True)
            for i, col in enumerate(section.columns, start=1):
                if col.total:
                    cell = ws.cell(row=row, column=i, value=_total(section, col))
                    cell.font = Font(bold=True)
                    cell.number_format = "#,##0"
                ws.cell(row=row, column=i).fill = PatternFill("solid", fgColor=_light(b.color, 0.8))
        if not section.rows:
            row += 1
            ws.cell(row=row, column=1, value="داده‌ای در این بازه نیست.").font = Font(italic=True, color="6B7280")
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
        if section.rows:
            ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(section.columns))}{header_row + len(section.rows)}"
        ws.cell(row=row + 2, column=1, value="تولیدشده با پسینه").font = Font(size=8, color="9CA3AF")
        ws.oddFooter.center.text = "صفحه &P از &N"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def to_csv(report: Report, b: Branding, now_local: datetime) -> bytes:
    """
    خروجی CSV برای ورود به نرم‌افزارهای دیگر و حجم بالا: سربرگ کوتاه، سپس هر بخش با سطر عنوان ستون‌ها.
    با BOM ذخیره می‌شود تا اکسل حروف فارسی را درست باز کند؛ اعداد خام (بدون جداکننده) می‌مانند.
    """
    import csv
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([b.name])
    writer.writerow([report.title])
    if report.period:
        writer.writerow([report.period])
    writer.writerow([f"تولید: {jalali(now_local, with_time=True)}"])
    for label, value in report.kpis:
        writer.writerow([label, value])
    for section in report.sections:
        writer.writerow([])
        writer.writerow([section.title])
        writer.writerow([c.title for c in section.columns])
        for row in section.rows:
            writer.writerow(["" if row.get(c.key) is None else row.get(c.key) for c in section.columns])
    return ("﻿" + out.getvalue()).encode("utf-8")


def _rtl(text) -> str:
    if text is None:
        return ""
    return get_display(arabic_reshaper.reshape(str(text)))


CELL_PAD = 3          # فاصله داخلی چپ/راست هر خانه جدول PDF (pt)
FONT_SIZE = 7.5


def _wrap(text, max_width: float, size: float = FONT_SIZE) -> str:
    """
    شکستن متن فارسی در چند خط تا از عرض ستون بیرون نزند (قبلاً عنوان‌ها و نام‌های بلند روی ستون کناری می‌افتادند).
    شکستن روی ترتیب منطقی کلمات انجام می‌شود و هر خط جدا راست‌به‌چپ می‌شود — اگر کل متن یک‌جا bidi شود
    و بعد شکسته شود، ترتیب خط‌ها برعکس درمی‌آید.
    """
    words = str(text if text is not None else "").split()
    if not words:
        return ""
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}" if current else word
        if current and pdfmetrics.stringWidth(arabic_reshaper.reshape(candidate), "Vazirmatn", size) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    lines.append(current)
    return "\n".join(_rtl(line) for line in lines)


def _fmt(value, kind: str) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, (int, float)):
        if kind == "percent":
            return fa_digits(f"{value:.1f}") + "٪"
        text = f"{value:,.0f}" if kind == "money" or float(value).is_integer() else f"{value:,.1f}"
        return fa_digits(text).replace(",", "٬")
    text = str(value)
    if kind == "date":
        return fa_digits(text)
    return text if len(text) <= 48 else text[:46] + "…"


def to_pdf(report: Report, b: Branding, now_local: datetime) -> bytes:
    pagesize = landscape(A4) if report.landscape else A4
    width = pagesize[0] - 3 * cm
    brand = colors.HexColor("#" + _hex(b.color))
    meta = _meta_lines(b, report, now_local)
    logo = _logo_png(b.logo_path, 200)

    def on_page(canvas, doc):
        canvas.saveState()
        top = pagesize[1] - 1.2 * cm
        right = pagesize[0] - 1.5 * cm
        x_text = right
        if logo:
            logo.seek(0)
            canvas.drawImage(_image_reader(logo), right - 1.8 * cm, top - 1.6 * cm, width=1.8 * cm, height=1.8 * cm,
                             preserveAspectRatio=True, mask="auto")
            x_text = right - 2.2 * cm
        canvas.setFillColor(brand)
        canvas.setFont("Vazirmatn", 14)
        canvas.drawRightString(x_text, top - 0.3 * cm, _rtl(b.name))
        canvas.setFillColor(colors.HexColor("#4B5563"))
        canvas.setFont("Vazirmatn", 8)
        for i, line in enumerate(meta):
            canvas.drawRightString(x_text, top - 0.8 * cm - i * 0.38 * cm, _rtl(fa_digits(line)))
        canvas.setStrokeColor(brand)
        canvas.setLineWidth(1.2)
        y_rule = top - 1.0 * cm - len(meta) * 0.38 * cm
        canvas.line(1.5 * cm, y_rule, right, y_rule)
        canvas.setFillColor(colors.HexColor("#9CA3AF"))
        canvas.setFont("Vazirmatn", 7)
        canvas.drawString(1.5 * cm, 0.8 * cm, _rtl(fa_digits(f"صفحه {doc.page}")))
        canvas.drawRightString(right, 0.8 * cm, _rtl("تولیدشده با پسینه"))
        canvas.restoreState()

    header_height = 1.6 * cm + len(meta) * 0.38 * cm
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=pagesize, rightMargin=1.5 * cm, leftMargin=1.5 * cm,
                            topMargin=1.2 * cm + header_height, bottomMargin=1.4 * cm)
    elements = []
    if report.kpis:
        per_row = 4
        grid = []
        for i in range(0, len(report.kpis), per_row):
            chunk = report.kpis[i:i + per_row]
            grid.append([_rtl(fa_digits(v)) for _, v in chunk][::-1] + [""] * (per_row - len(chunk)))
            grid.append([_rtl(l) for l, _ in chunk][::-1] + [""] * (per_row - len(chunk)))
        kpi_table = Table(grid, colWidths=[width / per_row] * per_row)
        style = [("FONTNAME", (0, 0), (-1, -1), "Vazirmatn"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                 ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#" + _light(b.color, 0.9))),
                 ("BOX", (0, 0), (-1, -1), 0.6, brand), ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.white)]
        for r in range(0, len(grid), 2):
            style += [("FONTSIZE", (0, r), (-1, r), 12), ("TEXTCOLOR", (0, r), (-1, r), brand),
                      ("FONTSIZE", (0, r + 1), (-1, r + 1), 7), ("TEXTCOLOR", (0, r + 1), (-1, r + 1), colors.HexColor("#6B7280"))]
        kpi_table.setStyle(TableStyle(style))
        elements += [kpi_table, Spacer(1, 12)]

    for n, section in enumerate(report.sections):
        if n and len(section.rows) > 25:
            elements.append(PageBreak())
        cols = list(reversed(section.columns))                       # راست‌به‌چپ: ستون اول سمت راست
        total_w = sum(c.width for c in cols) or 1
        widths = [width * c.width / total_w for c in cols]
        inner = [w - 2 * CELL_PAD - 1 for w in widths]
        data = [[_wrap(c.title, inner[i]) for i, c in enumerate(cols)]]
        for r in section.rows:
            data.append([_wrap(_fmt(r.get(c.key), c.kind), inner[i]) for i, c in enumerate(cols)])
        if section.totals and section.rows and any(c.total for c in cols):
            data.append([_rtl(_fmt(_total(section, c), "money")) if c.total else (_rtl("جمع") if c is cols[-1] else "") for c in cols])
        if not section.rows:
            data.append([_rtl("داده‌ای در این بازه نیست.")] + [""] * (len(cols) - 1))
        title = Table([[_rtl(section.title)]], colWidths=[width])
        title.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "Vazirmatn"), ("FONTSIZE", (0, 0), (-1, -1), 11),
                                   ("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("TEXTCOLOR", (0, 0), (-1, -1), brand)]))
        table = Table(data, colWidths=widths, repeatRows=1)
        style = [
            ("FONTNAME", (0, 0), (-1, -1), "Vazirmatn"), ("FONTSIZE", (0, 0), (-1, -1), FONT_SIZE), ("LEADING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), CELL_PAD), ("RIGHTPADDING", (0, 0), (-1, -1), CELL_PAD),
            ("BACKGROUND", (0, 0), (-1, 0), brand), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#" + _light(b.color, 0.93))]),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        if section.totals and section.rows and any(c.total for c in cols):
            style += [("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#" + _light(b.color, 0.8))),
                      ("FONTSIZE", (0, -1), (-1, -1), 8)]
        if not section.rows:
            style.append(("SPAN", (0, 1), (-1, 1)))
        table.setStyle(TableStyle(style))
        # عنوان بخش هیچ‌وقت تنها ته صفحه نمی‌ماند
        elements += [CondPageBreak(3.5 * cm), title, Spacer(1, 4), table, Spacer(1, 14)]
    doc.build(elements, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def _image_reader(stream):
    from reportlab.lib.utils import ImageReader
    return ImageReader(stream)
