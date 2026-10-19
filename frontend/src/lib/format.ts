/** قالب‌بندی تاریخ، عدد و ارقام برای نمایش فارسی */

/** تاریخ‌های سرور به UTC هستند؛ اگر منطقه زمانی نداشته باشند، Z اضافه می‌شود. */
function toDate(value?: string | null): Date | null {
  if (!value) return null;
  const iso = /[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function faDate(value?: string | null): string {
  const d = toDate(value);
  return d ? d.toLocaleDateString("fa-IR") : "—";
}

export function faDateTime(value?: string | null): string {
  const d = toDate(value);
  return d ? d.toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" }) : "—";
}

export function faShortDateTime(value?: string | null): string {
  const d = toDate(value);
  return d ? d.toLocaleString("fa-IR", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
}

export function faNumber(value?: number | null): string {
  return value === null || value === undefined ? "—" : value.toLocaleString("fa-IR");
}

/** ارقام فارسی/عربی → لاتین، و حذف فاصله و خط تیره (برای موبایل، کد پستی و ...) */
/** فقط ارقام فارسی/عربی را لاتین می‌کند (برای کدهایی مثل REQ-XXXX که خط تیره دارند) */
export function latinDigits(value: string): string {
  return value
    .replace(/[۰-۹]/g, d => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))
    .replace(/[٠-٩]/g, d => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)));
}

export function normalizeDigits(value: string): string {
  return latinDigits(value).replace(/[\s-]/g, "");
}

/** تاریخ (YYYY-MM-DD) + ساعت (HH:MM) به وقت محلی کاربر → ISO (UTC) برای سرور */
export function localToIso(date: string, time: string): string {
  return new Date(`${date}T${time}:00`).toISOString();
}

export function tomorrowIsoDate(): string {
  return new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
}
