/**
 * تعرفه‌ها — تنها جایی که قیمت و امکانات پلن‌ها تعریف می‌شود (صفحه /pricing و فرم درخواست از همین می‌خوانند).
 * مبالغ به تومان در ماه؛ پرداخت سالانه = ۱۰ برابر ماهانه (۲ ماه رایگان).
 */
export type PlanId = "trial" | "basic" | "pro" | "enterprise";

export type Plan = {
  id: PlanId;
  name: string;
  /** برای چه کسب‌وکاری مناسب است — یک جمله کوتاه */
  audience: string;
  /** null = توافقی */
  monthly: number | null;
  /** «از ... تومان» برای پلن توافقی */
  fromMonthly?: number;
  limits: { warehouses: string; drivers: string; orders: string; users: string };
  /** عنوان فهرست امکانات کارت؛ مثلاً «همه امکانات پایه، به‌علاوه:» */
  includesTitle: string;
  includes: string[];
  cta: string;
  highlight?: boolean;
};

export const ANNUAL_MONTHS = 10;
export const TRIAL_DAYS = 30;

export const PLANS: Plan[] = [
  {
    id: "trial", name: "آزمایشی", audience: "برای آشنایی با سامانه، بدون پرداخت",
    monthly: 0, limits: { warehouses: "۱", drivers: "۳", orders: "۱۰۰", users: "۲" },
    includesTitle: "در دوره آزمایشی:",
    includes: ["همه امکانات پلن حرفه‌ای", "پنل موبایل راننده", "صفحه پیگیری سفارش برای مشتری", "پشتیبانی تیکتی"],
    cta: "شروع رایگان",
  },
  {
    id: "basic", name: "پایه", audience: "برای کسب‌وکارهای کوچک با یک انبار",
    monthly: 1_500_000, limits: { warehouses: "۱", drivers: "۵", orders: "۵۰۰", users: "۳" },
    includesTitle: "امکانات اصلی:",
    includes: ["ثبت سفارش و تخصیص خودکار خودرو", "دفتر گردش کالا و هشدار کمبود", "پنل موبایل راننده", "گزارش اکسل و PDF"],
    cta: "انتخاب پلن پایه",
  },
  {
    id: "pro", name: "حرفه‌ای", audience: "برای پخش در چند شهر با چند انبار",
    monthly: 3_900_000, limits: { warehouses: "۳", drivers: "۲۵", orders: "۳٬۰۰۰", users: "۱۰" },
    includesTitle: "همه امکانات پایه، به‌علاوه:",
    includes: ["نقطه سفارش هوشمند و برآورد خرید", "انبارگردانی کور", "گزارش با لوگو و رنگ سازمان", "ورود کالاها از اکسل", "پشتیبانی تلفنی"],
    cta: "انتخاب پلن حرفه‌ای", highlight: true,
  },
  {
    id: "enterprise", name: "سازمانی", audience: "برای شرکت‌های پخش بزرگ با نیاز اختصاصی",
    // سقف‌ها متناسب با ظرفیت سرور مشترک فعلی؛ بیشتر از این روی سرور اختصاصی و با قرارداد جدا
    monthly: null, fromMonthly: 9_000_000, limits: { warehouses: "۱۰", drivers: "۱۰۰", orders: "۲۰٬۰۰۰", users: "۵۰" },
    includesTitle: "همه امکانات حرفه‌ای، به‌علاوه:",
    includes: ["تا ۱۰ انبار و ۱۰۰ راننده", "پشتیبان اختصاصی", "راه‌اندازی کامل و حضوری", "آموزش تیم شما", "ظرفیت بیشتر روی سرور اختصاصی (توافقی)"],
    cta: "مشاوره رایگان",
  },
];

/** جدول مقایسه: true = دارد، false = ندارد، یا متن */
export type FeatureRow = { label: string; values: Record<PlanId, boolean | string> };
const all: Record<PlanId, boolean> = { trial: true, basic: true, pro: true, enterprise: true };
const proUp: Record<PlanId, boolean> = { trial: true, basic: false, pro: true, enterprise: true };
const limit = (key: keyof Plan["limits"]) => Object.fromEntries(PLANS.map(p => [p.id, p.limits[key]])) as Record<PlanId, string>;

export const FEATURE_GROUPS: { title: string; rows: FeatureRow[] }[] = [
  {
    title: "ظرفیت",
    rows: [
      { label: "تعداد انبار", values: limit("warehouses") },
      { label: "تعداد راننده", values: limit("drivers") },
      { label: "سفارش در ماه", values: limit("orders") },
      { label: "کاربر پنل مدیریت", values: limit("users") },
    ],
  },
  {
    title: "سفارش و ارسال",
    rows: [
      { label: "ثبت سفارش چندقلمی و تخصیص خودکار خودرو", values: all },
      { label: "برنامه هفتگی و مرخصی رانندگان", values: all },
      { label: "نقشه ارسال‌ها و مسیر شهربه‌شهر", values: all },
      { label: "صفحه پیگیری و نظرسنجی مشتری", values: all },
    ],
  },
  {
    title: "انبار",
    rows: [
      { label: "دفتر گردش کالا و انتقال بین انبارها", values: all },
      { label: "هشدار خودکار کمبود موجودی", values: all },
      { label: "انبارگردانی کور", values: proUp },
      { label: "نقطه سفارش هوشمند و برآورد سرمایه خرید", values: proUp },
    ],
  },
  {
    title: "رانندگان و گزارش‌ها",
    rows: [
      { label: "احراز هویت آنلاین رانندگان", values: all },
      { label: "پورسانت، سطح‌بندی و امتیاز رانندگان", values: all },
      { label: "داشبورد مدیریتی و خروجی اکسل و PDF", values: all },
      { label: "گزارش با لوگو و رنگ سازمان", values: proUp },
    ],
  },
  {
    title: "پشتیبانی و راه‌اندازی",
    rows: [
      { label: "پشتیبانی", values: { trial: "تیکت", basic: "تیکت", pro: "تیکت و تلفن", enterprise: "پشتیبان اختصاصی" } },
      { label: "راه‌اندازی و ورود اطلاعات اولیه", values: { trial: false, basic: false, pro: "ورود کالاها از اکسل", enterprise: "کامل و حضوری" } },
    ],
  },
];

/** پرسش‌های پرتکرار درباره خرید */
export const PRICING_FAQ: { q: string; a: string }[] = [
  { q: "هزینه به ازای هر کاربر حساب می‌شود؟", a: "خیر. قیمت هر پلن برای کل سازمان است و تا سقف کاربران همان پلن، هزینه اضافه‌ای ندارد." },
  { q: "بعد از ۳۰ روز آزمایشی چه می‌شود؟", a: "با انتخاب یکی از پلن‌ها، کار را با همان سازمان و همه اطلاعاتی که ثبت کرده‌اید ادامه می‌دهید." },
  { q: "اگر تعداد سفارش‌ها از سقف پلن بیشتر شود؟", a: "کار شما متوقف نمی‌شود. با شما تماس می‌گیریم تا در صورت نیاز، پلن مناسب‌تری انتخاب کنید." },
  { q: "می‌توانم پلن را عوض کنم؟", a: "بله. هر زمان خواستید، با پشتیبانی تماس بگیرید تا پلن شما ارتقا یا تغییر کند." },
  { q: "پرداخت چطور انجام می‌شود؟", a: "پس از انتخاب پلن، فاکتور رسمی به نام سازمان شما صادر و ارسال می‌شود." },
];

// ---------------------------------------------------------------------------
// پلن سفارشی (ماشین‌حساب): نرخ‌ها به تومان در ماه.
// طوری تنظیم شده که هر پلن ثابت از ساختن همان امکانات به‌صورت سفارشی ارزان‌تر باشد
// (پایه ≈ ۱٬۷۰۵٬۰۰۰ در برابر ۱٬۵۰۰٬۰۰۰، حرفه‌ای ≈ ۴٬۴۰۰٬۰۰۰ در برابر ۳٬۹۰۰٬۰۰۰).
// ---------------------------------------------------------------------------
export const CUSTOM_RATES = {
  /** سامانه با ۱ انبار، ۱ کاربر، همه امکانات اصلی و پشتیبانی تیکتی */
  base: 1_300_000,
  perExtraWarehouse: 200_000,
  perDriver: 40_000,
  per100Orders: 25_000,
  perExtraUser: 40_000,
};

export type ResourceId = "warehouses" | "drivers" | "orders" | "users";
/** مقادیر مجاز هر اسلایدر؛ سفارش‌ها غیرخطی تا حرکت اسلایدر در عددهای کوچک دقیق باشد */
const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => from + i);
export const RESOURCES: { id: ResourceId; label: string; unit: string; steps: number[]; default: number }[] = [
  { id: "warehouses", label: "تعداد انبار", unit: "انبار", steps: range(1, 10), default: 2 },
  { id: "drivers", label: "تعداد راننده", unit: "راننده", steps: range(1, 100), default: 10 },
  { id: "orders", label: "سفارش در ماه", unit: "سفارش", steps: [100, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 4000, 5000, 7500, 10000, 15000, 20000], default: 1000 },
  { id: "users", label: "کاربر پنل مدیریت", unit: "کاربر", steps: range(1, 50), default: 5 },
];

export type ModuleId = "reorder" | "stocktake" | "branding" | "phone";
export const MODULES: { id: ModuleId; label: string; hint: string; monthly: number }[] = [
  { id: "reorder", label: "نقطه سفارش هوشمند", hint: "پیشنهاد زمان و مقدار خرید و برآورد سرمایه لازم", monthly: 300_000 },
  { id: "stocktake", label: "انبارگردانی کور", hint: "شمارش بدون دیدن موجودی سیستم و تأیید مغایرت", monthly: 120_000 },
  { id: "branding", label: "گزارش با لوگو و رنگ سازمان", hint: "سربرگ اختصاصی در خروجی‌های اکسل و PDF", monthly: 70_000 },
  { id: "phone", label: "پشتیبانی تلفنی", hint: "علاوه بر تیکت، تماس مستقیم با پشتیبانی", monthly: 100_000 },
];

export type CustomConfig = Record<ResourceId, number> & { modules: ModuleId[] };

export function customLines(c: CustomConfig): { label: string; amount: number }[] {
  const r = CUSTOM_RATES;
  const n = (v: number) => v.toLocaleString("fa-IR");
  const lines = [{ label: "سامانه پایه (۱ انبار، ۱ کاربر، پشتیبانی تیکتی)", amount: r.base }];
  if (c.warehouses > 1) lines.push({ label: `${n(c.warehouses - 1)} انبار اضافه`, amount: (c.warehouses - 1) * r.perExtraWarehouse });
  lines.push({ label: `${n(c.drivers)} راننده`, amount: c.drivers * r.perDriver });
  lines.push({ label: `${n(c.orders)} سفارش در ماه`, amount: (c.orders / 100) * r.per100Orders });
  if (c.users > 1) lines.push({ label: `${n(c.users - 1)} کاربر اضافه`, amount: (c.users - 1) * r.perExtraUser });
  for (const m of MODULES) if (c.modules.includes(m.id)) lines.push({ label: m.label, amount: m.monthly });
  return lines;
}

export const customMonthly = (c: CustomConfig) => customLines(c).reduce((sum, l) => sum + l.amount, 0);

/** سقف عددی پلن‌های ثابت برای پیشنهاد پلن ارزان‌تر */
const PLAN_CAPS: Partial<Record<PlanId, Record<ResourceId, number> & { modules: ModuleId[] }>> = {
  basic: { warehouses: 1, drivers: 5, orders: 500, users: 3, modules: [] },
  pro: { warehouses: 3, drivers: 25, orders: 3000, users: 10, modules: ["reorder", "stocktake", "branding", "phone"] },
};

/** ارزان‌ترین پلن ثابتی که همه نیازهای انتخاب‌شده را پوشش می‌دهد و از پلن سفارشی ارزان‌تر است */
export function cheaperPlan(c: CustomConfig): Plan | undefined {
  const total = customMonthly(c);
  return PLANS.find(p => {
    const cap = PLAN_CAPS[p.id];
    if (!cap || p.monthly === null || p.monthly >= total) return false;
    return RESOURCES.every(r => c[r.id] <= cap[r.id]) && c.modules.every(m => cap.modules.includes(m));
  });
}

/** پیکربندی سفارشی از آدرس فرم درخواست (?plan=custom&w=2&d=10&o=1000&u=5&m=reorder,phone) */
const QUERY_KEYS: Record<ResourceId, string> = { warehouses: "w", drivers: "d", orders: "o", users: "u" };
export function customToQuery(c: CustomConfig) {
  const q = new URLSearchParams({ plan: "custom" });
  for (const r of RESOURCES) q.set(QUERY_KEYS[r.id], String(c[r.id]));
  if (c.modules.length) q.set("m", c.modules.join(","));
  return q.toString();
}
export function customFromQuery(search: string): CustomConfig | null {
  const q = new URLSearchParams(search);
  if (q.get("plan") !== "custom") return null;
  const config = { modules: (q.get("m") ?? "").split(",").filter((m): m is ModuleId => MODULES.some(x => x.id === m)) } as CustomConfig;
  for (const r of RESOURCES) {
    const v = Number(q.get(QUERY_KEYS[r.id]));
    config[r.id] = r.steps.includes(v) ? v : r.default;   // مقدار نامعتبر ← پیش‌فرض
  }
  return config;
}
export function customSummary(c: CustomConfig) {
  const n = (v: number) => v.toLocaleString("fa-IR");
  const mods = MODULES.filter(m => c.modules.includes(m.id)).map(m => m.label);
  return `${n(c.warehouses)} انبار، ${n(c.drivers)} راننده، ${n(c.orders)} سفارش در ماه، ${n(c.users)} کاربر`
    + (mods.length ? ` + ${mods.join("، ")}` : "") + ` — ${n(customMonthly(c))} تومان در ماه`;
}

/** پیشنهاد مشتریان اولیه (برای حذف: null) */
export const EARLY_OFFER: string | null = "ویژه ۲۰ سازمان اول: ۵۰ درصد تخفیف در سال اول و راه‌اندازی رایگان";

export const planById = (id: string | null | undefined) => PLANS.find(p => p.id === id);
