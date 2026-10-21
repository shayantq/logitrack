/**
 * تعرفه‌ها — تنها جایی که قیمت و امکانات پلن‌ها تعریف می‌شود (صفحه /pricing و فرم درخواست از همین می‌خوانند).
 * مبالغ به تومان در ماه؛ پرداخت سالانه = ۱۰ برابر ماهانه (۲ ماه رایگان).
 */
export type PlanId = "trial" | "basic" | "pro" | "enterprise";

export type Plan = {
  id: PlanId;
  name: string;
  tagline: string;
  /** null = توافقی */
  monthly: number | null;
  /** «از ... تومان» برای پلن توافقی */
  fromMonthly?: number;
  limits: { warehouses: string; drivers: string; orders: string; users: string };
  cta: string;
  highlight?: boolean;
};

export const ANNUAL_MONTHS = 10;

export const PLANS: Plan[] = [
  {
    id: "trial", name: "آزمایشی", tagline: "۳۰ روز رایگان با همه امکانات، بدون نیاز به پرداخت",
    monthly: 0, limits: { warehouses: "۱", drivers: "۳", orders: "۱۰۰", users: "۲" }, cta: "شروع رایگان",
  },
  {
    id: "basic", name: "پایه", tagline: "برای کسب‌وکارهای کوچک با یک انبار",
    monthly: 1_500_000, limits: { warehouses: "۱", drivers: "تا ۵", orders: "۵۰۰", users: "۳" }, cta: "انتخاب پایه",
  },
  {
    id: "pro", name: "حرفه‌ای", tagline: "انبار و ناوگان چندشهری با نقطه سفارش هوشمند",
    monthly: 3_900_000, limits: { warehouses: "تا ۳", drivers: "تا ۲۵", orders: "۳٬۰۰۰", users: "۱۰" }, cta: "انتخاب حرفه‌ای", highlight: true,
  },
  {
    id: "enterprise", name: "سازمانی", tagline: "برای پخش‌کننده‌های بزرگ با نیاز اختصاصی",
    monthly: null, fromMonthly: 9_000_000, limits: { warehouses: "نامحدود", drivers: "نامحدود", orders: "نامحدود", users: "نامحدود" }, cta: "تماس با فروش",
  },
];

/** جدول مقایسه: true = دارد، false = ندارد، یا متن */
export const FEATURES: { label: string; values: Record<PlanId, boolean | string> }[] = [
  { label: "ثبت سفارش، تخصیص خودرو و برنامه رانندگان", values: { trial: true, basic: true, pro: true, enterprise: true } },
  { label: "صفحه پیگیری سفارش و نظرسنجی مشتری", values: { trial: true, basic: true, pro: true, enterprise: true } },
  { label: "دفتر گردش کالا و گزارش اکسل و PDF", values: { trial: true, basic: true, pro: true, enterprise: true } },
  { label: "احراز هویت، پورسانت و امتیاز رانندگان", values: { trial: true, basic: true, pro: true, enterprise: true } },
  { label: "انبارگردانی کور", values: { trial: true, basic: false, pro: true, enterprise: true } },
  { label: "نقطه سفارش هوشمند و برآورد سرمایه خرید", values: { trial: true, basic: false, pro: true, enterprise: true } },
  { label: "گزارش با لوگو و رنگ سازمان", values: { trial: true, basic: false, pro: true, enterprise: true } },
  { label: "پشتیبانی", values: { trial: "تیکت", basic: "تیکت", pro: "تیکت و تلفن", enterprise: "پشتیبان اختصاصی" } },
  { label: "راه‌اندازی و ورود اطلاعات اولیه", values: { trial: false, basic: false, pro: "ورود کاتالوگ از اکسل", enterprise: "حضوری و کامل" } },
];

/** پیشنهاد مشتریان اولیه (برای حذف: null) */
export const EARLY_OFFER: string | null = "۲۰ سازمان اول: ۵۰٪ تخفیف سال اول با قیمت ثابت، و راه‌اندازی رایگان";

export const planById = (id: string | null | undefined) => PLANS.find(p => p.id === id);
