/** صفحه «تعرفه‌ها»: پلن‌ها با پرداخت ماهانه/سالانه، مزیت‌های مشترک، جدول مقایسه، پرسش‌های خرید و مشاوره */
import { useState } from "react";
import { Link } from "react-router-dom";
import * as Accordion from "@radix-ui/react-accordion";
import { ArrowLeft, CalendarCheck, Check, ChevronDown, ClipboardList, Gift, Minus, Phone, Receipt, SlidersHorizontal, Truck, UserRound, Users, Warehouse, type LucideIcon } from "lucide-react";
import { BRAND } from "@/brand";
import { buttonClass, cn } from "@/ui/primitives";
import { InfoLayout } from "./InfoLayout";
import { PricingCalculator } from "./PricingCalculator";
import { ANNUAL_MONTHS, EARLY_OFFER, FEATURE_GROUPS, PLANS, PRICING_FAQ, TRIAL_DAYS, type Plan } from "./content/pricing";

type Billing = "monthly" | "annual";
const fa = (n: number) => n.toLocaleString("fa-IR");
const roundK = (n: number) => Math.round(n / 1000) * 1000;

function BillingToggle({ value, onChange }: { value: Billing; onChange: (b: Billing) => void }) {
  const option = (b: Billing, label: string, badge?: string) => (
    <button type="button" role="radio" aria-checked={value === b} onClick={() => onChange(b)} data-testid={`billing-${b}`}
      className={cn("flex h-11 items-center gap-2 rounded-xl px-5 text-sm font-semibold transition",
        value === b ? "bg-surface text-text shadow-[var(--shadow)]" : "text-muted hover:text-text")}>
      {label}
      {badge && <span className="rounded-full bg-success-soft px-2 py-0.5 text-xs font-bold text-success">{badge}</span>}
    </button>
  );
  return (
    <div role="radiogroup" aria-label="دوره پرداخت" className="inline-flex rounded-2xl border border-border bg-surface-2 p-1">
      {option("monthly", "ماهانه")}
      {option("annual", "سالانه", `${fa(12 - ANNUAL_MONTHS)} ماه رایگان`)}
    </div>
  );
}

/**
 * مبلغ کامل با جداکننده هزارگان (اعشار فارسی «٫» شبیه «/» خوانده می‌شد).
 * سالانه: معادل ماهانه درشت، قیمت ماهانه خط‌خورده و مبلغ کل سال زیرش.
 */
function Price({ plan, billing }: { plan: Plan; billing: Billing }) {
  let main: string, unit: string, prefix: string | undefined, was: string | undefined, note: string | undefined;
  if (plan.monthly === 0) { main = "رایگان"; unit = `به مدت ${fa(TRIAL_DAYS)} روز`; }
  else if (plan.monthly === null) { prefix = "از"; main = fa(plan.fromMonthly ?? 0); unit = "تومان در ماه"; note = "قیمت نهایی متناسب با نیاز شما"; }
  else if (billing === "monthly") { main = fa(plan.monthly); unit = "تومان در ماه"; }
  else {
    const yearly = plan.monthly * ANNUAL_MONTHS;
    main = fa(roundK(yearly / 12)); unit = "تومان در ماه"; was = fa(plan.monthly);
    note = `پرداخت یک‌جا: ${fa(yearly)} تومان در سال`;
  }
  return (
    <div data-testid="plan-price" className="sm:min-h-[104px]">
      <div className={cn("h-5 items-center text-sm text-muted", was ? "flex" : "hidden sm:flex")}>{was && <span className="line-through decoration-danger/60">{was}</span>}</div>
      <div className="flex items-baseline gap-1.5">
        {prefix && <span className="text-base font-semibold text-muted">{prefix}</span>}
        <span className="text-[2rem] font-black leading-tight">{main}</span>
      </div>
      <div className="text-sm text-text-2">{unit}</div>
      {note && <div className={cn("mt-1.5 text-sm", was ? "font-medium text-success" : "text-muted")}>{note}</div>}
    </div>
  );
}

const LIMIT_ITEMS: [keyof Plan["limits"], string, LucideIcon][] = [
  ["warehouses", "انبار", Warehouse], ["drivers", "راننده", Truck], ["orders", "سفارش در ماه", ClipboardList], ["users", "کاربر پنل", UserRound],
];

function PlanCard({ plan, billing }: { plan: Plan; billing: Billing }) {
  const to = `/request?plan=${plan.id}`;
  return (
    <div data-testid="plan-card" data-plan={plan.id}
      className={cn("relative flex flex-col rounded-3xl border bg-surface p-6 transition-shadow",
        plan.highlight ? "border-brand shadow-[var(--shadow-lg)] ring-1 ring-brand/40" : "border-border shadow-[var(--shadow)]")}>
      {plan.highlight && <span className="absolute -top-3.5 right-6 rounded-full bg-brand px-3.5 py-1 text-sm font-bold text-brand-ink shadow">پیشنهاد ما</span>}
      <h2 className={cn("text-2xl font-black", plan.highlight && "text-brand")}>{plan.name}</h2>
      <p className="mt-1 text-sm leading-6 text-text-2">{plan.audience}</p>

      <div className="mt-5"><Price plan={plan} billing={billing} /></div>

      <div className="mt-5">
        {plan.id === "enterprise" ? (
          <div className="grid gap-2">
            <a href={`tel:${BRAND.phone}`} className={buttonClass("primary", "lg", "w-full")} data-testid="plan-cta"><Phone className="size-4" />{plan.cta}</a>
            <Link to={to} className={buttonClass("ghost", "md", "w-full")}>یا ثبت درخواست</Link>
          </div>
        ) : (
          <Link to={to} className={buttonClass(plan.highlight ? "primary" : "secondary", "lg", "w-full")} data-testid="plan-cta">{plan.cta}<ArrowLeft className="size-4" /></Link>
        )}
      </div>

      <dl className="mt-6 grid grid-cols-2 gap-2">
        {LIMIT_ITEMS.map(([key, label, Icon]) => (
          <div key={key} className="rounded-xl bg-surface-2 px-3 py-2.5">
            <dt className="flex items-center gap-1.5 text-xs text-muted"><Icon className="size-3.5" />{label}</dt>
            <dd className="mt-0.5 font-bold">{plan.limits[key]}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-6 border-t border-border pt-5">
        <div className="text-sm font-semibold">{plan.includesTitle}</div>
        <ul className="mt-3 space-y-2.5">
          {plan.includes.map(item => (
            <li key={item} className="flex items-start gap-2.5 text-sm leading-6 text-text-2">
              <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-success-soft text-success"><Check className="size-3" strokeWidth={3} /></span>
              {item}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

const PROMISES: [LucideIcon, string, string][] = [
  [Users, "بدون هزینه به ازای هر کاربر", "قیمت برای کل سازمان است"],
  [CalendarCheck, `${fa(TRIAL_DAYS)} روز رایگان`, "همه امکانات، بدون پرداخت"],
  [Receipt, "فاکتور رسمی", "برای هر پرداخت"],
  [Phone, "مشاوره رایگان", "پیش از خرید، با ما صحبت کنید"],
];

function CompareTable() {
  return (
    <div className="overflow-x-auto rounded-3xl border border-border bg-surface" data-testid="pricing-compare">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="border-b border-border bg-surface-2">
            <th className="sticky right-0 z-10 bg-surface-2 px-5 py-4 text-start font-semibold text-text-2">امکانات</th>
            {PLANS.map(p => (
              <th key={p.id} className={cn("px-4 py-4 text-center", p.highlight && "bg-brand-soft/60")}>
                <div className={cn("text-base font-black", p.highlight ? "text-brand" : "text-text")}>{p.name}</div>
              </th>
            ))}
          </tr>
        </thead>
        {FEATURE_GROUPS.map(group => (
          <tbody key={group.title}>
            <tr className="border-b border-border">
              <th colSpan={PLANS.length + 1} className="bg-bg-2 px-5 py-2.5 text-start text-sm font-bold">{group.title}</th>
            </tr>
            {group.rows.map(f => (
              <tr key={f.label} className="border-b border-border">
                <td className="sticky right-0 z-10 bg-surface px-5 py-3.5 text-text-2">{f.label}</td>
                {PLANS.map(p => {
                  const v = f.values[p.id];
                  return (
                    <td key={p.id} className={cn("px-4 py-3.5 text-center", p.highlight && "bg-brand-soft/30")}>
                      {v === true ? <Check className="mx-auto size-5 text-success" aria-label="دارد" />
                        : v === false ? <Minus className="mx-auto size-4 text-border-strong" aria-label="ندارد" />
                        : <span className="font-medium">{v}</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}

export default function PricingPage() {
  const [billing, setBilling] = useState<Billing>("monthly");
  return (
    <InfoLayout title="تعرفه‌ها" testId="pricing-page" eyebrow="تعرفه‌ها" cta={false}
      heading="یک قیمت ثابت برای کل سازمان"
      lead={`بدون هزینه به ازای هر کاربر. ${fa(TRIAL_DAYS)} روز رایگان امتحان کنید و هر زمان خواستید، پلن را تغییر دهید.`}
      hero={
        <div className="flex flex-col items-start gap-4">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
            <BillingToggle value={billing} onChange={setBilling} />
            <a href="#custom-plan" className="inline-flex items-center gap-1.5 text-sm font-semibold text-brand hover:underline" data-testid="custom-plan-link">
              <SlidersHorizontal className="size-4" />یا پلن خودتان را بسازید
            </a>
          </div>
          {EARLY_OFFER && (
            <div className="flex items-center gap-3 rounded-2xl border border-success/30 bg-success-soft px-4 py-3 text-success" data-testid="early-offer">
              <Gift className="size-5 shrink-0" /><span className="text-sm font-semibold leading-6 sm:text-base">{EARLY_OFFER}</span>
            </div>
          )}
        </div>
      }>
      <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6 sm:py-20">
        <div className="grid gap-6 pt-2 sm:grid-cols-2 xl:grid-cols-4">
          {PLANS.map(p => <PlanCard key={p.id} plan={p} billing={billing} />)}
        </div>
        <p className="mt-6 text-center text-sm text-muted">همه مبالغ به تومان و بدون احتساب مالیات بر ارزش افزوده است.</p>

        <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="pricing-promises">
          {PROMISES.map(([Icon, title, text]) => (
            <div key={title} className="flex items-center gap-3.5 rounded-2xl border border-border bg-surface p-4">
              <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand"><Icon className="size-5" /></span>
              <div><div className="font-bold">{title}</div><div className="text-sm text-muted">{text}</div></div>
            </div>
          ))}
        </div>

        <section id="custom-plan" className="mt-20 scroll-mt-24">
          <h2 className="text-2xl font-black tracking-tight sm:text-3xl">پلن خودتان را بسازید</h2>
          <p className="mt-2 text-text-2">فقط برای همان چیزی که لازم دارید هزینه کنید؛ قیمت همزمان با تغییرات محاسبه می‌شود.</p>
          <div className="mt-6"><PricingCalculator billing={billing} /></div>
        </section>

        <div className="mt-20">
          <h2 className="text-2xl font-black tracking-tight sm:text-3xl">مقایسه کامل پلن‌ها</h2>
          <p className="mt-2 text-text-2">همه امکانات، کنار هم.</p>
          <div className="mt-6"><CompareTable /></div>
        </div>

        <div className="mt-20 grid gap-10 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <div>
            <h2 className="text-2xl font-black tracking-tight sm:text-3xl">پرسش‌های خرید</h2>
            <p className="mt-3 leading-8 text-text-2">پاسخ پرسش شما این‌جا نیست؟ با ما تماس بگیرید.</p>
            <div className="mt-6 flex flex-wrap gap-3">
              <a href={`tel:${BRAND.phone}`} className={buttonClass("primary", "lg")}><Phone className="size-4" />{BRAND.phoneDisplay}</a>
              <Link to="/faq" className={buttonClass("secondary", "lg")}>همه پرسش‌ها</Link>
            </div>
          </div>
          <Accordion.Root type="single" collapsible className="divide-y divide-border border-y border-border" dir="rtl" data-testid="pricing-faq">
            {PRICING_FAQ.map(({ q, a }, i) => (
                <Accordion.Item key={q} value={`p${i}`}>
                  <Accordion.Header>
                    <Accordion.Trigger className="group flex w-full items-center gap-4 py-5 text-right text-base font-bold transition hover:text-brand sm:text-lg">
                      <span className="flex-1">{q}</span>
                      <ChevronDown className="size-5 shrink-0 text-muted transition-transform duration-300 group-data-[state=open]:rotate-180" />
                    </Accordion.Trigger>
                  </Accordion.Header>
                  <Accordion.Content className="accordion-content overflow-hidden">
                    <p className="pb-5 leading-8 text-text-2">{a}</p>
                  </Accordion.Content>
                </Accordion.Item>
            ))}
          </Accordion.Root>
        </div>
      </section>
    </InfoLayout>
  );
}
