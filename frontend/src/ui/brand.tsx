/** لوگو، کلید تم و نمودارهای ساده SVG (بدون کتابخانه سنگین نمودار) */
import { Moon, Sun } from "lucide-react";
import { BRAND } from "@/brand";
import { useTheme } from "@/theme/ThemeProvider";
import { Button, cn } from "./primitives";

/** نشان: مسیر خط‌چین روی یک جعبه — ترکیب «ارسال» و «انبار» */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cn("size-8", className)} aria-hidden="true">
      <rect x="2" y="2" width="28" height="28" rx="9" fill="var(--brand)" />
      <path d="M9 21.5 15 18l8 4.5" stroke="var(--brand-ink)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" fill="none" opacity=".55" />
      <path d="M9 13.5 16 9.5l7 4v7.5" stroke="var(--brand-ink)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <circle cx="23" cy="21" r="2.6" fill="var(--mark-dot)" />
    </svg>
  );
}

export function Logo({ className, compact }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      {!compact && <span className="text-lg font-extrabold tracking-tight">{BRAND.name}</span>}
    </span>
  );
}

/** کلید تم: یک کلیک بین روز و شب؛ خورشید و ماه با چرخش به هم تبدیل می‌شوند */
export function ThemeToggle() {
  const { resolved, toggle } = useTheme();
  const dark = resolved === "dark";
  return (
    <Button variant="ghost" size="icon" className="relative overflow-hidden" data-testid="theme-toggle" data-theme-state={resolved}
      aria-label={dark ? "تم روشن" : "تم تاریک"} title={dark ? "تم روشن" : "تم تاریک"}
      onClick={e => toggle({ x: e.clientX, y: e.clientY })}>
      <Sun className={cn("absolute size-[18px] transition-all duration-500 ease-[cubic-bezier(.4,0,.2,1)]",
        dark ? "-rotate-90 scale-0 opacity-0" : "rotate-0 scale-100 opacity-100")} />
      <Moon className={cn("absolute size-[18px] transition-all duration-500 ease-[cubic-bezier(.4,0,.2,1)]",
        dark ? "rotate-0 scale-100 opacity-100" : "rotate-90 scale-0 opacity-0")} />
    </Button>
  );
}

// ---------------------------------------------------------------- نمودارها
// رنگ‌های پشت‌سرهم نمودار از خانواده‌های متفاوت (نه چند آبی کنار هم)؛ داده می‌تواند رنگ معنایی خودش را بدهد
const CHART_COLORS = ["var(--brand)", "var(--orange)", "var(--info)", "var(--violet)", "var(--success)", "var(--pink)", "var(--warning)", "var(--danger)", "var(--muted)"];
type ChartDatum = { label: string; value: number; color?: string };
const colorOf = (d: ChartDatum, i: number) => d.color ?? CHART_COLORS[i % CHART_COLORS.length];

export function DonutChart({ data, size = 180 }: { data: ChartDatum[]; size?: number }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const r = 70, c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div className="flex flex-wrap items-center gap-6">
      <svg viewBox="0 0 180 180" width={size} height={size} role="img" aria-label="نمودار دایره‌ای">
        <circle cx="90" cy="90" r={r} fill="none" stroke="var(--surface-2)" strokeWidth="22" />
        {total > 0 && data.map((d, i) => {
          const len = (d.value / total) * c;
          const el = (
            <circle key={d.label} cx="90" cy="90" r={r} fill="none" stroke={colorOf(d, i)} strokeWidth="22"
              strokeDasharray={`${Math.max(len - 2, 0)} ${c}`} strokeDashoffset={-offset} transform="rotate(-90 90 90)" strokeLinecap="butt" />
          );
          offset += len;
          return el;
        })}
        <text x="90" y="86" textAnchor="middle" className="fill-[var(--text)] text-[26px] font-extrabold">{total.toLocaleString("fa-IR")}</text>
        <text x="90" y="108" textAnchor="middle" className="fill-[var(--muted)] text-[11px]">مجموع</text>
      </svg>
      <ul className="space-y-1.5 text-sm">
        {data.map((d, i) => (
          <li key={d.label} className="flex items-center gap-2">
            <span className="size-2.5 rounded-full" style={{ background: colorOf(d, i) }} />
            <span className="text-text-2">{d.label}</span>
            <span className="tnum font-semibold">{d.value.toLocaleString("fa-IR")}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function BarChart({ data }: { data: ChartDatum[] }) {
  const max = Math.max(1, ...data.map(d => d.value));
  return (
    <div className="flex h-48 items-end gap-3">
      {data.map((d, i) => (
        <div key={d.label} className="flex flex-1 flex-col items-center gap-2">
          <span className="text-xs font-semibold tnum">{d.value.toLocaleString("fa-IR")}</span>
          <div className="w-full rounded-t-lg transition-all duration-700" style={{ height: `${(d.value / max) * 140}px`, background: colorOf(d, i) }} />
          <span className="text-center text-xs text-muted">{d.label}</span>
        </div>
      ))}
    </div>
  );
}
