/** برچسب‌های درخواست‌های راننده (مرخصی و تغییر خودرو) */
import type { Tone } from "@/ui/primitives";

export const LEAVE_CATEGORIES: Record<string, string> = {
  sickness: "بیماری", family: "امور خانوادگی", personal: "کار شخصی", vehicle_repair: "تعمیر خودرو", other: "سایر",
};
export const LEAVE_TYPES: Record<string, { label: string; hint: string }> = {
  urgent: { label: "مرخصی فوری", hint: "برای امروز تا دو روز آینده — بلافاصله به ادمین اطلاع داده می‌شود" },
  normal: { label: "مرخصی عادی", hint: "حداقل ۲۴ ساعت قبل از شروع" },
};
export const REQUEST_STATUS: Record<string, { label: string; tone: Tone }> = {
  draft: { label: "پیش‌نویس", tone: "muted" },
  pending: { label: "منتظر بررسی", tone: "warning" },
  approved: { label: "تأییدشده", tone: "success" },
  rejected: { label: "ردشده", tone: "danger" },
  canceled: { label: "لغوشده", tone: "muted" },
};

/** «2026-10-14» + «08:30» ← زمان به وقت ایران */
export const iranDateTime = (isoDate: string, hhmm: string) => `${isoDate}T${hhmm}:00+03:30`;
