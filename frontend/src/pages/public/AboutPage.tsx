/** صفحه «درباره ما»: چرایی، مأموریت، آنچه ساخته‌ایم، اصول، روند همکاری و برای چه کسانی */
import { Link } from "react-router-dom";
import {
  BadgeCheck, CalendarDays, ClipboardList, Coins, Eye, FileSpreadsheet, Fingerprint, Flag, Handshake, Layers, MapPinned,
  MessageSquareWarning, PackageSearch, PhoneOff, Route, ShieldCheck, Smartphone, Sparkles, Truck, Warehouse,
} from "lucide-react";
import { BRAND } from "@/brand";
import { BUSINESS_TYPES } from "@/lib/labels";
import { buttonClass } from "@/ui/primitives";
import { InfoLayout } from "./InfoLayout";
import { CountUp, Reveal, ScrubText, SectionTag } from "./motion";

const PAINS = [
  { icon: FileSpreadsheet, title: "سفارش‌ها پراکنده‌اند", text: "بخشی در دفتر، بخشی در اکسل و بخشی در پیام‌رسان. هیچ‌کس تصویر کامل امروز را ندارد." },
  { icon: Warehouse, title: "موجودی حدسی است", text: "بعد از هر ارسال، مرجوعی یا لغو، عدد موجودی با واقعیت انبار فاصله می‌گیرد." },
  { icon: PhoneOff, title: "راننده پشت خط است", text: "برای فهمیدن این‌که بار کجاست باید تماس گرفت؛ مشتری هم برای پیگیری باید زنگ بزند." },
  { icon: MessageSquareWarning, title: "حساب‌ها شفاف نیست", text: "کمیسیون و عملکرد رانندگان دستی حساب می‌شود و هر ماه محل اختلاف است." },
];

const MODULES = [
  { icon: ClipboardList, title: "سفارش و ارسال", text: "ثبت سفارش، تخصیص راننده و خودرو، نُه وضعیت استاندارد و تاریخچه کامل هر تغییر." },
  { icon: Warehouse, title: "انبار و دفتر گردش", text: "چند انبار، موجودی هر کالا در هر انبار، و دفتری که هر ورود و خروج را با موجودی بعد از آن ثبت می‌کند." },
  { icon: Fingerprint, title: "احراز هویت رانندگان", text: "دعوت با لینک، بارگذاری مدارک و ویدیوی چهره، و تأیید ادمین پیش از شروع کار." },
  { icon: CalendarDays, title: "برنامه کاری و تخصیص هوشمند", text: "شیفت‌ها، مرخصی‌ها و سقف سفارش روزانه؛ و پیشنهاد راننده مناسب برای هر سفارش با ذکر دلیل." },
  { icon: Coins, title: "کمیسیون، سطح و امتیاز", text: "کمیسیون پلکانی بر اساس سطح راننده، امتیاز وزن‌دار از سازمان و مشتری، و رتبه‌بندی رانندگان برتر." },
  { icon: PackageSearch, title: "پیگیری برای مشتری", text: "صفحه پیگیری بدون ثبت‌نام، با محافظت از نشانی گیرنده و لینک نظرسنجی بعد از تحویل." },
];

const PRINCIPLES = [
  { icon: MapPinned, title: "ساخته‌شده برای ایران", text: "تقویم شمسی و وقت ایران، ۳۱ استان، پلاک ایرانی، اعداد فارسی و رابط کاملاً راست‌به‌چپ — از روز اول، نه به‌صورت وصله." },
  { icon: ShieldCheck, title: "داده مال سازمان شماست", text: "داده هر سازمان در لایه پایگاه داده از بقیه جداست و فقط برای خدمت‌رسانی به همان سازمان استفاده می‌شود." },
  { icon: Eye, title: "هر عدد، قابل توضیح", text: "موجودی با دفتر گردش، کمیسیون با فرمول روشن و وضعیت سفارش با تاریخچه. چیزی بی‌صدا عوض نمی‌شود." },
  { icon: Smartphone, title: "موبایل برای میدان", text: "راننده بدون نصب برنامه، روی مرورگر گوشی کار می‌کند؛ هر مرحله با یک لمس ثبت می‌شود." },
  { icon: Sparkles, title: "ساده، حتی برای روز اول", text: "هر نقش فقط همان چیزی را می‌بیند که لازم دارد؛ آموزش طولانی لازم نیست." },
  { icon: BadgeCheck, title: "قاعده‌ها جلوی خطا را می‌گیرند", text: "سفارش فردا امروز تحویل نمی‌شود، تحویل بدون بارگیری ثبت نمی‌شود و کالای لغوشده خودکار به انبار برمی‌گردد." },
];

const JOURNEY = [
  { icon: Flag, title: "ثبت درخواست", text: "فرم سه‌مرحله‌ای را پر می‌کنید و کد پیگیری می‌گیرید." },
  { icon: Eye, title: "بررسی", text: "اطلاعات سازمان بررسی می‌شود؛ نتیجه را با همان کد می‌بینید." },
  { icon: Layers, title: "ساخت فضای اختصاصی", text: "سازمان شما ساخته و اطلاعات ورود ادمین ارسال می‌شود." },
  { icon: Truck, title: "انبار، ناوگان و رانندگان", text: "کالاها و موجودی را وارد و رانندگان را با لینک دعوت اضافه می‌کنید." },
  { icon: Route, title: "اولین سفارش", text: "از همان روز سفارش ثبت و به راننده مناسب تخصیص می‌دهید." },
];

export default function AboutPage() {
  return (
    <InfoLayout title="درباره ما" testId="about-page" eyebrow={`درباره ${BRAND.nameFa}`}
      heading={<>سفارش، انبار و ناوگان؛<br className="hidden sm:block" /> روی یک مسیر روشن.</>}
      lead={`${BRAND.nameFa} (${BRAND.name}) سامانه‌ای ابری برای کسب‌وکارهای ایرانی است که سفارش، موجودی انبار، رانندگان و ارسال را در یک‌جا و به‌صورت شفاف مدیریت می‌کند — از لحظه ثبت سفارش تا ثبت نظر مشتری.`}
      hero={
        <div className="flex flex-wrap gap-3">
          <Link to="/request" className={buttonClass("primary", "lg")}>درخواست دسترسی</Link>
          <Link to="/faq" className={buttonClass("secondary", "lg")}>سوالات متداول</Link>
        </div>
      }>
      {/* [01] چرا */}
      <section className="mx-auto max-w-7xl px-4 py-24 sm:px-6 sm:py-32" data-testid="about-why">
        <SectionTag label="چرا ساختیمش" />
        <div className="grid gap-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:items-start">
          <div className="lg:sticky lg:top-28">
            <ScrubText className="text-3xl font-black leading-tight tracking-tight sm:text-5xl" text="لجستیک کسب‌وکارها نباید به حافظه آدم‌ها و تماس تلفنی وابسته باشد." />
            <p className="mt-6 leading-8 text-text-2">
              بیشتر کسب‌وکارهایی که سفارش ارسال می‌کنند، با ابزارهای پراکنده کار می‌کنند. نتیجه، اتلاف وقت، موجودی نادرست و مشتری‌ای است که نمی‌داند بسته‌اش کجاست.
              {" "}{BRAND.nameFa} را ساختیم تا همه این حلقه‌ها در یک سامانه به هم وصل شوند.
            </p>
          </div>
          <Reveal className="grid gap-4 sm:grid-cols-2">
            {PAINS.map(p => (
              <div key={p.title} className="card p-6">
                <span className="grid size-11 place-items-center rounded-2xl bg-danger-soft text-danger"><p.icon className="size-5" /></span>
                <h3 className="mt-5 text-lg font-bold">{p.title}</h3>
                <p className="mt-2 text-sm leading-7 text-text-2">{p.text}</p>
              </div>
            ))}
          </Reveal>
        </div>
      </section>

      {/* [02] مأموریت و چشم‌انداز */}
      <section className="bg-bg-2 py-24 sm:py-32">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <SectionTag label="مأموریت و چشم‌انداز" />
          <Reveal className="grid gap-6 lg:grid-cols-2">
            <div className="relative overflow-hidden rounded-[28px] bg-brand p-8 text-brand-ink sm:p-12">
              <div className="text-sm font-semibold opacity-80">مأموریت</div>
              <p className="mt-4 text-2xl font-black leading-[1.6] sm:text-3xl">ساده کردن ارسال برای هر کسب‌وکار؛ تا هر سفارش، سر وقت و با اطلاعات درست به مقصد برسد.</p>
              <Route className="absolute -bottom-6 -left-6 size-40 opacity-10" />
            </div>
            <div className="relative overflow-hidden rounded-[28px] border border-border bg-surface p-8 sm:p-12">
              <div className="text-sm font-semibold text-muted">چشم‌انداز</div>
              <p className="mt-4 text-2xl font-black leading-[1.6] sm:text-3xl">زیرساخت لجستیک قابل‌اعتمادی که سازمان‌ها، رانندگان و مشتریان در سراسر ایران روی آن هماهنگ کار کنند.</p>
              <MapPinned className="absolute -bottom-6 -left-6 size-40 text-brand opacity-10" />
            </div>
          </Reveal>
        </div>
      </section>

      {/* [03] آنچه ساخته‌ایم */}
      <section className="mx-auto max-w-7xl px-4 py-24 sm:px-6 sm:py-32">
        <SectionTag label="آنچه ساخته‌ایم" />
        <div className="mb-12 flex flex-wrap items-end justify-between gap-6">
          <h2 className="max-w-2xl text-3xl font-black leading-tight tracking-tight sm:text-5xl">یک سامانه، به‌جای شش ابزار جدا.</h2>
          <Link to="/#product" className="text-sm font-semibold text-brand hover:underline">دیدن محصول در صفحه اصلی ←</Link>
        </div>
        <Reveal className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {MODULES.map((m, i) => (
            <div key={m.title} className="card group relative overflow-hidden p-6 transition-[translate,box-shadow] duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lg)]">
              <span className="absolute end-5 top-5 font-mono text-xs text-muted">0{i + 1}</span>
              <span className="grid size-12 place-items-center rounded-2xl bg-brand-soft text-brand transition-transform duration-300 group-hover:-rotate-6 group-hover:scale-110"><m.icon className="size-6" /></span>
              <h3 className="mt-5 text-lg font-bold">{m.title}</h3>
              <p className="mt-2 text-sm leading-7 text-text-2">{m.text}</p>
            </div>
          ))}
        </Reveal>
        <div className="mt-14 grid grid-cols-2 gap-8 border-t border-border pt-12 sm:grid-cols-5" data-testid="about-numbers">
          {[[9, "", "وضعیت استاندارد سفارش"], [3, "", "نقش داخل هر سازمان"], [4, "", "سطح عملکرد راننده"], [31, "", "استان پوشش‌داده‌شده"], [15, "ث", "به‌روزرسانی خودکار"]].map(([v, s, l]) => (
            <div key={l as string}>
              <CountUp to={v as number} suffix={s as string} className="text-4xl font-black tracking-tight text-brand" />
              <div className="mt-1 text-sm text-muted">{l as string}</div>
            </div>
          ))}
        </div>
      </section>

      {/* [04] اصول */}
      <section className="bg-bg-2 py-24 sm:py-32">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <SectionTag label="اصول ما" />
          <h2 className="mb-12 max-w-2xl text-3xl font-black leading-tight tracking-tight sm:text-5xl">چیزهایی که روی آن‌ها کوتاه نمی‌آییم.</h2>
          <Reveal className="grid gap-x-10 gap-y-12 sm:grid-cols-2 lg:grid-cols-3">
            {PRINCIPLES.map(p => (
              <div key={p.title} className="border-t-2 border-brand pt-6">
                <p.icon className="size-6 text-brand" />
                <h3 className="mt-4 text-lg font-bold">{p.title}</h3>
                <p className="mt-2 text-sm leading-7 text-text-2">{p.text}</p>
              </div>
            ))}
          </Reveal>
        </div>
      </section>

      {/* [05] روند همکاری */}
      <section className="mx-auto max-w-7xl px-4 py-24 sm:px-6 sm:py-32">
        <SectionTag label="روند همکاری" />
        <h2 className="mb-14 max-w-2xl text-3xl font-black leading-tight tracking-tight sm:text-5xl">از درخواست تا اولین سفارش.</h2>
        <Reveal as="ol" className="relative grid gap-8 lg:grid-cols-5 lg:gap-4" stagger={0.12}>
          {JOURNEY.map((j, i) => (
            <li key={j.title} className="relative flex gap-4 lg:flex-col">
              {i < JOURNEY.length - 1 && (
                <span className="absolute start-6 top-14 h-[calc(100%-1.5rem)] w-px border-s-2 border-dashed border-border-strong lg:start-14 lg:top-6 lg:h-px lg:w-[calc(100%-2rem)] lg:border-s-0 lg:border-t-2" aria-hidden="true" />
              )}
              <span className="relative z-10 grid size-12 shrink-0 place-items-center rounded-2xl bg-brand text-brand-ink shadow-sm"><j.icon className="size-5" /></span>
              <div>
                <div className="font-mono text-xs text-muted">مرحله {i + 1}</div>
                <h3 className="mt-1 font-bold">{j.title}</h3>
                <p className="mt-1.5 text-sm leading-7 text-text-2">{j.text}</p>
              </div>
            </li>
          ))}
        </Reveal>
      </section>

      {/* [06] برای چه کسانی */}
      <section className="mx-auto max-w-7xl px-4 pb-24 sm:px-6 sm:pb-32">
        <div className="grid gap-10 rounded-[28px] border border-border bg-surface p-8 sm:p-12 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:items-center">
          <div>
            <SectionTag label="برای چه کسانی" />
            <h2 className="text-2xl font-black leading-tight tracking-tight sm:text-4xl">هر کسب‌وکاری که سفارش، انبار و ارسال دارد.</h2>
            <p className="mt-4 leading-8 text-text-2">از یک فروشگاه با دو راننده تا مرکز پخشی با چند انبار و ده‌ها خودرو.</p>
          </div>
          <Reveal className="flex flex-wrap gap-2.5" stagger={0.05} y={14}>
            {Object.entries(BUSINESS_TYPES).filter(([k]) => k !== "other").map(([k, label]) => (
              <span key={k} className="inline-flex items-center gap-2 rounded-full border border-border bg-bg px-4 py-2.5 text-sm font-medium">
                <Handshake className="size-4 text-brand" />{label}
              </span>
            ))}
          </Reveal>
        </div>
      </section>
    </InfoLayout>
  );
}
