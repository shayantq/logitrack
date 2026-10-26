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
  status_out: { label: "تغییر وضعیت (خروج)", tone: "muted" },
  status_in: { label: "تغییر وضعیت (ورود)", tone: "muted" },
  move_out: { label: "جابه‌جایی (خروج از محل)", tone: "muted" },
  move_in: { label: "جابه‌جایی (ورود به محل)", tone: "muted" },
  supplier_return: { label: "برگشت به تأمین‌کننده", tone: "orange" },
};

/** وضعیت کیفی موجودی — هم‌خوان با app/core/wms.py */
export type StockStatus = "available" | "pending" | "quarantine" | "blocked" | "rejected" | "defective" | "damaged" | "repair" | "in_transit";
export const STOCK_STATUS: Record<StockStatus, { label: string; tone: Tone; hint: string }> = {
  available: { label: "تأییدشده (سالم)", tone: "success", hint: "قابل فروش و مصرف — تنها وضعیت قابل تخصیص" },
  pending: { label: "در انتظار بازرسی", tone: "info", hint: "کالای تازه‌رسیده یا مرجوعی که هنوز بازرسی نشده" },
  quarantine: { label: "قرنطینه", tone: "warning", hint: "نگه‌داشته برای بررسی بیشتر" },
  blocked: { label: "توقیف", tone: "danger", hint: "به دستور مدیریت؛ فقط ادمین آزادش می‌کند" },
  rejected: { label: "مردود", tone: "danger", hint: "در بازرسی رد شد؛ برگشت به تأمین‌کننده یا امحا" },
  defective: { label: "معیوب", tone: "orange", hint: "نقص فنی؛ تعمیر یا مرجوع" },
  damaged: { label: "آسیب‌دیده", tone: "orange", hint: "آسیب فیزیکی (شکستگی، خیسی، بسته‌بندی)" },
  repair: { label: "در تعمیر", tone: "violet", hint: "پس از تعمیر دوباره بازرسی می‌شود" },
  in_transit: { label: "در راه", tone: "brand", hint: "سفارش انتقال ارسال شده و هنوز در مقصد دریافت نشده" },
};
export const stockStatusLabel = (s: string) => STOCK_STATUS[s as StockStatus]?.label ?? s;

/** اسناد انبار */
export const DOCUMENT_TYPES: Record<string, { label: string; tone: Tone }> = {
  opening: { label: "موجودی اول دوره", tone: "muted" },
  receipt: { label: "رسید ورود کالا", tone: "success" },
  order_issue: { label: "حواله خروج سفارش", tone: "info" },
  order_return: { label: "برگشت از سفارش", tone: "orange" },
  adjustment: { label: "اصلاحیه موجودی", tone: "warning" },
  write_off: { label: "ضایعات و کسری", tone: "danger" },
  transfer: { label: "انتقال بین انبارها", tone: "violet" },
  status_change: { label: "تغییر وضعیت کیفی", tone: "brand" },
  stocktake: { label: "اصلاحیه انبارگردانی", tone: "pink" },
  reversal: { label: "سند برگشت", tone: "muted" },
  inbound_receipt: { label: "رسید دریافت کالا", tone: "success" },
  inspection: { label: "بازرسی کیفی", tone: "info" },
  putaway: { label: "جانمایی", tone: "brand" },
  location_move: { label: "جابه‌جایی بین محل‌ها", tone: "violet" },
  transfer_ship: { label: "ارسال سفارش انتقال", tone: "violet" },
  transfer_receive: { label: "دریافت سفارش انتقال", tone: "brand" },
  pick: { label: "برداشت (پیکینگ)", tone: "info" },
  replenishment: { label: "تأمین مجدد", tone: "brand" },
  scrap: { label: "امحا", tone: "danger" },
  supplier_return: { label: "برگشت به تأمین‌کننده", tone: "orange" },
  disposition: { label: "تعیین تکلیف کیفی", tone: "muted" },
};
export const DOCUMENT_STATUS: Record<string, { label: string; tone: Tone }> = {
  draft: { label: "پیش‌نویس", tone: "muted" },
  posted: { label: "قطعی", tone: "success" },
  reversed: { label: "برگشت‌خورده", tone: "danger" },
  canceled: { label: "لغوشده", tone: "muted" },
};

/** انواع انبار */
export const WAREHOUSE_TYPES: Record<string, { label: string; hint: string }> = {
  general: { label: "انبار عمومی", hint: "نگهداری و ارسال سفارش" },
  finished_goods: { label: "انبار محصول نهایی", hint: "کالای آماده فروش؛ ارسال سفارش" },
  distribution: { label: "مرکز توزیع", hint: "ارسال سفارش به مشتریان" },
  raw_materials: { label: "انبار مواد اولیه", hint: "مصرف داخلی؛ بدون ارسال سفارش" },
  quarantine: { label: "انبار قرنطینه", hint: "کالای رسیده با وضعیت «قرنطینه» ثبت می‌شود" },
  returns: { label: "انبار مرجوعی", hint: "کالای برگشتی؛ پیش‌فرض قرنطینه" },
  transit: { label: "انبار در راه", hint: "فقط با سند انتقال پر و خالی می‌شود" },
  site: { label: "سایت / مجتمع انبار", hint: "فقط گروه‌بندی انبارها؛ کالا نگه نمی‌دارد" },
};

/** طرف‌های تجاری */
export const PARTNER_ROLES: Record<string, { label: string; tone: Tone }> = {
  supplier: { label: "تأمین‌کننده", tone: "brand" },
  customer: { label: "مشتری", tone: "success" },
  carrier: { label: "شرکت حمل", tone: "violet" },
  owner: { label: "مالک کالا (امانی)", tone: "orange" },
};

/** محل‌های انبار — هم‌خوان با app/core/wms.py */
export const LOCATION_LEVELS: Record<string, string> = {
  zone: "منطقه", aisle: "راهرو", rack: "قفسه", shelf: "طبقه", bin: "خانه / جایگاه",
};
export const LOCATION_LEVEL_ORDER = ["zone", "aisle", "rack", "shelf", "bin"];
export const LOCATION_TYPES: Record<string, { label: string; tone: Tone; hint: string }> = {
  receiving: { label: "تخلیه و دریافت", tone: "info", hint: "رسید کالا اینجا ثبت می‌شود؛ قابل تخصیص نیست" },
  storage: { label: "نگهداری", tone: "success", hint: "مقصد جانمایی؛ قابل تخصیص به سفارش" },
  picking: { label: "برداشت", tone: "brand", hint: "قفسه برداشت سفارش؛ قابل تخصیص" },
  quarantine: { label: "قرنطینه", tone: "warning", hint: "مقصد کالای غیرقابل‌استفاده" },
  staging: { label: "آماده‌سازی", tone: "violet", hint: "تجمیع پیش از ارسال یا جانمایی" },
  shipping: { label: "بارگیری و ارسال", tone: "muted", hint: "سکوی بارگیری" },
};

/** رسید دریافت */
export const RECEIPT_TYPES: Record<string, string> = {
  purchase: "خرید از تأمین‌کننده", transfer: "انتقال از انبار در راه", return: "مرجوعی مشتری", unexpected: "ورود پیش‌بینی‌نشده",
};
export const RECEIPT_STATUS: Record<string, { label: string; tone: Tone }> = {
  open: { label: "در انتظار ورود", tone: "info" },
  receiving: { label: "در حال دریافت", tone: "warning" },
  closed: { label: "بسته‌شده", tone: "success" },
  canceled: { label: "لغوشده", tone: "muted" },
};
export const DISCREPANCY: Record<string, { label: string; tone: Tone }> = {
  shortage: { label: "کسری", tone: "danger" },
  over: { label: "اضافه تحویل", tone: "warning" },
  unexpected_item: { label: "خارج از برنامه", tone: "orange" },
};

/** جانمایی */
export const PUTAWAY_STATUS: Record<string, { label: string; tone: Tone }> = {
  open: { label: "باز", tone: "info" },
  partial: { label: "نیمه‌انجام", tone: "warning" },
  done: { label: "انجام‌شده", tone: "success" },
  canceled: { label: "لغوشده", tone: "muted" },
};
/** فصل‌های ۱۱ تا ۱۵ */
export const BACKORDER_STATUS: Record<string, { label: string; tone: Tone }> = {
  open: { label: "در انتظار موجودی", tone: "warning" },
  allocated: { label: "تخصیص‌یافته", tone: "success" },
  fulfilled: { label: "ارسال‌شده", tone: "muted" },
  canceled: { label: "لغوشده", tone: "muted" },
};
export const TRANSFER_STATUS: Record<string, { label: string; tone: Tone }> = {
  open: { label: "آماده ارسال", tone: "info" },
  in_transit: { label: "در راه", tone: "brand" },
  received: { label: "دریافت کامل", tone: "success" },
  closed: { label: "بسته‌شده", tone: "muted" },
  canceled: { label: "لغوشده", tone: "muted" },
};
export const PICK_STRATEGIES: Record<string, { label: string; hint: string }> = {
  single: { label: "تک‌سفارشی", hint: "یک سفارش در هر فهرست" },
  batch: { label: "دسته‌ای", hint: "چند سفارش انتخابی با یک مسیر" },
  wave: { label: "موجی", hint: "همه سفارش‌های آماده یک روز تحویل" },
  zone: { label: "منطقه‌ای", hint: "فقط محل‌های یک منطقه" },
};
export const PICK_LIST_STATUS: Record<string, { label: string; tone: Tone }> = {
  open: { label: "باز", tone: "info" },
  in_progress: { label: "در حال برداشت", tone: "warning" },
  picked: { label: "برداشت‌شده", tone: "success" },
  canceled: { label: "لغوشده", tone: "muted" },
};
export const FULFILLMENT: Record<string, { label: string; tone: Tone }> = {
  open: { label: "آماده‌نشده", tone: "muted" },
  picking: { label: "در حال برداشت", tone: "warning" },
  picked: { label: "برداشت‌شده", tone: "info" },
  packed: { label: "بسته‌بندی‌شده", tone: "brand" },
  shipped: { label: "ارسال‌شده", tone: "success" },
};
export const SHIPMENT_STATUS: Record<string, { label: string; tone: Tone }> = {
  open: { label: "در حال بارگیری", tone: "warning" },
  dispatched: { label: "تحویل راننده شد", tone: "success" },
  canceled: { label: "لغوشده", tone: "muted" },
};
export const DISPOSITION_ACTIONS: Record<string, { label: string; tone: Tone; hint: string }> = {
  scrap: { label: "امحا (ضایعات)", tone: "danger", hint: "کالا با سند امحا از موجودی خارج می‌شود" },
  repair: { label: "ارسال به تعمیر", tone: "violet", hint: "وضعیت «در تعمیر» در همان محل" },
  return_to_supplier: { label: "برگشت به تأمین‌کننده", tone: "orange", hint: "خروج با سند برگشت، با ارجاع به رسید خرید" },
  reinspect: { label: "بازرسی دوباره", tone: "info", hint: "«در انتظار بازرسی» — فقط بازرسی آن را قابل تخصیص می‌کند" },
};

export const PUTAWAY_PROBLEMS: Record<string, string> = {
  destination_full: "محل مقصد پر است",
  destination_blocked: "محل مقصد مسدود/خراب است",
  item_damaged: "کالا آسیب دیده است",
  item_missing: "کالا در محل مبدأ نیست",
  scan_mismatch: "اسکن اشتباه",
  rule_violation: "نقض ظرفیت یا قاعده محل",
};
export const CARRIER_SERVICES: Record<string, string> = {
  road: "جاده‌ای", rail: "ریلی", air: "هوایی", sea: "دریایی", courier: "پیک", post: "پست",
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
