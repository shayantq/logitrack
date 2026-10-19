/**
 * محتوای راهنمای تعاملی. هر راهنما فقط بار اول خودکار باز می‌شود (وضعیتش در users.tour_state ذخیره می‌شود)
 * و از منوی کاربر ← «راهنمای استفاده» دوباره قابل دیدن است.
 *
 * target: انتخابگر CSS عنصری که روشن می‌شود؛ اگر روی صفحه نبود (مثلاً منوی کناری در موبایل)، کارت وسط صفحه می‌آید.
 */
import type { Role } from "@/lib/labels";

export type TourStep = { target?: string; title: string; body: string };
export type Tour = { id: string; roles: Role[]; path?: RegExp; steps: TourStep[] };

const nav = (group: string) => `[data-tour="nav-${group}"]`;
const HEADER_STEPS: TourStep[] = [
  { target: "[data-testid=theme-toggle]", title: "روز و شب", body: "با یک کلیک بین تم روشن و تاریک جابه‌جا شوید؛ انتخابتان روی همین مرورگر می‌ماند." },
  { target: "[data-testid=user-menu]", title: "حساب شما و راهنما", body: "تغییر رمز، خروج و «راهنمای استفاده» اینجاست — هر وقت خواستید همین راهنما یا راهنمای صفحه‌ای که در آن هستید را دوباره ببینید." },
];

export const TOURS: Tour[] = [
  // ---------------------------------------------------------------- راهنمای اصلی هر نقش
  {
    id: "main-admin", roles: ["org_admin"], steps: [
      { title: "به پنل سازمان خوش آمدید 👋", body: "در چند قدم کوتاه بخش‌های اصلی را نشانتان می‌دهیم. با «بعدی» جلو بروید یا هر وقت خواستید «رد شدن» را بزنید." },
      { target: nav("عملیات"), title: "عملیات روزانه", body: "ثبت و پیگیری سفارش‌ها، نقشه ارسال‌ها، برنامه کاری رانندگان و پاسخ به تیکت‌های مشتری و راننده." },
      { target: nav("انبار"), title: "انبار و کالا", body: "انبارها، کاتالوگ و موجودی، انبارگردانی، دفتر گردش کالا و «نقطه سفارش هوشمند» که می‌گوید کِی و چقدر خرید کنید." },
      { target: nav("گزارش‌ها"), title: "گزارش‌ها", body: "خروجی اکسل و PDF با سربرگ سازمان، مالی حمل‌ونقل و «برآورد سرمایه خرید» برای بودجه‌بندی نقدینگی ماه‌های آینده." },
      { target: nav("تیم"), title: "تیم و ناوگان", body: "خودروها، کاربران، احراز هویت رانندگان تازه، درخواست‌های مرخصی و برترین رانندگان." },
      { target: nav("تنظیمات"), title: "تنظیمات سازمان", body: "پروفایل و لوگو، گزارش فعالیت کاربران و سطح‌ها و پورسانت رانندگان." },
      { target: "[data-testid=notifications-bell]", title: "اعلان‌ها", body: "کمبود موجودی، سفارش ناموفق، تیکت تازه و درخواست رانندگان اینجا می‌آید؛ با کلیک روی هر اعلان مستقیم به همان مورد می‌روید." },
      ...HEADER_STEPS,
    ],
  },
  {
    id: "main-manager", roles: ["warehouse_manager"], steps: [
      { title: "به پنل مدیر انبار خوش آمدید 👋", body: "در چند قدم کوتاه بخش‌هایی را که با آن‌ها کار دارید نشانتان می‌دهیم." },
      { target: nav("عملیات"), title: "عملیات", body: "سفارش‌هایی که از انبار شما ارسال می‌شوند، نقشه ارسال‌ها و برنامه رانندگان." },
      { target: nav("انبار"), title: "انبار شما", body: "موجودی، ثبت ورود و خروج کالا، انبارگردانی کور، دفتر گردش و نقطه سفارش هوشمند — فقط برای انبار خودتان." },
      { target: nav("گزارش‌ها"), title: "گزارش‌ها", body: "گزارش موجودی، سفارش‌ها، دفتر گردش و نقطه سفارش انبار شما به‌صورت اکسل یا PDF." },
      { target: "[data-testid=notifications-bell]", title: "اعلان‌ها", body: "هشدار کالاهای انبار شما که به نقطه سفارش رسیده‌اند و سفارش‌های ناموفق؛ کلیک روی اعلان شما را به همان کالا یا سفارش می‌برد." },
      ...HEADER_STEPS,
    ],
  },
  {
    id: "main-driver", roles: ["driver"], steps: [
      { title: "سلام! به پنل راننده خوش آمدید 👋", body: "در چند قدم کوتاه نشانتان می‌دهیم سفارش‌ها، برنامه و درخواست‌هایتان کجاست." },
      { target: nav("راننده"), title: "منوی شما", body: "سفارش‌های امروز، برنامه و کارنامه روزانه، درخواست مرخصی یا تغییر خودرو، پشتیبانی و پروفایل." },
      ...HEADER_STEPS,
    ],
  },
  {
    id: "main-platform", roles: ["platform_admin", "platform_support"], steps: [
      { title: "به پنل پلتفرم خوش آمدید 👋", body: "مدیریت سازمان‌ها، درخواست‌های ثبت سازمان و تیکت‌های پشتیبانی از همین‌جاست." },
      { target: nav("پلتفرم"), title: "بخش‌های پلتفرم", body: "سازمان‌ها و آمارشان، درخواست‌های ثبت سازمان جدید (تأیید یا رد با دلیل) و تیکت‌هایی که سازمان‌ها ارجاع داده‌اند." },
      ...HEADER_STEPS,
    ],
  },

  // ---------------------------------------------------------------- راهنمای صفحه‌ها (اولین بازدید)
  {
    id: "page-orders", roles: ["org_admin", "warehouse_manager"], path: /^\/app\/orders\/?$/, steps: [
      { target: "[data-testid=new-order]", title: "ثبت سفارش", body: "کالاها، مشتری، مقصد و بازه تحویل را وارد کنید؛ موجودی همان لحظه کسر و بهترین رانندگان با امتیاز و دلیل پیشنهاد می‌شوند." },
      { target: "[data-testid=orders-count]", title: "جستجو و فیلتر", body: "با کد، مشتری، کالا، راننده، پلاک، روز تحویل یا استان جستجو کنید؛ فیلترها در آدرس صفحه می‌مانند و قابل اشتراک‌اند." },
    ],
  },
  {
    id: "page-inventory", roles: ["org_admin", "warehouse_manager"], path: /^\/app\/inventory\/?$/, steps: [
      { target: "[data-testid=new-movement]", title: "ورود و خروج کالا", body: "هر تغییر موجودی (رسید خرید، ضایعات، اصلاح، انتقال بین انبارها) با علت در دفتر گردش ثبت می‌شود." },
      { target: "[data-testid=catalog-import-open]", title: "ورود گروهی از اکسل", body: "قالب اکسل را بگیرید، کالاها را پر کنید و یک‌جا وارد کنید — اول همه ردیف‌ها بررسی می‌شوند." },
      { target: "[data-testid=product-row]", title: "جزئیات هر کالا", body: "روی هر کالا بزنید: قیمت تاریخ‌دار، بهای خرید، تنوع‌ها و موجودی در هر انبار." },
    ],
  },
  {
    id: "page-reorder", roles: ["org_admin", "warehouse_manager"], path: /^\/app\/reorder\/?$/, steps: [
      { target: "[data-tour=rop-stats]", title: "وضعیت خرید در یک نگاه", body: "چند کالا ناموجودند، چند کالا زیر موجودی اطمینان‌اند و چند کالا به زمان سفارش رسیده‌اند." },
      { target: "[data-tour=rop-formula]", title: "فرمول، شفاف", body: "نقطه سفارش = فروش دوره تأمین + موجودی اطمینان. اینجا ببینید هر عدد از کجا می‌آید." },
      { target: "[data-testid=rop-table]", title: "هر کالا، جدا", body: "روی هر ردیف بزنید تا محاسبه با عددهای واقعی همان کالا را ببینید و زمان تأمین یا سطح خدمت اختصاصی بدهید." },
      { target: "[data-tour=rop-auto]", title: "خودکار کنید", body: "در حالت خودکار نقطه سفارش هر شب با فروش تازه به‌روز می‌شود و هشدار کمبود و گزارش‌ها از همان استفاده می‌کنند." },
    ],
  },
  {
    id: "page-capital", roles: ["org_admin"], path: /^\/app\/capital\/?$/, steps: [
      { target: "[data-tour=capital-controls]", title: "سناریو بسازید", body: "افق برنامه، انبار، تورم ماهانه بها و رشد فروش را عوض کنید؛ عددها فوراً دوباره حساب می‌شوند." },
      { target: "[data-tour=capital-stats]", title: "نقدینگی لازم", body: "کل سرمایه خرید، پرهزینه‌ترین ماه و میانگین ماهانه برای بودجه‌بندی." },
      { target: "[data-testid=capital-bars]", title: "ماه‌به‌ماه", body: "هر ستون خرید همان ماه است و نوار کم‌رنگ پشتش جمع تجمعی؛ جزئیات هر کالا در جدول پایین صفحه." },
    ],
  },
  {
    id: "page-stocktakes", roles: ["org_admin", "warehouse_manager"], path: /^\/app\/stocktakes\/?$/, steps: [
      { target: "[data-testid=stocktake-overview]", title: "سررسید هر انبار", body: "دوره انبارگردانی هر انبار و نوبت بعدی؛ سررسید گذشته با نشان قرمز مشخص می‌شود." },
      { target: "[data-testid=stocktake-new]", title: "شمارش کور", body: "انبارگردانی کامل یا بخشی را شروع کنید؛ موجودی سیستم تا مرحله بررسی به شمارنده نشان داده نمی‌شود." },
    ],
  },
  {
    id: "page-driver", roles: ["driver"], path: /^\/app\/driver\/?$/, steps: [
      { target: "[data-testid=driver-vehicle]", title: "خودروی شما", body: "مشخصات خودرو و ظرفیت؛ تغییر خودرو را از «درخواست مرخصی / خودرو» بخواهید." },
      { target: "[data-testid=my-schedule]", title: "برنامه کاری", body: "شیفت‌های این هفته؛ فقط در شیفت‌ها برایتان سفارش پیشنهاد می‌شود." },
      { target: "[data-testid=quick-leave]", title: "مرخصی", body: "مرخصی فوری یا عادی را با علت درخواست کنید؛ با تأیید ادمین، سفارش‌های بارگیری‌نشده‌تان آزاد می‌شوند." },
    ],
  },
];

export function mainTourFor(role: Role): Tour | undefined {
  return TOURS.find(t => !t.path && t.roles.includes(role));
}

export function pageTourFor(role: Role, pathname: string): Tour | undefined {
  return TOURS.find(t => t.path && t.roles.includes(role) && t.path.test(pathname));
}
