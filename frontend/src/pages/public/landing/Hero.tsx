/**
 * بخش آغازین: شهر سه‌بعدی ثابت می‌ماند و با اسکرول، ون از انبار تا مشتری می‌رود؛
 * متن هر مرحله به‌جای اسکرول شدن، جای مرحله قبل ظاهر می‌شود و کارت سفر پر می‌شود.
 */
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Check, ChevronsDown, CircleCheck, Package, Truck, Warehouse, type LucideIcon } from "lucide-react";
import { BRAND } from "@/brand";
import { useTheme } from "@/theme/ThemeProvider";
import { faNumber } from "@/lib/format";
import { buttonClass, cn } from "@/ui/primitives";
import type { CityScene } from "../city/CityScene";
import { TRIAL_DAYS } from "../content/pricing";
import { range, useInView, useReducedMotion, useScrubProgress } from "../motion";

type Stage = { at: number; n: string; title: string; text: string; icon: LucideIcon; time: string };
const STAGES: Stage[] = [
  { at: 0.1, n: "۰۱", title: "سفارش ثبت شد", icon: Package, time: "۰۹:۱۲",
    text: "اقلام، بازه تحویل و نشانی در یک فرم ثبت می‌شود و موجودی همان لحظه از انبار کم می‌شود." },
  { at: 0.26, n: "۰۲", title: "بارگیری در انبار", icon: Warehouse, time: "۰۹:۴۰",
    text: "خودروی آزاد با ظرفیت کافی خودکار انتخاب می‌شود و راننده تحویل بار را در موبایلش تأیید می‌کند." },
  { at: 0.42, n: "۰۳", title: "در مسیر مقصد", icon: Truck, time: "۱۰:۰۵",
    text: "شما و مشتری وضعیت سفارش را لحظه‌به‌لحظه می‌بینید؛ بدون حتی یک تماس با راننده." },
  { at: 0.88, n: "۰۴", title: "تحویل داده شد", icon: Check, time: "۱۰:۳۸",
    text: "تحویل با یک لمس ثبت می‌شود و داشبورد و گزارش‌ها همان لحظه به‌روز می‌شوند." },
];
const ROUTE_KM = 12.4;
/** مسافت باقی‌مانده به کیلومتر کامل (اعشار فارسی «٫» شبیه «/» خوانده می‌شد) */
const kmLeft = (u: number) => { const km = (1 - u) * ROUTE_KM; return km < 1 && km > 0 ? "کمتر از ۱" : faNumber(Math.round(km)); };
const VALUE_POINTS = ["موجودی انبار، همیشه دقیق", "پیگیری لحظه‌ای هر سفارش", "پنل موبایل برای رانندگان"];
const TRIP_MIN = 33;

/** پیشرفت اسکرول بخش ← پیشرفت صحنه: ۸٪ اول صحنه توقف درِ انبار است */
function sceneProgress(p: number) {
  return p < 0.42 ? range(p, 0.1, 0.42) * 0.08 : 0.08 + range(p, 0.42, 0.9) * 0.92;
}

export function Hero() {
  const section = useRef<HTMLElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const sticky = useRef<HTMLDivElement>(null);
  const labels = { warehouse: useRef<HTMLDivElement>(null), customer: useRef<HTMLDivElement>(null), van: useRef<HTMLDivElement>(null) };
  const scene = useRef<CityScene | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const reduced = useReducedMotion();
  const { resolved } = useTheme();
  const visible = useInView(sticky);
  const [progress, setProgress] = useState(reduced ? 0.6 : 0);

  // Three.js فقط در این صفحه و به‌صورت تنبل بارگذاری می‌شود
  useEffect(() => {
    let cancelled = false;
    import("../city/CityScene").then(({ CityScene }) => {
      if (cancelled || !canvas.current) return;
      try {
        scene.current = new CityScene(canvas.current, { warehouse: labels.warehouse.current, customer: labels.customer.current, van: labels.van.current });
        scene.current.setProgress(sceneProgress(reduced ? 0.6 : 0));
        setReady(true);
      } catch {
        setFailed(true); // مرورگر بدون WebGL
      }
    }).catch(() => setFailed(true));
    return () => { cancelled = true; scene.current?.dispose(); scene.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { scene.current?.setTheme(resolved); }, [resolved, ready]);
  useEffect(() => { scene.current?.setRunning(visible && !reduced); }, [visible, reduced, ready]);

  useScrubProgress(section, p => {
    scene.current?.setProgress(sceneProgress(p));
    setProgress(Math.round(p * 400) / 400);
  }, { smooth: 0.8, disabled: reduced });

  const stageIndex = STAGES.reduce((last, s, i) => (progress >= s.at ? i : last), -1);
  const u = range(progress, 0.42, 0.9);
  const delivered = progress >= 0.88;

  return (
    <section ref={section} id="hero" data-section="سفر یک سفارش" className={cn("relative", reduced ? "h-svh" : "h-[460vh]")}>
      <div ref={sticky} className="sticky top-0 h-svh overflow-hidden">
        <canvas ref={canvas} className={cn("absolute inset-0 size-full transition-opacity duration-1000", ready ? "opacity-100" : "opacity-0")} data-testid="city-canvas" />
        {failed && <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_40%,var(--brand-soft),transparent_60%)]" />}

        {/* برچسب‌های شناور روی صحنه — مکانشان را خود صحنه تنظیم می‌کند */}
        <div className={cn("pointer-events-none absolute inset-0 transition-opacity duration-700", ready ? "opacity-100" : "opacity-0")} aria-hidden="true">
          <div ref={labels.warehouse} className="absolute left-0 top-0 hidden md:block">
            <MapChip tone="brand" icon={Warehouse}>انبار مرکزی</MapChip>
          </div>
          <div ref={labels.customer} className={cn("absolute left-0 top-0", stageIndex < 0 && "max-md:hidden")}>
            <MapChip tone={delivered ? "success" : "accent"} icon={delivered ? Check : Package}>{delivered ? "تحویل داده شد" : "مقصد سفارش"}</MapChip>
          </div>
          <div ref={labels.van} className={cn("absolute left-0 top-0 transition-opacity", progress > 0.42 && !delivered ? "opacity-100" : "opacity-0")}>
            <span className="whitespace-nowrap rounded-full bg-text px-2.5 py-1 text-xs font-semibold text-bg shadow-lg">{kmLeft(u)} کیلومتر</span>
          </div>
        </div>

        {/* محو شدن صحنه پشت متن برای خوانایی */}
        <div className="pointer-events-none absolute inset-y-0 right-0 hidden w-[58%] bg-linear-to-l from-bg via-bg/85 to-transparent md:block" />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[62%] bg-linear-to-t from-bg via-bg/90 to-transparent md:hidden" />
        <div className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-linear-to-b from-bg to-transparent" />

        <div className="relative mx-auto flex h-full max-w-7xl items-end px-4 pb-10 pt-20 sm:px-6 md:items-center md:pb-0">
          <div className="w-full max-w-xl">
            <div className="relative">
              {/* معرفی */}
              <div className={cn("transition-all duration-700", stageIndex < 0 ? "translate-y-0 opacity-100" : "pointer-events-none absolute inset-x-0 bottom-0 -translate-y-6 opacity-0")}>
                <div className="eyebrow mb-5">نرم‌افزار آنلاین مدیریت انبار و پخش</div>
                <h1 className="text-4xl font-black leading-[1.2] tracking-tight sm:text-5xl lg:text-6xl">
                  سفارش، انبار و رانندگان،<br /><span className="bg-linear-to-l from-brand to-accent bg-clip-text text-transparent">همه در یک سامانه.</span>
                </h1>
                <p className="mt-5 max-w-md text-base leading-8 text-text-2 sm:text-lg">
                  {BRAND.nameFa} به شرکت‌های پخش و فروشگاه‌ها کمک می‌کند هر سفارش را از انبار تا درِ خانه مشتری، بی‌دردسر مدیریت کنند.
                </p>
                <ul className="mt-5 space-y-2 max-md:[@media(max-height:740px)]:hidden" data-testid="hero-values">
                  {VALUE_POINTS.map(v => (
                    <li key={v} className="flex items-center gap-2 font-medium"><CircleCheck className="size-5 shrink-0 text-success" />{v}</li>
                  ))}
                </ul>
                <div className="mt-7 flex flex-wrap gap-3">
                  <Link to="/request?plan=trial" className={buttonClass("primary", "lg")} data-testid="hero-cta">{`${faNumber(TRIAL_DAYS)} روز رایگان امتحان کنید`}<ArrowLeft className="size-4" /></Link>
                  <Link to="/pricing" className={buttonClass("secondary", "lg")}>تعرفه‌ها</Link>
                </div>
                {!reduced && (
                  <div className="mt-10 hidden items-center gap-2 text-sm text-muted md:flex">
                    <ChevronsDown className="size-4 animate-bounce" />اسکرول کنید تا یک سفارش را دنبال کنید
                  </div>
                )}
              </div>

              {/* مراحل سفر — هر کدام جای قبلی ظاهر می‌شود */}
              {STAGES.map((s, i) => (
                <div key={s.n} data-testid="hero-stage" data-active={i === stageIndex}
                  className={cn("transition-all duration-700",
                    i === stageIndex ? "relative translate-y-0 opacity-100 blur-0" : "pointer-events-none absolute inset-x-0 bottom-0 opacity-0 blur-sm",
                    i < stageIndex && "-translate-y-8", i > stageIndex && "translate-y-8")}>
                  <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-border bg-surface/70 px-3 py-1 text-sm text-muted backdrop-blur">
                    <span className="font-semibold text-brand">مرحله {faNumber(i + 1)} از {faNumber(STAGES.length)}</span>
                    <span className="size-1 rounded-full bg-border-strong" /><span className="tnum">{s.time}</span>
                  </div>
                  <h2 className="flex items-center gap-3 text-3xl font-black tracking-tight sm:text-5xl">
                    <span className={cn("grid size-12 place-items-center rounded-2xl sm:size-14", i === 3 ? "bg-success-soft text-success" : "bg-brand-soft text-brand")}><s.icon className="size-6 sm:size-7" /></span>
                    {s.title}
                  </h2>
                  <p className="mt-5 max-w-md text-base leading-8 text-text-2 sm:text-lg">{s.text}</p>
                </div>
              ))}
            </div>
            <TripCard stageIndex={stageIndex} u={u} delivered={delivered} />
          </div>
        </div>
      </div>
    </section>
  );
}

function MapChip({ children, icon: Icon, tone }: { children: string; icon: LucideIcon; tone: "brand" | "accent" | "success" }) {
  const tones = { brand: "bg-brand text-brand-ink", accent: "bg-accent text-accent-ink", success: "bg-success text-white" };
  return (
    <span className="flex flex-col items-center">
      <span className={cn("flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-bold shadow-lg transition-colors", tones[tone])}>
        <Icon className="size-3.5" />{children}
      </span>
      <span className={cn("h-3 w-px", tone === "brand" ? "bg-brand" : tone === "accent" ? "bg-accent" : "bg-success")} />
    </span>
  );
}

/** کارت رهگیری سفر که با پیشرفت اسکرول پر می‌شود */
function TripCard({ stageIndex, u, delivered }: { stageIndex: number; u: number; delivered: boolean }) {
  return (
    <div className={cn("mt-8 hidden w-full max-w-sm transition-all duration-700 md:block",
      stageIndex >= 0 ? "translate-y-0 opacity-100" : "translate-y-6 opacity-0")} data-testid="trip-card">
      <div className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div>
            <div className="text-xs text-muted">کد رهگیری</div>
            <div className="font-mono text-sm font-bold ltr">LT-2481-K7</div>
          </div>
          <span className={cn("rounded-full px-2.5 py-1 text-xs font-bold", delivered ? "bg-success-soft text-success" : "bg-brand-soft text-brand-strong")}>
            {stageIndex >= 0 ? STAGES[stageIndex].title : "—"}
          </span>
        </div>
        <ol className="space-y-0 px-4 py-3">
          {STAGES.map((s, i) => {
            const done = i < stageIndex || (i === stageIndex && (i !== 2 || delivered));
            const active = i === stageIndex && !done;
            return (
              <li key={s.n} className="relative flex items-center gap-3 py-1.5">
                {i < STAGES.length - 1 && <span className={cn("absolute right-[9px] top-6 h-[calc(100%-12px)] w-0.5 transition-colors duration-500", i < stageIndex ? "bg-brand" : "bg-border")} />}
                <span className={cn("relative grid size-5 place-items-center rounded-full border-2 transition-all duration-500",
                  done ? "border-brand bg-brand text-brand-ink" : active ? "border-brand bg-surface" : "border-border-strong bg-surface")}>
                  {done && <Check className="size-3" strokeWidth={3} />}
                  {active && <span className="size-2 animate-pulse rounded-full bg-brand" />}
                </span>
                <span className={cn("flex-1 text-sm transition-colors", i <= stageIndex ? "font-semibold text-text" : "text-muted")}>{s.title}</span>
                <span className="font-mono text-xs text-muted">{i <= stageIndex ? s.time : "--:--"}</span>
              </li>
            );
          })}
        </ol>
        <div className="border-t border-border px-4 py-3">
          <div className="mb-2 flex justify-between text-xs text-muted">
            <span>باقی‌مانده: <b className="text-text">{kmLeft(u)}</b> کیلومتر</span>
            <span>رسیدن: <b className="tnum text-text">{faNumber(Math.round((1 - u) * TRIP_MIN))}</b> دقیقه</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full origin-right rounded-full bg-linear-to-l from-brand to-accent transition-transform duration-300" style={{ transform: `scaleX(${u})` }} />
          </div>
        </div>
      </div>
    </div>
  );
}
