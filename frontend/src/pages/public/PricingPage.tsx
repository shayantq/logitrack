/** صفحه «تعرفه‌ها»: پلن‌ها با پرداخت ماهانه/سالانه، مزیت‌های مشترک، جدول مقایسه، پرسش‌های خرید و مشاوره */
import { useState } from "react";
import { Link } from "react-router-dom";
import * as Accordion from "@radix-ui/react-accordion";
import { ArrowLeft, CalendarCheck, Check, ChevronDown, ClipboardList, Gift, Minus, Phone, Receipt, SlidersHorizontal, Truck, UserRound, Users, Warehouse, type LucideIcon } from "lucide-react";
import { BRAND } from "@/brand";
import { RequestAccessLink } from "@/components/RequestAccessLink";
import { buttonClass, cn } from "@/ui/primitives";
import { InfoLayout } from "./InfoLayout";
import { PricingCalculator } from "./PricingCalculator";
import { ANNUAL_MONTHS, EARLY_OFFER, FEATURE_GROUPS, PLANS, PRICING_COMING_SOON, PRICING_FAQ, PRICING_PUBLISHED, TRIAL_DAYS, type CustomConfig, type Plan } from "./content/pricing";

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
  if (!PRICING_PUBLISHED) {
    return <div data-testid="plan-price" className="text-2xl font-black text-brand">{PRICING_COMING_SOON}</div>;
  }
  let main: string, unit: string, was: string | undefined, note: string | undefined;
  if (plan.monthly === 0) { main = "رایگان"; unit = `به مدت ${fa(TRIAL_DAYS)} روز`; }
  else if (billing === "monthly") { main = fa(plan.monthly); unit = "تومان در ماه"; }
  else {
    const yearly = plan.monthly * ANNUAL_MONTHS;
    main = fa(roundK(yearly / 12)); unit = "تومان در ماه"; was = fa(plan.monthly);
    note = `پرداخت یک‌جا: ${fa(yearly)} تومان در سال`;
  }
  return (
    <div data-testid="plan-price" data-monthly={plan.monthly} className="sm:min-h-[104px]">
      <div className={cn("h-5 items-center text-sm text-muted", was ? "flex" : "hidden sm:flex")}>{was && <span className="line-through decoration-danger/60">{was}</span>}</div>
      <div className="text-[2rem] font-black leading-tight">{main}</div>
      <div className="text-sm text-text-2">{unit}</div>
      {note && <div className={cn("mt-1.5 text-sm", was ? "font-medium text-success" : "text-muted")}>{note}</div>}
    </div>
  );
}

const LIMIT_ITEMS: [keyof Plan["limits"], string, LucideIcon][] = [
  ["warehouses", "انبار", Warehouse], ["drivers", "راننده", Truck], ["orders", "سفارش در ماه", ClipboardList], ["users", "کاربر پنل", UserRound],
];

function PlanCard({ plan, billing, onCustomize }: { plan: Plan; billing: Billing; onCustomize: () => void }) {
  const to = `/request?plan=${plan.id}`;
  const trialBeforePricing = !PRICING_PUBLISHED && plan.id === "trial";
  return (
    <div data-testid="plan-card" data-plan={plan.id}
      className={cn("relative flex flex-col rounded-3xl border bg-surface p-6 transition-shadow",
        plan.highlight ? "border-brand shadow-[var(--shadow-lg)] ring-1 ring-brand/40" : "border-border shadow-[var(--shadow)]")}>
      {plan.highlight && <span className="absolute -top-3.5 right-6 rounded-full bg-brand px-3.5 py-1 text-sm font-bold text-brand-ink shadow">پیشنهاد ما</span>}
      <h2 className={cn("text-2xl font-black", plan.highlight && "text-brand")}>{plan.name}</h2>
      <p className="mt-1 text-sm leading-6 text-text-2">{trialBeforePricing ? "برای آشنایی با سامانه" : plan.audience}</p>

      <div className="mt-5"><Price plan={plan} billing={billing} /></div>

      <div className="mt-5">
        {plan.id === "enterprise" ? (
          <div className="grid gap-2">
            <a href={`tel:${BRAND.phone}`} className={buttonClass("primary", "lg", "w-full")} data-testid="plan-cta"><Phone className="size-4" />{PRICING_PUBLISHED ? plan.cta : "تماس برای مشاوره"}</a>
            <RequestAccessLink to={to} className={buttonClass("ghost", "md", "w-full")}>یا ثبت درخواست</RequestAccessLink>
          </div>
        ) : (
          <RequestAccessLink to={to} className={buttonClass(plan.highlight ? "primary" : "secondary", "lg", "w-full")} data-testid="plan-cta">{trialBeforePricing ? "شروع دورهٔ آزمایشی" : plan.cta}<ArrowLeft className="size-4" /></RequestAccessLink>
        )}
        {PRICING_PUBLISHED && plan.monthly > 0 && (
          <button type="button" onClick={onCustomize} data-testid="plan-customize"
            className="mx-auto mt-2 flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-medium text-brand transition hover:bg-brand-soft">
            <SlidersHorizontal className="size-4" />شخصی‌سازی این پلن
          </button>
        )}
      </div>

      <dl className="mt-6 grid grid-cols-2 gap-2">
        {LIMIT_ITEMS.map(([key, label, Icon]) => (
          <div key={key} className="rounded-xl bg-surface-2 px-3 py-2.5">
            <dt className="flex items-center gap-1.5 text-xs text-muted"><Icon className="size-3.5" />{label}</dt>
            <dd className="mt-0.5 font-bold">{fa(plan.limits[key])}</dd>
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
    <div role="region" aria-labelledby="pricing-compare-heading" tabIndex={0}
      className="snap-x snap-mandatory overflow-x-auto scroll-ps-[40%] rounded-3xl border border-border bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand sm:snap-none sm:scroll-ps-0" data-testid="pricing-compare">
      <table className="w-[160%] table-fixed text-sm sm:w-full">
        <colgroup>
          <col className="w-1/4 sm:w-48 lg:w-80" />
          <col span={PLANS.length} />
        </colgroup>
        <thead>
          <tr className="border-b border-border bg-surface-2">
            <th scope="col" className="sticky start-0 z-10 bg-surface-2 px-3 py-4 text-start font-semibold text-text-2 sm:px-5">امکانات</th>
            {PLANS.map(p => (
              <th key={p.id} scope="col" className={cn("snap-start px-2 py-4 text-center sm:px-4", p.highlight && "bg-brand-soft/60")}>
                <div className={cn("font-black sm:text-base", p.highlight ? "text-brand" : "text-text")}>{p.name}</div>
              </th>
            ))}
          </tr>
        </thead>
        {FEATURE_GROUPS.map(group => (
          <tbody key={group.title}>
            <tr className="border-b border-border">
              <th scope="rowgroup" colSpan={PLANS.length + 1} className="bg-bg-2 text-start font-bold">
                <span className="sticky start-0 inline-block px-3 py-2.5 sm:px-5">{group.title}</span>
              </th>
            </tr>
            {group.rows.map(f => (
              <tr key={f.label} className="border-b border-border">
                <th scope="row" className="sticky start-0 z-10 bg-surface px-3 py-2.5 text-start font-normal text-text-2 sm:px-5 sm:py-3.5">{f.label}</th>
                {PLANS.map(p => {
                  const v = f.values[p.id];
                  return (
                    <td key={p.id} className={cn("px-2 py-2.5 text-center sm:px-4 sm:py-3.5", p.highlight && "bg-brand-soft/30")}>
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
  // «شخصی‌سازی این پلن»: مشخصات همان پلن در ماشین‌حساب بارگذاری می‌شود (n = کلید بازسازی)
  const [preset, setPreset] = useState<{ config: CustomConfig; n: number } | null>(null);
  const customize = (p: Plan) => {
    setPreset(prev => ({ config: { ...p.limits, modules: [...p.modules] }, n: (prev?.n ?? 0) + 1 }));
    requestAnimationFrame(() => document.getElementById("custom-plan")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };
  return (
    <InfoLayout title="تعرفه‌ها" testId="pricing-page" eyebrow="تعرفه‌ها" cta={false}
      heading={PRICING_PUBLISHED ? "یک قیمت ثابت برای کل سازمان" : "پلن‌های پسینه"}
      lead={PRICING_PUBLISHED
        ? `بدون هزینه به ازای هر کاربر. ${fa(TRIAL_DAYS)} روز رایگان امتحان کنید و هر زمان خواستید، پلن را تغییر دهید.`
        : `امکانات پلن‌ها را مقایسه کنید یا با دورهٔ آزمایشی ${fa(TRIAL_DAYS)}روزه شروع کنید.`}
      hero={PRICING_PUBLISHED && (
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
      )}>
      <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6 sm:py-20">
        <div className="grid gap-6 pt-2 sm:grid-cols-2 xl:grid-cols-4">
          {PLANS.map(p => <PlanCard key={p.id} plan={p} billing={billing} onCustomize={() => customize(p)} />)}
        </div>
        {PRICING_PUBLISHED && (
          <>
            <p className="mt-6 text-center text-sm text-muted">همه مبالغ به تومان و بدون احتساب مالیات بر ارزش افزوده است.</p>

            <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="pricing-promises">
              {PROMISES.map(([Icon, title, text]) => (
                <div key={title} className="flex items-center gap-3.5 rounded-2xl border border-border bg-surface p-4">
                  <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand"><Icon className="size-5" /></span>
                  <div><div className="font-bold">{title}</div><div className="text-sm text-muted">{text}</div></div>
                </div>
              ))}
            </div>
          </>
        )}

        <section id="custom-plan" className="mt-20 scroll-mt-24">
          <h2 className="text-2xl font-black tracking-tight sm:text-3xl">{PRICING_PUBLISHED ? "پلن خودتان را بسازید" : "محاسبهٔ قیمت پلن سفارشی"}</h2>
          {PRICING_PUBLISHED ? (
            <>
              <p className="mt-2 text-text-2">فقط برای همان چیزی که لازم دارید هزینه کنید؛ قیمت همزمان با تغییرات محاسبه می‌شود.</p>
              <div className="mt-6"><PricingCalculator key={preset?.n ?? 0} billing={billing} initial={preset?.config} /></div>
            </>
          ) : (
            <p data-testid="pricing-calculator-status" className="mt-4 rounded-2xl border border-border bg-surface px-6 py-4 font-bold text-brand">{PRICING_COMING_SOON}</p>
          )}
        </section>

        <div className="mt-20">
          <h2 id="pricing-compare-heading" className="text-2xl font-black tracking-tight sm:text-3xl">مقایسه کامل پلن‌ها</h2>
          <p className="mt-2 text-sm text-text-2 sm:hidden">برای دیدن پلن‌های دیگر، جدول را به چپ و راست بکشید.</p>
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
