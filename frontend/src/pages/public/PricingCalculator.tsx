/** ماشین‌حساب پلن سفارشی: اسلایدر منابع، انتخاب ماژول‌ها، جزئیات قیمت لحظه‌ای و پیشنهاد پلن ثابت (همان فرمول قیمت پلن‌ها) */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, ClipboardList, Lightbulb, Minus, Plus, Truck, UserRound, Warehouse, type LucideIcon } from "lucide-react";
import { buttonClass, cn } from "@/ui/primitives";
import {
  ANNUAL_MONTHS, MODULES, RESOURCES, TRIAL_DAYS, customLines, customMonthly, customToQuery, matchPlan,
  type CustomConfig, type ModuleId, type ResourceId,
} from "./content/pricing";

type Billing = "monthly" | "annual";
const fa = (n: number) => Math.round(n).toLocaleString("fa-IR");
const roundK = (n: number) => Math.round(n / 1000) * 1000;
const ICONS: Record<ResourceId, LucideIcon> = { warehouses: Warehouse, drivers: Truck, orders: ClipboardList, users: UserRound };

const DEFAULT: CustomConfig = {
  ...Object.fromEntries(RESOURCES.map(r => [r.id, r.default])) as Record<ResourceId, number>,
  modules: ["reorder"],
};

function ResourceSlider({ id, value, onChange }: { id: ResourceId; value: number; onChange: (v: number) => void }) {
  const r = RESOURCES.find(x => x.id === id)!;
  const Icon = ICONS[id];
  const index = Math.max(0, r.steps.indexOf(value));
  const last = r.steps.length - 1;
  const setIndex = (i: number) => onChange(r.steps[Math.min(last, Math.max(0, i))]);
  const step = (dir: 1 | -1, label: string) => (
    <button type="button" onClick={() => setIndex(index + dir)} disabled={dir < 0 ? index === 0 : index === last}
      aria-label={`${label} ${r.label}`} data-testid={`calc-${id}-${dir > 0 ? "plus" : "minus"}`}
      className="grid size-10 shrink-0 place-items-center rounded-xl border border-border bg-surface text-text-2 transition hover:border-brand hover:text-brand disabled:opacity-40">
      {dir > 0 ? <Plus className="size-4" /> : <Minus className="size-4" />}
    </button>
  );
  return (
    <div data-testid={`calc-${id}`}>
      <div className="flex items-center justify-between gap-3">
        <label htmlFor={`calc-range-${id}`} className="flex items-center gap-2 font-semibold"><Icon className="size-4 text-brand" />{r.label}</label>
        <span className="rounded-lg bg-brand-soft px-2.5 py-1 text-sm font-bold text-brand-strong" data-testid={`calc-${id}-value`}>{fa(value)} {r.unit}</span>
      </div>
      {/* ردیف چپ‌به‌راست (کم ← زیاد) تا «−» کنار کمینه و «+» کنار بیشینه باشد؛ اسلایدر راست‌به‌چپ در Safari آیفون یکدست کار نمی‌کند */}
      <div className="mt-3 flex items-center gap-3" dir="ltr">
        {step(-1, "کاهش")}
        <input id={`calc-range-${id}`} type="range" min={0} max={last} step={1} value={index}
          onChange={e => setIndex(Number(e.target.value))} aria-valuetext={`${fa(value)} ${r.unit}`}
          className="range-slider flex-1" style={{ ["--fill" as string]: `${(index / last) * 100}%` }} data-testid={`calc-${id}-range`} />
        {step(1, "افزایش")}
      </div>
      <div className="mt-1.5 flex justify-between px-[52px] text-xs text-muted" dir="ltr">
        <span>{fa(r.steps[0])}</span><span>{fa(r.steps[last])}</span>
      </div>
    </div>
  );
}

function ModuleSwitch({ id, on, onToggle }: { id: ModuleId; on: boolean; onToggle: () => void }) {
  const m = MODULES.find(x => x.id === id)!;
  return (
    <button type="button" role="switch" aria-checked={on} onClick={onToggle} data-testid={`calc-module-${id}`}
      className={cn("flex w-full items-center gap-3 rounded-2xl border p-4 text-start transition",
        on ? "border-brand bg-brand-soft/50" : "border-border bg-surface hover:border-border-strong")}>
      <span className={cn("relative h-6 w-11 shrink-0 rounded-full transition-colors", on ? "bg-brand" : "bg-surface-2 ring-1 ring-inset ring-border-strong")}>
        <span className={cn("absolute top-0.5 size-5 rounded-full shadow transition-[right,background-color] duration-200", on ? "right-[22px] bg-white" : "right-0.5 bg-muted")} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-semibold">{m.label}</span>
        <span className="block text-sm leading-6 text-muted">{m.hint}</span>
      </span>
      <span className="shrink-0 text-sm font-bold text-text-2">{fa(m.monthly)}<span className="block text-xs font-normal text-muted">تومان/ماه</span></span>
    </button>
  );
}

export function PricingCalculator({ billing, initial }: { billing: Billing; initial?: CustomConfig }) {
  const [config, setConfig] = useState<CustomConfig>(initial ?? DEFAULT);
  // موبایل: وقتی اسلایدرها در دید است ولی کارت جمع کل نه، نوار پایین صفحه جمع لحظه‌ای را نشان می‌دهد
  const controls = useRef<HTMLDivElement>(null);
  const summary = useRef<HTMLElement>(null);
  const [inView, setInView] = useState({ controls: false, summary: false });
  useEffect(() => {
    const io = new IntersectionObserver(entries => setInView(v => {
      const next = { ...v };
      for (const e of entries) next[e.target === summary.current ? "summary" : "controls"] = e.isIntersecting;
      return next;
    }));
    if (controls.current) io.observe(controls.current);
    if (summary.current) io.observe(summary.current);
    return () => io.disconnect();
  }, []);
  const lines = useMemo(() => customLines(config), [config]);
  const monthly = customMonthly(config);
  const match = matchPlan(config);
  const annual = billing === "annual";
  const shown = annual ? roundK((monthly * ANNUAL_MONTHS) / 12) : monthly;

  const setResource = (id: ResourceId) => (v: number) => setConfig(c => ({ ...c, [id]: v }));
  const toggle = (id: ModuleId) => setConfig(c => ({ ...c, modules: c.modules.includes(id) ? c.modules.filter(m => m !== id) : [...c.modules, id] }));

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:items-start" data-testid="pricing-calculator">
      <div ref={controls} className="space-y-6 rounded-3xl border border-border bg-surface p-5 sm:p-7">
        <div className="space-y-7">
          {RESOURCES.map(r => <ResourceSlider key={r.id} id={r.id} value={config[r.id]} onChange={setResource(r.id)} />)}
        </div>
        <div className="border-t border-border pt-6">
          <div className="mb-3 font-semibold">امکانات بیشتر</div>
          <div className="grid gap-3">
            {MODULES.map(m => <ModuleSwitch key={m.id} id={m.id} on={config.modules.includes(m.id)} onToggle={() => toggle(m.id)} />)}
          </div>
        </div>
      </div>

      <aside ref={summary} className="rounded-3xl border border-brand/40 bg-surface p-5 shadow-[var(--shadow-lg)] sm:p-7 lg:sticky lg:top-24" data-testid="calc-summary">
        <div className="text-sm font-semibold text-muted">هزینه پلن شما</div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="text-4xl font-black" data-testid="calc-total" data-monthly={monthly}>{fa(shown)}</span>
          <span className="text-text-2">تومان در ماه</span>
        </div>
        {annual
          ? <div className="mt-1 text-sm font-medium text-success">پرداخت یک‌جا: {fa(monthly * ANNUAL_MONTHS)} تومان در سال</div>
          : <div className="mt-1 text-sm text-muted">با پرداخت سالانه: {fa(roundK((monthly * ANNUAL_MONTHS) / 12))} تومان در ماه</div>}

        <ul className="mt-5 space-y-2.5 border-t border-border pt-5 text-sm" data-testid="calc-lines">
          {lines.map(l => (
            <li key={l.label} className="flex items-start justify-between gap-4">
              <span className="text-text-2">{l.label}</span>
              <span className="shrink-0 font-semibold">{fa(l.amount)}</span>
            </li>
          ))}
        </ul>

        {match && (
          <div className="mt-5 rounded-2xl bg-success-soft p-4 text-sm leading-6 text-success" data-testid="calc-better-plan" data-kind={match.kind}>
            <div className="flex items-center gap-2 font-bold"><Lightbulb className="size-4" />
              {match.kind === "same" ? `این دقیقاً پلن ${match.plan.name} است` : match.kind === "trial" ? `در دوره آزمایشی، رایگان` : `پیشنهاد ما: پلن ${match.plan.name}`}
            </div>
            <p className="mt-1">
              {match.kind === "same" ? "همین قیمت را در کارت این پلن هم می‌بینید."
                : match.kind === "trial" ? `این نیازها در سقف دوره آزمایشی است؛ ${fa(TRIAL_DAYS)} روز رایگان امتحان کنید.`
                : match.saving > 0 ? `همه این نیازها را پوشش می‌دهد و ${fa(match.saving)} تومان در ماه ارزان‌تر است.`
                : "با همین هزینه، همه این نیازها و ظرفیت بیشتری دارد."}
            </p>
            <Link to={`/request?plan=${match.plan.id}`} className="mt-2 inline-flex items-center gap-1 font-bold underline-offset-4 hover:underline">
              {match.kind === "trial" ? "شروع دوره آزمایشی" : `انتخاب پلن ${match.plan.name}`}<ArrowLeft className="size-4" />
            </Link>
          </div>
        )}

        <Link to={`/request?${customToQuery(config)}`} className={buttonClass("primary", "lg", "mt-5 w-full")} data-testid="calc-cta">
          ثبت درخواست با همین پلن<ArrowLeft className="size-4" />
        </Link>
        <p className="mt-3 text-center text-xs text-muted">مبالغ بدون احتساب مالیات بر ارزش افزوده است.</p>
      </aside>

      <div aria-hidden={!(inView.controls && !inView.summary)} data-testid="calc-mobile-bar"
        className={cn("fixed inset-x-3 bottom-[max(0.75rem,env(safe-area-inset-bottom))] z-40 flex items-center justify-between gap-3 rounded-2xl border border-brand/40 bg-surface/95 px-4 py-3 shadow-[var(--shadow-lg)] backdrop-blur transition-all duration-300 lg:hidden",
          inView.controls && !inView.summary ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-6 opacity-0")}>
        <div>
          <div className="text-xs text-muted">هزینه پلن شما</div>
          <div className="font-black">{fa(shown)} <span className="text-sm font-medium text-text-2">تومان در ماه</span></div>
        </div>
        <button type="button" onClick={() => summary.current?.scrollIntoView({ behavior: "smooth", block: "start" })}
          className={buttonClass("primary", "md")} tabIndex={inView.controls && !inView.summary ? 0 : -1}>جزئیات</button>
      </div>
    </div>
  );
}
