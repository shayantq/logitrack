/** اجزای مشترک عملکرد راننده: ستاره امتیاز، نشان سطح، کارت پیشرفت سطح و مبلغ ریالی */
import { useState } from "react";
import { Star, TrendingUp } from "lucide-react";
import type { Schemas } from "@/api/client";
import { faNumber } from "@/lib/format";
import { cn } from "@/ui/primitives";

export const SOURCE_LABELS: Record<string, string> = { organization: "سازمان", customer: "مشتری", platform: "پلتفرم" };
const LEVEL_STYLES = [
  "from-stone-400 to-stone-600", "from-slate-300 to-slate-500", "from-amber-300 to-amber-600", "from-cyan-300 to-sky-600",
  "from-violet-400 to-fuchsia-600", "from-rose-400 to-red-600",
];

export function Rial({ value, className }: { value?: number | null; className?: string }) {
  return <span className={cn("tnum", className)}>{faNumber(Math.round(value ?? 0))} <span className="text-[0.8em] font-normal text-muted">ریال</span></span>;
}

export function Stars({ value, size = "sm", count }: { value?: number | null; size?: "sm" | "md" | "lg"; count?: number }) {
  const px = { sm: "size-3.5", md: "size-4", lg: "size-6" }[size];
  return (
    <span className="inline-flex items-center gap-1" aria-label={value ? `امتیاز ${value} از ۵` : "بدون امتیاز"}>
      <span className="relative inline-flex" dir="ltr">
        <span className="flex text-border-strong">{[0, 1, 2, 3, 4].map(i => <Star key={i} className={cn(px, "fill-current")} />)}</span>
        <span className="absolute inset-y-0 left-0 flex overflow-hidden text-accent" style={{ width: `${((value ?? 0) / 5) * 100}%` }}>
          {[0, 1, 2, 3, 4].map(i => <Star key={i} className={cn(px, "shrink-0 fill-current")} />)}
        </span>
      </span>
      {value != null && <span className="text-xs font-bold tnum">{faNumber(value)}</span>}
      {count != null && <span className="text-xs text-muted">({faNumber(count)})</span>}
    </span>
  );
}

export function StarInput({ value, onChange, size = "md", testId }: { value: number; onChange: (v: number) => void; size?: "md" | "lg"; testId?: string }) {
  const [hover, setHover] = useState(0);
  const px = size === "lg" ? "size-10" : "size-7";
  return (
    <div className="inline-flex gap-1" dir="ltr" onMouseLeave={() => setHover(0)} role="radiogroup" data-testid={testId}>
      {[1, 2, 3, 4, 5].map(i => (
        <button key={i} type="button" role="radio" aria-checked={value === i} aria-label={`${i} ستاره`} data-star={i}
          onMouseEnter={() => setHover(i)} onClick={() => onChange(i)} className="transition hover:scale-110">
          <Star className={cn(px, (hover || value) >= i ? "fill-accent text-accent" : "text-border-strong")} />
        </button>
      ))}
    </div>
  );
}

export function LevelBadge({ code, name, index = 0, size = "md" }: { code: string; name?: string; index?: number; size?: "sm" | "md" | "lg" }) {
  const box = { sm: "size-7 text-xs", md: "size-10 text-base", lg: "size-16 text-2xl" }[size];
  return (
    <span className="inline-flex items-center gap-2" data-testid="level-badge" data-level={code}>
      <span className={cn("grid place-items-center rounded-2xl bg-linear-to-br font-black text-white shadow-sm ring-2 ring-white/40", box,
        LEVEL_STYLES[Math.min(index, LEVEL_STYLES.length - 1)])}>{code}</span>
      {name && <span className="font-bold">{name}</span>}
    </span>
  );
}

/** کارت سطح فعلی، شرط‌های سطح بعد و پورسانت سفر بعدی امروز */
export function LevelProgressCard({ p }: { p: Schemas["LevelProgress"] }) {
  const next = p.next_level;
  const pct = (have: number, need: number) => (need ? Math.min(100, (have / need) * 100) : 100);
  return (
    <div className="space-y-4" data-testid="level-progress">
      <div className="flex flex-wrap items-center gap-4">
        <LevelBadge code={p.level.code} name={p.level.name} index={p.level_index} size="lg" />
        <div className="text-sm text-text-2">
          <div>پورسانت پایه این سطح: <b className="tnum">{faNumber(p.level.commission_percent)}٪</b></div>
          <div>امتیاز: <Stars value={p.rating} /></div>
        </div>
      </div>
      {next ? (
        <div className="rounded-2xl border border-border p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-bold"><TrendingUp className="size-4 text-brand" />تا سطح {next.code} — {next.name} ({faNumber(next.commission_percent)}٪)</div>
          <div className="space-y-2.5 text-xs">
            {[["تحویل موفق", p.deliveries, next.min_deliveries], ["روز همکاری", p.days, next.min_days]].map(([label, have, need]) => (
              <div key={label as string}>
                <div className="mb-1 flex justify-between"><span>{label as string}</span><span className="tnum">{faNumber(have as number)} / {faNumber(need as number)}</span></div>
                <div className="h-1.5 overflow-hidden rounded-full bg-surface-2"><div className="h-full rounded-full bg-brand" style={{ width: `${pct(have as number, need as number)}%` }} /></div>
              </div>
            ))}
            {next.min_rating != null && (
              <div className="flex justify-between"><span>میانگین امتیاز</span>
                <span className={cn("tnum", (p.rating ?? 0) >= next.min_rating ? "text-success" : "text-warning")}>{p.rating != null ? faNumber(p.rating) : "—"} / {faNumber(next.min_rating)}</span></div>
            )}
          </div>
          {p.needs.length > 0 && <p className="mt-3 text-xs text-muted">باقی‌مانده: {p.needs.join("، ")}</p>}
        </div>
      ) : <p className="rounded-2xl bg-success-soft px-4 py-3 text-sm text-success">در بالاترین سطح هستید 🎉</p>}
      <div className="rounded-2xl bg-surface-2 px-4 py-3 text-sm">
        امروز <b className="tnum">{faNumber(p.trips_today)}</b> تحویل — پورسانت سفر بعدی: <b className="tnum">{faNumber(p.next_trip_percent)}٪</b>
        {p.next_tier && <span className="text-muted"> · از سفر {faNumber(p.next_tier.from_trip)}ام امروز {p.next_tier.multiplier_percent === 0 ? "بدون پورسانت" : `${faNumber(p.next_tier.multiplier_percent)}٪ درصد سطح`}</span>}
      </div>
    </div>
  );
}

const BAD_HINTS = ["دیر", "نامناسب", "آسیب", "بدون هماهنگی"];
/** برچسب‌های آماده نظر (مثبت سبز، منفی قرمز) */
export function RatingTags({ tags }: { tags?: string[] | null }) {
  if (!tags?.length) return null;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {tags.map(t => {
        const bad = BAD_HINTS.some(h => t.includes(h));
        return <span key={t} className={cn("rounded-full px-2 py-0.5 text-[11px]", bad ? "bg-danger-soft text-danger" : "bg-success-soft text-success")}>{t}</span>;
      })}
    </span>
  );
}
