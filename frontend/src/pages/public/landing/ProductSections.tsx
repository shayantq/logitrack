/** بخش‌های «محصول» (قاب مرورگر ثابت با صفحه‌های جابه‌جاشونده)، «شروع کار»، «اعتماد»، «پرسش‌ها» و دعوت پایانی */
import { useRef, type ReactNode } from "react";
import { Link } from "react-router-dom";
import * as Accordion from "@radix-ui/react-accordion";
import { ArrowLeft, Building2, Check, ChevronDown, ClipboardList, History, KeyRound, Layers, MapPin, Phone, ShieldCheck, Sheet, Truck, UserCog } from "lucide-react";
import { faNumber } from "@/lib/format";
import { buttonClass, cn } from "@/ui/primitives";
import { CountUp, Reveal, ScrubText, SectionTag, useProgressState, useReducedMotion } from "../motion";
import { ALL_FAQ, LANDING_FAQ_IDS } from "../content/faq";

// ------------------------------------------------------------------ [03] محصول
const SCREENS = [
  { key: "orders", path: "/app/orders", title: "صف سفارش‌ها", text: "همه سفارش‌ها با وضعیت، شهر مقصد و راننده؛ جست‌وجو، فیلتر و خروجی اکسل. صفحه هر ۱۵ ثانیه خودش به‌روز می‌شود.", icon: ClipboardList },
  { key: "ledger", path: "/app/ledger", title: "دفتر گردش انبار", text: "هر ورود و خروج کالا با موجودی بعد از تغییر. برای هر کالا می‌توانید تاریخچه کامل را ببینید.", icon: History },
  { key: "driver", path: "/app/driver", title: "پنل راننده", text: "راننده روی موبایل فقط سفارش‌های خودش را می‌بیند و هر مرحله را با یک لمس ثبت می‌کند.", icon: Truck },
] as const;

export function ProductSection() {
  const section = useRef<HTMLElement>(null);
  const reduced = useReducedMotion();
  const p = useProgressState(section, { smooth: 0.5, disabled: reduced }, 0.005);
  const active = reduced ? 0 : Math.min(2, Math.floor(p * 3));
  const local = reduced ? 1 : Math.min(1, p * 3 - active);

  return (
    <section ref={section} id="product" data-section="محصول" className={cn("relative bg-bg-2", reduced ? "py-24" : "h-[330vh]")}>
      <div className={cn("flex items-center", !reduced && "sticky top-0 h-svh pt-16")}>
        <div className="mx-auto grid w-full max-w-7xl items-center gap-8 px-4 sm:px-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-14">
          <div>
            <SectionTag label="محصول" />
            <h2 className="text-3xl font-black leading-tight tracking-tight sm:text-4xl">یک سامانه، سه نگاه.</h2>
            <ol className="mt-6 space-y-2 sm:mt-8">
              {SCREENS.map((s, i) => (
                <li key={s.key} className={cn("rounded-2xl border p-4 transition-all duration-500",
                  i === active ? "border-border bg-surface shadow-[var(--shadow)]" : "border-transparent opacity-50")}>
                  <div className="flex items-center gap-3">
                    <span className={cn("grid size-9 place-items-center rounded-xl transition-colors", i === active ? "bg-brand text-brand-ink" : "bg-surface-2 text-muted")}><s.icon className="size-[18px]" /></span>
                    <span className="font-bold">{s.title}</span>
                    <span className="ms-auto font-mono text-xs text-muted">0{i + 1}</span>
                  </div>
                  <div className={cn("grid transition-all duration-500", i === active ? "mt-3 grid-rows-[1fr]" : "grid-rows-[0fr]")}>
                    <p className="overflow-hidden text-sm leading-7 text-text-2">{s.text}</p>
                  </div>
                  {i === active && (
                    <div className="mt-3 h-0.5 overflow-hidden rounded-full bg-border">
                      <div className="h-full origin-right bg-brand" style={{ transform: `scaleX(${local})` }} />
                    </div>
                  )}
                </li>
              ))}
            </ol>
          </div>

          <BrowserFrame path={SCREENS[active].path}>
            <div className="relative h-full">
              {SCREENS.map((s, i) => (
                <div key={s.key} className={cn("absolute inset-0 transition-all duration-700",
                  i === active ? "translate-x-0 opacity-100" : i < active ? "pointer-events-none translate-x-8 opacity-0" : "pointer-events-none -translate-x-8 opacity-0")}>
                  {s.key === "orders" ? <OrdersMock /> : s.key === "ledger" ? <LedgerMock /> : <DriverMock />}
                </div>
              ))}
            </div>
          </BrowserFrame>
        </div>
      </div>
    </section>
  );
}

function BrowserFrame({ path, children }: { path: string; children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-border-strong bg-surface shadow-[var(--shadow-lg)]" data-testid="browser-mock">
      <div className="flex items-center gap-3 border-b border-border bg-surface-2 px-4 py-2.5">
        <div className="flex gap-1.5 ltr"><span className="size-2.5 rounded-full bg-danger/70" /><span className="size-2.5 rounded-full bg-accent/80" /><span className="size-2.5 rounded-full bg-success/70" /></div>
        <div className="mx-auto flex h-7 w-full max-w-xs items-center justify-center rounded-lg bg-surface px-3 font-mono text-[11px] text-muted ltr">
          passineh.ir<span className="text-brand">/app</span><span key={path} className="animate-rise text-text">{path.replace("/app", "")}</span>
        </div>
      </div>
      <div className="h-[340px] bg-bg sm:h-[420px]">{children}</div>
    </div>
  );
}

const MOCK_ORDERS = [
  ["LT-2481", "تهران", "در مسیر", "info", "D-07"],
  ["LT-2482", "کرج", "تحویل داده شد", "success", "D-03"],
  ["LT-2483", "قزوین", "در حال بارگیری", "violet", "D-11"],
  ["LT-2484", "تهران", "در انتظار تخصیص", "warning", "—"],
  ["LT-2485", "رشت", "تحویل داده شد", "success", "D-05"],
  ["LT-2486", "کرج", "لغو شد", "muted", "—"],
] as const;
const TONE_CLS: Record<string, string> = {
  info: "bg-info-soft text-info", success: "bg-success-soft text-success", violet: "bg-violet-soft text-violet",
  warning: "bg-warning-soft text-warning", muted: "bg-surface-2 text-muted",
};

function OrdersMock() {
  return (
    <div className="flex h-full flex-col gap-3 p-4 text-xs sm:p-5">
      <div className="grid grid-cols-3 gap-2 sm:gap-3">
        {[["فعال", 18, "text-brand"], ["تحویل امروز", 42, "text-success"], ["در انتظار", 5, "text-warning"]].map(([l, v, c]) => (
          <div key={l as string} className="rounded-xl border border-border bg-surface p-3">
            <div className="text-muted">{l}</div><div className={cn("mt-1 text-xl font-black tnum", c as string)}>{faNumber(v as number)}</div>
          </div>
        ))}
      </div>
      <div className="flex-1 overflow-hidden rounded-xl border border-border bg-surface">
        <div className="grid grid-cols-[1.1fr_0.8fr_1.3fr_0.6fr] gap-2 border-b border-border bg-surface-2 px-3 py-2 text-muted">
          <span>کد</span><span>مقصد</span><span>وضعیت</span><span>راننده</span>
        </div>
        {MOCK_ORDERS.map(([code, city, status, tone, driver]) => (
          <div key={code} className="grid grid-cols-[1.1fr_0.8fr_1.3fr_0.6fr] items-center gap-2 border-b border-border px-3 py-2.5 last:border-0">
            <span className="font-mono font-semibold ltr text-right">{code}</span><span className="text-text-2">{city}</span>
            <span><span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", TONE_CLS[tone])}>{status}</span></span>
            <span className="font-mono text-muted">{driver}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function LedgerMock() {
  const rows = [
    ["ورود کالا", "+۶۰", "۱٬۲۸۸", "text-success"], ["خروج بابت سفارش LT-2481", "−۱۲", "۱٬۲۲۸", "text-info"],
    ["برگشت از سفارش LT-2486", "+۸", "۱٬۲۳۶", "text-brand"], ["ضایعات / کسری", "−۲", "۱٬۲۳۴", "text-danger"],
    ["انتقال به انبار کرج", "−۴۰", "۱٬۱۹۴", "text-violet"], ["خروج بابت سفارش LT-2490", "−۲۰", "۱٬۱۷۴", "text-info"],
  ];
  return (
    <div className="flex h-full flex-col gap-3 p-4 text-xs sm:p-5">
      <div className="flex items-center justify-between rounded-xl border border-border bg-surface p-3">
        <div><div className="text-muted">کارتن دستمال کاغذی</div><div className="mt-1 font-bold">انبار مرکزی</div></div>
        <div className="text-left"><div className="text-muted">موجودی فعلی</div><div className="mt-1 text-xl font-black tnum">۱٬۱۷۴</div></div>
      </div>
      <div className="flex-1 overflow-hidden rounded-xl border border-border bg-surface">
        <div className="grid grid-cols-[2fr_0.7fr_0.8fr] gap-2 border-b border-border bg-surface-2 px-3 py-2 text-muted"><span>نوع گردش</span><span>تغییر</span><span>موجودی بعد</span></div>
        {rows.map(([label, delta, after, cls]) => (
          <div key={label} className="grid grid-cols-[2fr_0.7fr_0.8fr] items-center gap-2 border-b border-border px-3 py-2.5 last:border-0">
            <span className="truncate">{label}</span><span className={cn("font-mono font-bold", cls)}>{delta}</span><span className="tnum text-text-2">{after}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function DriverMock() {
  return (
    <div className="grid h-full place-items-center p-4">
      <div className="w-56 rounded-[32px] border-4 border-text/80 bg-surface p-3 shadow-[var(--shadow-lg)] sm:w-60">
        <div className="mx-auto mb-3 h-1.5 w-14 rounded-full bg-border-strong" />
        <div className="rounded-2xl border border-border p-3 text-xs">
          <div className="flex items-center justify-between"><span className="font-mono font-bold ltr">LT-2481</span><span className="rounded-full bg-info-soft px-2 py-0.5 text-[10px] font-semibold text-info">در مسیر</span></div>
          <div className="mt-3 flex gap-1">{[1, 1, 1, 1, 0].map((on, i) => <span key={i} className={cn("h-1 flex-1 rounded-full", on ? "bg-brand" : "bg-surface-2")} />)}</div>
          <div className="mt-3 space-y-1.5 text-text-2">
            <div className="flex gap-1.5"><MapPin className="size-3.5 shrink-0 text-danger" />تهران، سعادت‌آباد، خیابان سرو</div>
            <div className="flex gap-1.5"><Phone className="size-3.5 shrink-0 text-muted" /><span className="font-mono ltr">0912 ••• 4567</span></div>
          </div>
        </div>
        <div className="mt-3 rounded-xl bg-brand py-2.5 text-center text-xs font-bold text-brand-ink">تحویل داده شد</div>
        <div className="mt-2 rounded-xl border border-danger/40 py-2 text-center text-xs text-danger">ناموفق</div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ [04] شروع کار
const HOW = [
  { title: "فرم درخواست را پر کنید", text: "مشخصات کسب‌وکار، حجم سفارش ماهانه و بخش‌هایی که لازم دارید. یک کد پیگیری می‌گیرید." },
  { title: "بررسی و ساخت سازمان", text: "پس از تأیید، فضای اختصاصی سازمان شما ساخته و نام کاربری ادمین برایتان فرستاده می‌شود." },
  { title: "تعریف انبار، کالا و ناوگان", text: "انبارها، کالاها با موجودی اولیه، خودروها و کاربران (مدیر انبار و راننده) را اضافه کنید." },
  { title: "اولین سفارش را ثبت کنید", text: "از همین لحظه موجودی، تخصیص خودرو و وضعیت هر سفارش خودکار دنبال می‌شود." },
];

export function HowSection() {
  const list = useRef<HTMLOListElement>(null);
  const reduced = useReducedMotion();
  const p = useProgressState(list, { smooth: 0.4, start: "top 70%", end: "bottom 55%", disabled: reduced });
  return (
    <section id="how" data-section="شروع کار" className="py-28 sm:py-36">
      <div className="mx-auto grid max-w-7xl gap-14 px-4 sm:px-6 lg:grid-cols-2">
        <div className="lg:sticky lg:top-32 lg:h-fit">
          <SectionTag label="شروع کار" />
          <ScrubText className="text-3xl font-black leading-tight tracking-tight sm:text-5xl" text="از فرم درخواست تا اولین تحویل، در چهار قدم." />
          <Link to="/request" className={buttonClass("primary", "lg", "mt-8")}>شروع با فرم درخواست<ArrowLeft className="size-4" /></Link>
        </div>
        <ol ref={list} className="relative space-y-6">
          <span className="absolute right-[23px] top-6 bottom-6 w-0.5 bg-border" />
          <span className="absolute right-[23px] top-6 bottom-6 w-0.5 origin-top bg-linear-to-b from-brand to-accent" style={{ transform: `scaleY(${p})` }} />
          {HOW.map((step, i) => {
            const reached = p >= (i + 0.2) / HOW.length || (i === 0 && p > 0.02);
            return (
              <li key={step.title} className="relative flex gap-5">
                <span className={cn("relative z-10 grid size-12 shrink-0 place-items-center rounded-2xl border-2 font-mono text-sm font-bold transition-all duration-500",
                  reached ? "border-brand bg-brand text-brand-ink" : "border-border-strong bg-bg text-muted")}>
                  {reached ? <Check className="size-5" /> : `0${i + 1}`}
                </span>
                <div className={cn("card flex-1 p-6 transition-all duration-500", reached ? "opacity-100" : "opacity-50")}>
                  <h3 className="text-lg font-bold">{step.title}</h3>
                  <p className="mt-2 leading-7 text-text-2">{step.text}</p>
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ [05] اعتماد
const TRUST = [
  { icon: Layers, title: "جداسازی کامل سازمان‌ها", text: "هر پرس‌وجو در لایه پایگاه داده به سازمان کاربر محدود می‌شود؛ داده یک سازمان هیچ‌وقت در پنل سازمان دیگر دیده نمی‌شود." },
  { icon: UserCog, title: "نقش‌ها و دسترسی‌ها", text: "ادمین سازمان، مدیر انبار و راننده هر کدام فقط همان بخشی را می‌بینند و تغییر می‌دهند که لازم دارند." },
  { icon: History, title: "ردپای هر تغییر", text: "تاریخچه وضعیت سفارش و دفتر گردش انبار، با زمان و نام ثبت‌کننده. چیزی بی‌صدا عوض نمی‌شود." },
  { icon: Sheet, title: "گزارش و خروجی", text: "داشبورد آماری سفارش‌ها و موجودی، با خروجی اکسل برای حسابداری و گزارش‌های مدیریتی." },
];

export function TrustSection() {
  return (
    <section id="trust" data-section="اعتماد" className="bg-bg-2 py-28 sm:py-36">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <SectionTag label="اعتماد" />
        <div className="grid gap-10 lg:grid-cols-2 lg:items-end">
          <ScrubText className="text-3xl font-black leading-tight tracking-tight sm:text-5xl" text="داده‌های شما، فقط برای سازمان شما." />
          <div className="grid grid-cols-2 gap-6 sm:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4">
            {[[100, "٪", "جداسازی داده"], [9, "", "وضعیت استاندارد سفارش"], [5, "", "نقش دسترسی"], [15, "ث", "به‌روزرسانی خودکار"]].map(([v, s, l]) => (
              <div key={l as string}>
                <CountUp to={v as number} suffix={s as string} className="text-4xl font-black tracking-tight text-brand" />
                <div className="mt-1 text-sm text-muted">{l as string}</div>
              </div>
            ))}
          </div>
        </div>
        <Reveal className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {TRUST.map(t => (
            <div key={t.title} className="card group p-6 transition-[translate,box-shadow] duration-300 hover:-translate-y-1 hover:shadow-[var(--shadow-lg)]">
              <div className="grid size-12 place-items-center rounded-2xl bg-brand-soft text-brand transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-6"><t.icon className="size-6" /></div>
              <h3 className="mt-5 text-lg font-bold">{t.title}</h3>
              <p className="mt-2 text-sm leading-7 text-text-2">{t.text}</p>
            </div>
          ))}
        </Reveal>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ [06] پرسش‌ها
const FAQ = LANDING_FAQ_IDS.map(id => ALL_FAQ.find(f => f.id === id)!).map(f => [f.q, f.a] as const);

export function FaqSection() {
  return (
    <section id="faq" data-section="پرسش‌ها" className="py-28 sm:py-36">
      <div className="mx-auto grid max-w-7xl gap-12 px-4 sm:px-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div>
          <SectionTag label="پرسش‌ها" />
          <h2 className="text-3xl font-black leading-tight tracking-tight sm:text-5xl">پرسش‌های پرتکرار</h2>
          <p className="mt-5 leading-8 text-text-2">پرتکرارترین پرسش‌ها این‌جاست؛ ده‌ها پرسش دیگر درباره سفارش، انبار، رانندگان و امنیت را در صفحه «سوالات متداول» ببینید.</p>
          <Link to="/faq" className={buttonClass("secondary", "lg", "mt-8")} data-testid="landing-faq-all">همه پرسش‌ها<ArrowLeft className="size-4" /></Link>
        </div>
        <Accordion.Root type="single" collapsible className="divide-y divide-border border-y border-border" dir="rtl">
          {FAQ.map(([q, a], i) => (
            <Accordion.Item key={q} value={`q${i}`}>
              <Accordion.Header>
                <Accordion.Trigger className="group flex w-full items-center gap-4 py-5 text-right text-lg font-bold transition hover:text-brand">
                  <span className="font-mono text-xs text-muted">0{i + 1}</span>
                  <span className="flex-1">{q}</span>
                  <ChevronDown className="size-5 shrink-0 text-muted transition-transform duration-300 group-data-[state=open]:rotate-180" />
                </Accordion.Trigger>
              </Accordion.Header>
              <Accordion.Content className="accordion-content overflow-hidden">
                <p className="pb-6 pe-8 ps-9 leading-8 text-text-2">{a}</p>
              </Accordion.Content>
            </Accordion.Item>
          ))}
        </Accordion.Root>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ دعوت پایانی
export function CtaSection() {
  return (
    <section className="px-4 pb-28 sm:px-6">
      <Reveal className="mx-auto max-w-7xl">
        <div className="relative overflow-hidden rounded-[32px] bg-brand px-6 py-16 text-brand-ink sm:px-14 sm:py-20">
          <svg className="absolute inset-0 size-full opacity-25" aria-hidden="true">
            <defs>
              <pattern id="cta-grid" width="56" height="56" patternUnits="userSpaceOnUse">
                <path d="M56 0H0v56" fill="none" stroke="currentColor" strokeWidth="1" opacity=".35" />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#cta-grid)" />
            <path d="M-20 260 C 200 260, 260 120, 480 140 S 760 300, 1400 90" fill="none" stroke="currentColor" strokeWidth="2.5" strokeDasharray="10 12" className="cta-route" />
          </svg>
          <div className="relative grid gap-10 lg:grid-cols-[1fr_auto] lg:items-center">
            <div>
              <div className="mb-4 flex items-center gap-2 text-sm font-semibold opacity-85"><ShieldCheck className="size-4" />فضای اختصاصی هر سازمان</div>
              <h2 className="max-w-2xl text-3xl font-black leading-tight tracking-tight sm:text-5xl">سفارش بعدی را روی مسیر درست ثبت کنید.</h2>
              <p className="mt-5 max-w-xl text-lg leading-8 opacity-85">درخواست دسترسی را ثبت کنید؛ پس از بررسی، سازمان شما ساخته می‌شود و می‌توانید همان روز اولین سفارش را ثبت کنید.</p>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row lg:flex-col">
              <Link to="/request" className="inline-flex h-14 items-center justify-center gap-2 rounded-2xl bg-bg px-8 font-bold text-text shadow-lg transition hover:scale-[1.02]">
                <Building2 className="size-5" />درخواست دسترسی
              </Link>
              <Link to="/app/login" className="inline-flex h-14 items-center justify-center gap-2 rounded-2xl border border-current/30 px-8 font-bold transition hover:bg-white/10">
                <KeyRound className="size-5" />ورود به پنل
              </Link>
            </div>
          </div>
        </div>
      </Reveal>
    </section>
  );
}
