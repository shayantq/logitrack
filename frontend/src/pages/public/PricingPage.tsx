/** صفحه «تعرفه‌ها»: پلن‌ها با پرداخت ماهانه/سالانه، جدول مقایسه امکانات و پیشنهاد مشتریان اولیه */
import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, Gift, Minus, Phone } from "lucide-react";
import { BRAND } from "@/brand";
import { SegmentedControl, buttonClass, cn } from "@/ui/primitives";
import { InfoLayout } from "./InfoLayout";
import { ANNUAL_MONTHS, EARLY_OFFER, FEATURES, PLANS, type Plan } from "./content/pricing";

type Billing = "monthly" | "annual";
const fa = (n: number) => n.toLocaleString("fa-IR");
/** مبلغ کامل با جداکننده هزارگان (اعشار فارسی «٫» شبیه «/» خوانده می‌شد)؛ واحد زیر عدد تا کارت‌ها هم‌تراز باشند */
function Amount({ value, unit, prefix, note }: { value: string; unit: string; prefix?: string; note?: string }) {
  return (
    <div data-testid="plan-price">
      <div className="flex items-baseline gap-1.5">
        {prefix && <span className="text-base font-medium text-muted">{prefix}</span>}
        <span className="text-3xl font-black">{value}</span>
      </div>
      <div className="mt-1 text-sm text-muted">{unit}</div>
      {note && <div className="mt-1 text-xs text-success">{note}</div>}
    </div>
  );
}

function Price({ plan, billing }: { plan: Plan; billing: Billing }) {
  if (plan.monthly === 0) return <Amount value="رایگان" unit="به مدت ۳۰ روز" />;
  if (plan.monthly === null) return <Amount prefix="از" value={fa(plan.fromMonthly ?? 0)} unit="تومان در ماه" />;
  if (billing === "monthly") return <Amount value={fa(plan.monthly)} unit="تومان در ماه" />;
  const yearly = plan.monthly * ANNUAL_MONTHS;
  return <Amount value={fa(yearly)} unit="تومان در سال" note={`معادل ${fa(Math.round(yearly / 12 / 1000) * 1000)} تومان در ماه`} />;
}

function PlanCard({ plan, billing }: { plan: Plan; billing: Billing }) {
  const to = `/request?plan=${plan.id}`;
  return (
    <div data-testid="plan-card" data-plan={plan.id}
      className={cn("relative flex flex-col rounded-3xl border bg-surface p-6 shadow-[var(--shadow)]",
        plan.highlight ? "border-brand ring-2 ring-brand/30 lg:-translate-y-2" : "border-border")}>
      {plan.highlight && <span className="absolute -top-3 right-6 rounded-full bg-brand px-3 py-1 text-xs font-bold text-white">پیشنهاد ما</span>}
      <h2 className="text-xl font-black">{plan.name}</h2>
      <p className="mt-1.5 min-h-12 text-sm leading-6 text-text-2">{plan.tagline}</p>
      <div className="mt-5"><Price plan={plan} billing={billing} /></div>
      <dl className="mt-6 space-y-2.5 border-t border-border pt-5 text-sm">
        {([["انبار", plan.limits.warehouses], ["راننده", plan.limits.drivers], ["سفارش در ماه", plan.limits.orders], ["کاربر پنل", plan.limits.users]] as const).map(([k, v]) => (
          <div key={k} className="flex items-center justify-between gap-3"><dt className="text-muted">{k}</dt><dd className="font-semibold">{v}</dd></div>
        ))}
      </dl>
      <div className="mt-auto pt-6">
        {plan.id === "enterprise" ? (
          <div className="grid gap-2">
            <a href={`tel:${BRAND.phone}`} className={buttonClass("primary", "lg", "w-full")}><Phone className="size-4" />{plan.cta}</a>
            <Link to={to} className={buttonClass("secondary", "md", "w-full")}>ثبت درخواست</Link>
          </div>
        ) : (
          <Link to={to} className={buttonClass(plan.highlight ? "primary" : "secondary", "lg", "w-full")} data-testid="plan-cta">{plan.cta}</Link>
        )}
      </div>
    </div>
  );
}

export default function PricingPage() {
  const [billing, setBilling] = useState<Billing>("monthly");
  return (
    <InfoLayout title="تعرفه‌ها" testId="pricing-page" eyebrow="تعرفه‌ها"
      heading="هزینه‌ای شفاف، متناسب با اندازه کسب‌وکارتان"
      lead="قیمت هر پلن برای کل سازمان است، نه برای هر کاربر. ۳۰ روز رایگان امتحان کنید و هر زمان خواستید، پلن را تغییر دهید."
      hero={
        <div className="flex flex-wrap items-center gap-3">
          <SegmentedControl value={billing} onChange={setBilling} options={[
            { value: "monthly", label: "ماهانه" }, { value: "annual", label: `سالانه (${fa(12 - ANNUAL_MONTHS)} ماه رایگان)` },
          ]} />
          {EARLY_OFFER && (
            <span className="inline-flex items-center gap-2 rounded-full bg-success-soft px-3.5 py-1.5 text-sm font-medium text-success" data-testid="early-offer">
              <Gift className="size-4" />{EARLY_OFFER}
            </span>
          )}
        </div>
      }>
      <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6 sm:py-20">
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {PLANS.map(p => <PlanCard key={p.id} plan={p} billing={billing} />)}
        </div>
        <p className="mt-6 text-center text-xs text-muted">همه مبالغ به تومان است و برای هر پرداخت، فاکتور رسمی صادر می‌شود.</p>

        <div className="mt-16 overflow-x-auto rounded-3xl border border-border bg-surface" data-testid="pricing-compare">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-border bg-surface-2 text-text-2">
                <th className="px-5 py-4 text-start font-semibold">امکانات</th>
                {PLANS.map(p => <th key={p.id} className={cn("px-4 py-4 text-center font-semibold", p.highlight && "text-brand")}>{p.name}</th>)}
              </tr>
            </thead>
            <tbody>
              {FEATURES.map(f => (
                <tr key={f.label} className="border-b border-border last:border-0">
                  <td className="px-5 py-3.5 text-text-2">{f.label}</td>
                  {PLANS.map(p => {
                    const v = f.values[p.id];
                    return (
                      <td key={p.id} className="px-4 py-3.5 text-center">
                        {v === true ? <Check className="mx-auto size-4 text-success" aria-label="دارد" />
                          : v === false ? <Minus className="mx-auto size-4 text-muted" aria-label="ندارد" />
                          : <span className="text-xs font-medium text-text-2">{v}</span>}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </InfoLayout>
  );
}
