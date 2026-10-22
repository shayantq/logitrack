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
    monthly: null, fromMonthly: 9_000_000, limits: { warehouses: "نامحدود", drivers: "نامحدود", orders: "نامحدود", users: "نامحدود" },
    includesTitle: "همه امکانات حرفه‌ای، به‌علاوه:",
    includes: ["انبار، راننده و کاربر نامحدود", "پشتیبان اختصاصی", "راه‌اندازی کامل و حضوری", "آموزش تیم شما"],
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

/** پیشنهاد مشتریان اولیه (برای حذف: null) */
export const EARLY_OFFER: string | null = "ویژه ۲۰ سازمان اول: ۵۰ درصد تخفیف در سال اول و راه‌اندازی رایگان";

export const planById = (id: string | null | undefined) => PLANS.find(p => p.id === id);
