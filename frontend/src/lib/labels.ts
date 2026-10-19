/** برچسب‌ها و قوانین مشترک — هم‌خوان با بک‌اند (app/services/order_service.py و app/models.py) */
import type { Tone } from "@/ui/primitives";

export type Role = "platform_admin" | "platform_support" | "org_admin" | "warehouse_manager" | "driver";

export const ROLE_LABELS: Record<Role, string> = {
  platform_admin: "ادمین پلتفرم",
  platform_support: "پشتیبان پلتفرم",
  org_admin: "ادمین سازمان",
  warehouse_manager: "مدیر انبار",
  driver: "راننده",
};

export const PLATFORM_ROLES: Role[] = ["platform_admin", "platform_support"];

export type OrderStatus =
  | "pending" | "assigned" | "picking_up" | "picked_up" | "in_transit"
  | "delivered" | "failed" | "canceled" | "expired";

export const ORDER_STATUS: Record<OrderStatus, { label: string; tone: Tone }> = {
  pending: { label: "در انتظار تخصیص", tone: "warning" },
  assigned: { label: "تخصیص‌یافته", tone: "info" },
  picking_up: { label: "در راه انبار", tone: "violet" },
  picked_up: { label: "بارگیری شد", tone: "violet" },
  in_transit: { label: "در مسیر مقصد", tone: "brand" },
  delivered: { label: "تحویل‌شده", tone: "success" },
  failed: { label: "ناموفق", tone: "danger" },
  canceled: { label: "لغوشده", tone: "muted" },
  expired: { label: "منقضی‌شده", tone: "orange" },
};

export const ACTIVE_ORDER_STATUSES: OrderStatus[] = ["pending", "assigned", "picking_up", "picked_up", "in_transit"];

/** انتقال‌های مجاز (ادمین سازمان). pending → assigned فقط از مسیر تخصیص خودرو. */
export const ORDER_TRANSITIONS: Partial<Record<OrderStatus, OrderStatus[]>> = {
  pending: ["canceled"],
  // «تحویل داده شد» فقط پس از بارگیری (هماهنگ با سرور)
  assigned: ["picking_up", "picked_up", "failed", "canceled"],
  picking_up: ["picked_up", "failed", "canceled"],
  picked_up: ["in_transit", "failed"],
  in_transit: ["delivered", "failed"],
};
const DRIVER_ALLOWED: OrderStatus[] = ["picking_up", "picked_up", "in_transit", "delivered", "failed"];
const MANAGER_ALLOWED: OrderStatus[] = ["picked_up", "canceled"];

export function nextStatusesFor(role: Role, status: string): OrderStatus[] {
  const next = ORDER_TRANSITIONS[status as OrderStatus] ?? [];
  if (role === "driver") return next.filter(s => DRIVER_ALLOWED.includes(s));
  if (role === "warehouse_manager") return next.filter(s => MANAGER_ALLOWED.includes(s));
  if (role === "org_admin") return next;
  return [];
}

export const orderStatusLabel = (s: string) => ORDER_STATUS[s as OrderStatus]?.label ?? s;
export const orderStatusTone = (s: string): Tone => ORDER_STATUS[s as OrderStatus]?.tone ?? "muted";

export const VEHICLE_STATUS: Record<string, string> = {
  available: "در دسترس", on_route: "در مسیر", maintenance: "تعمیرات", inactive: "غیرفعال", busy: "مشغول",
};
export const VEHICLE_TYPES: Record<string, string> = {
  motorcycle: "موتورسیکلت", sedan: "سواری", pickup: "وانت", van: "ون", truck: "کامیون",
};

export const MOVEMENT_TYPES: Record<string, { label: string; tone: Tone }> = {
  initial: { label: "موجودی اولیه", tone: "muted" },
  receipt: { label: "ورود کالا", tone: "success" },
  order_out: { label: "خروج بابت سفارش", tone: "info" },
  order_return: { label: "برگشت از سفارش", tone: "orange" },
  adjustment: { label: "اصلاح موجودی", tone: "warning" },
  damage: { label: "ضایعات / کسری", tone: "danger" },
  transfer_out: { label: "انتقال (خروج)", tone: "violet" },
  transfer_in: { label: "انتقال (ورود)", tone: "brand" },
  stocktake: { label: "انبارگردانی", tone: "pink" },
};

export const BUSINESS_TYPES: Record<string, string> = {
  retail: "فروشگاه / خرده‌فروشی", ecommerce: "فروشگاه اینترنتی", wholesale: "پخش و عمده‌فروشی",
  warehouse_3pl: "انبارداری و لجستیک (3PL)", manufacturing: "تولیدی / صنعتی", healthcare: "بیمارستان و مراکز درمانی",
  food: "مواد غذایی و زنجیره سرد", other: "سایر",
};
export const EMPLOYEE_RANGES: Record<string, string> = {
  "1-10": "۱ تا ۱۰", "11-50": "۱۱ تا ۵۰", "51-200": "۵۱ تا ۲۰۰", "201-1000": "۲۰۱ تا ۱۰۰۰", "1000+": "بیش از ۱۰۰۰",
};
export const ORDER_VOLUMES: Record<string, string> = {
  "<100": "کمتر از ۱۰۰", "100-1000": "۱۰۰ تا ۱۰۰۰", "1000-10000": "۱۰۰۰ تا ۱۰٬۰۰۰", "10000+": "بیش از ۱۰٬۰۰۰",
};
export const FEATURES: Record<string, string> = {
  transport: "حمل‌ونقل", warehouse: "انبارداری", stocktaking: "انبارگردانی",
  accounting: "گزارش مالی", reports: "گزارش‌گیری", api: "اتصال API",
};
/** «چطور با ما آشنا شدید؟» */
export const REFERRAL_SOURCES: Record<string, string> = {
  search: "گوگل / جستجو", instagram: "اینستاگرام", linkedin: "لینکدین", telegram: "تلگرام",
  referral: "معرفی دوست یا همکار", event: "نمایشگاه / رویداد", ads: "تبلیغات", other: "سایر",
};
/** متن نمایشی منبع آشنایی (برای «سایر»، همان چیزی که متقاضی نوشته) */
export function referralLabel(source?: string | null, detail?: string | null) {
  if (!source) return null;
  const label = REFERRAL_SOURCES[source] ?? source;
  return detail ? (source === "other" ? detail : `${label} — ${detail}`) : label;
}
export const REQUEST_STATUS: Record<string, { label: string; tone: Tone }> = {
  pending: { label: "در انتظار", tone: "warning" },
  approved: { label: "تأییدشده", tone: "success" },
  rejected: { label: "ردشده", tone: "danger" },
};
export const PACKAGE_SIZES: Record<string, string> = {
  xs: "کوچک (XS)", s: "متوسط (S)", m: "عادی (M)", l: "بزرگ (L)", xl: "بسیار بزرگ (XL)",
};

export const VEHICLE_STATUS_TONE: Record<string, Tone> = {
  available: "success", on_route: "info", maintenance: "warning", inactive: "muted", busy: "brand",
};
