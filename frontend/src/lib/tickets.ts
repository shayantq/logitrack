/** تیکت پشتیبانی (مرحله ۱۱): برچسب‌ها و ارسال فرم چندبخشی (متن + تصویر) */
import { ApiError, authFetch, type Schemas } from "@/api/client";
import type { Tone } from "@/ui/primitives";

export type Ticket = Schemas["TicketDetail"];
export type TicketRow = Schemas["TicketSummary"];
export type Side = "requester" | "org" | "platform";

export const TICKET_CATEGORIES: Record<"customer" | "driver" | "org", Record<string, string>> = {
  customer: { delay: "تأخیر در ارسال", damaged: "آسیب‌دیدگی کالا", wrong_item: "کالای اشتباه یا ناقص", driver: "رفتار راننده", address: "تغییر نشانی یا زمان تحویل", other: "سایر" },
  driver: { order_issue: "مشکل سفارش", vehicle: "خودرو", payment: "پورسانت و تسویه", app: "مشکل در سامانه", other: "سایر" },
  org: { technical: "مشکل فنی", account: "حساب کاربری و دسترسی", billing: "مالی و صورتحساب", feature: "پیشنهاد قابلیت", data: "اطلاعات و گزارش‌ها", other: "سایر" },
};

export const TICKET_STATUS: Record<string, { label: string; tone: Tone }> = {
  open: { label: "باز", tone: "info" },
  resolved: { label: "حل‌شده", tone: "success" },
  closed: { label: "بسته", tone: "muted" },
};
export const TICKET_PRIORITY: Record<string, { label: string; tone: Tone }> = {
  normal: { label: "عادی", tone: "muted" },
  high: { label: "بالا", tone: "warning" },
  urgent: { label: "فوری", tone: "danger" },
};
export const TICKET_SOURCE: Record<string, string> = { customer: "مشتری", driver: "راننده", org: "سازمان" };

/** «نوبت پاسخ» از دید بیننده */
export function waitingLabel(t: Pick<TicketRow, "status" | "waiting_on" | "source">, side: Side): { label: string; mine: boolean } | null {
  if (t.status !== "open") return null;
  const w = t.waiting_on;
  if ((side === "org" && w === "org") || (side === "platform" && w === "platform") || (side === "requester" && w === "requester"))
    return { label: side === "requester" ? "پاسخ جدید دارید" : "منتظر پاسخ شما", mine: true };
  if (w === "platform") return { label: "در انتظار پشتیبانی پسینه", mine: false };
  if (w === "org") return { label: side === "requester" ? "در حال بررسی" : "در انتظار سازمان", mine: false };
  if (w === "requester") return { label: side === "platform" && t.source === "org" ? "در انتظار سازمان" : "در انتظار درخواست‌کننده", mine: false };
  return null;
}

/** ارسال فرم با فایل (FormData) — خطای سرور به ApiError با پیام فارسی تبدیل می‌شود */
export async function postForm<T>(url: string, form: FormData, auth = true): Promise<T> {
  const res = auth ? await authFetch(url, { method: "POST", body: form }) : await fetch(url, { method: "POST", body: form });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (data as { detail?: unknown }).detail;
    const message = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map(d => String((d as { msg?: string }).msg ?? "").replace(/^Value error, /, "")).join(" | ")
        : "خطا در ارسال";
    throw new ApiError(message, res.status);
  }
  return data as T;
}

export function messageForm(body: string, extra: Record<string, string | number | null | undefined> = {}, file?: File | null) {
  const form = new FormData();
  form.set("body", body);
  for (const [k, v] of Object.entries(extra)) if (v !== null && v !== undefined && v !== "") form.set(k, String(v));
  if (file) form.set("file", file);
  return form;
}
