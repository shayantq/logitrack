"""
ماشین وضعیت اسناد و عملیات (فصل ۲۰) — مرجع خوانا برای رابط کاربری، آموزش و مستندات.

وضعیت‌ها همان ثابت‌های app/core/wms.py و مدل‌ها هستند (تست tests/unit/test_wms_control.py برابری را کنترل می‌کند)؛
اجرای واقعی هر انتقال و کنترل نقش/مجوز آن در سرویس همان سند است — این فهرست فقط آن را توصیف می‌کند.
"""
from __future__ import annotations

from app.core.wms import (
    BACKORDER_STATUS_LABELS, DOCUMENT_STATUS_LABELS, PICK_LIST_STATUS_LABELS, PUTAWAY_STATUS_LABELS, RECEIPT_STATUS_LABELS,
    SHIPMENT_STATUS_LABELS, TRANSFER_STATUS_LABELS,
)

ADMIN, MANAGER, DRIVER, SYSTEM = "ادمین سازمان", "مدیر انبار", "راننده", "سیستم"
STAFF = f"{ADMIN} / {MANAGER}"

ORDER_LABELS = {"pending": "ثبت‌شده", "assigned": "تخصیص خودرو", "picking_up": "راننده در راه انبار", "picked_up": "بارگیری‌شده",
                "in_transit": "در مسیر", "delivered": "تحویل داده شد", "failed": "ناموفق", "canceled": "لغوشده", "expired": "منقضی"}
STOCKTAKE_LABELS = {"counting": "در حال شمارش", "review": "منتظر بررسی", "approved": "تأییدشده", "canceled": "لغوشده"}


def _wf(code, label, states: dict[str, str], finals, transitions, note=None) -> dict:
    return {"code": code, "label": label, "note": note,
            "states": [{"code": c, "label": l, "final": c in finals} for c, l in states.items()],
            "transitions": [{"from": f, "to": t, "action": a, "actor": r} for f, t, a, r in transitions]}


WORKFLOWS = [
    _wf("order", "سفارش مشتری", ORDER_LABELS, ("delivered", "failed", "canceled", "expired"), [
        ("pending", "assigned", "تخصیص خودرو و راننده (دستی یا هوشمند)", f"{STAFF} / {SYSTEM}"),
        ("pending", "canceled", "لغو و آزادسازی رزرو", STAFF),
        ("pending", "expired", "گذشتن بازه تحویل", SYSTEM),
        ("assigned", "picking_up", "حرکت راننده به انبار", DRIVER),
        ("assigned", "picked_up", "تحویل بار به راننده (حواله خروج)", f"{MANAGER} / {DRIVER}"),
        ("picking_up", "picked_up", "تحویل بار به راننده (حواله خروج)", f"{MANAGER} / {DRIVER}"),
        ("assigned", "canceled", "لغو", STAFF), ("picking_up", "canceled", "لغو", STAFF),
        ("picked_up", "in_transit", "شروع مسیر", DRIVER),
        ("in_transit", "delivered", "تحویل به مشتری", DRIVER),
        ("assigned", "failed", "ناموفق", DRIVER), ("picking_up", "failed", "ناموفق", DRIVER),
        ("picked_up", "failed", "ناموفق (برگشت کالا در انتظار بازرسی)", DRIVER),
        ("in_transit", "failed", "ناموفق (برگشت کالا در انتظار بازرسی)", DRIVER),
    ], "موجودی هنگام ثبت رزرو، هنگام بارگیری با حواله خروج کسر و در لغو/انقضا آزاد می‌شود."),
    _wf("fulfillment", "آماده‌سازی سفارش در انبار", {"open": "آماده‌نشده", "picking": "در حال برداشت", "picked": "برداشت‌شده",
                                                    "packed": "بسته‌بندی‌شده", "shipped": "ارسال‌شده"}, ("shipped",), [
        ("open", "picking", "ساخت فهرست برداشت", STAFF), ("picking", "picked", "اسکن و برداشت همه سطرها", STAFF),
        ("picked", "packed", "بسته‌بندی و برگه بسته‌بندی", STAFF), ("packed", "shipped", "تحویل محموله به راننده", STAFF),
        ("picking", "open", "لغو فهرست برداشت (برگشت از محل آماده‌سازی)", STAFF),
    ]),
    _wf("receipt", "رسید دریافت کالا", RECEIPT_STATUS_LABELS, ("closed", "canceled"), [
        ("open", "receiving", "اولین دریافت (اسکن/ثبت مقدار)", STAFF), ("receiving", "closed", "بستن با ثبت مغایرت", STAFF),
        ("open", "canceled", "لغو رسید بدون دریافت", STAFF),
    ], "مغایرت‌ها (کسری، اضافه، کالای خارج از برنامه) هنگام بستن با دلیل ثبت می‌شوند."),
    _wf("putaway", "وظیفه جانمایی / تأمین مجدد", PUTAWAY_STATUS_LABELS, ("done", "canceled"), [
        ("open", "partial", "اجرای بخشی با اسکن", STAFF), ("open", "done", "اجرای کامل با اسکن", STAFF),
        ("partial", "done", "اجرای باقی‌مانده", STAFF), ("open", "canceled", "لغو با دلیل", STAFF),
        ("partial", "canceled", "لغو باقی‌مانده با دلیل", STAFF),
    ]),
    _wf("pick_list", "فهرست برداشت", PICK_LIST_STATUS_LABELS, ("picked", "canceled"), [
        ("open", "in_progress", "اولین اسکن برداشت", STAFF), ("in_progress", "picked", "برداشت یا کسری همه سطرها", STAFF),
        ("open", "canceled", "لغو", STAFF), ("in_progress", "canceled", "لغو (برگشت کالای برداشت‌شده)", STAFF),
    ]),
    _wf("shipment", "محموله", SHIPMENT_STATUS_LABELS, ("dispatched", "canceled"), [
        ("open", "dispatched", "تحویل به راننده (کنترل وزن و حجم خودرو)", STAFF), ("open", "canceled", "لغو", STAFF),
    ]),
    _wf("transfer", "سفارش انتقال", TRANSFER_STATUS_LABELS, ("closed", "canceled"), [
        ("open", "in_transit", "ارسال از مبدأ (کالا «در راه»)", STAFF), ("open", "canceled", "لغو", STAFF),
        ("in_transit", "received", "دریافت کامل در مقصد", STAFF),
        ("in_transit", "closed", "بستن با تکلیف کسری (حذف یا برگشت)", STAFF),
        ("received", "closed", "بستن", STAFF),
    ]),
    _wf("backorder", "سفارش معوق", BACKORDER_STATUS_LABELS, ("fulfilled", "canceled"), [
        ("open", "allocated", "تخصیص موجودی جدید به ترتیب اولویت", f"{STAFF} / {SYSTEM}"),
        ("allocated", "fulfilled", "ساخت سفارش تکمیلی", STAFF), ("open", "canceled", "لغو", STAFF),
        ("allocated", "canceled", "لغو (آزادسازی رزرو)", STAFF),
    ]),
    _wf("stocktake", "انبارگردانی", STOCKTAKE_LABELS, ("approved", "canceled"), [
        ("counting", "review", "پایان شمارش همه سطرها", STAFF), ("review", "counting", "درخواست شمارش مجدد", "تأییدکننده"),
        ("review", "approved", "تأیید و ثبت اصلاحیه (سقف ارزش مغایرت و تفکیک وظایف)", "تأییدکننده"),
        ("counting", "canceled", "لغو (آزادسازی قفل محل‌ها)", ADMIN), ("review", "canceled", "لغو", ADMIN),
    ], "در حالت «قفل محل» هیچ گردشی تا تأیید یا لغو از محل‌های محدوده ثبت نمی‌شود."),
    _wf("stock_document", "سند انبار", DOCUMENT_STATUS_LABELS, ("reversed", "canceled"), [
        ("draft", "posted", "قطعی کردن", STAFF), ("draft", "canceled", "لغو پیش‌نویس", STAFF),
        ("posted", "reversed", "سند برگشت (اسناد قابل برگشت، با دلیل)", STAFF),
    ], "سند قطعی و گردش‌هایش ویرایش یا حذف نمی‌شوند؛ اصلاح فقط با سند برگشت."),
]


def workflows() -> list[dict]:
    return WORKFLOWS
