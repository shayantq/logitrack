/** جستجوی پیشرفته سفارش‌ها (مرحله ۹): سراسری + کد، کالا، راننده، پلاک، روز تحویل، استان، وضعیت، فوری */
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronDown, Search, SlidersHorizontal, X } from "lucide-react";
import { JalaliDateInput, thisJalaliYear } from "@/components/driver/DriverInputs";
import { useProvinces } from "@/hooks/data";
import { ORDER_STATUS } from "@/lib/labels";
import { faDate } from "@/lib/format";
import { isoDate, pyWeekday } from "@/lib/schedule";
import { SavedViews } from "@/components/SavedViews";
import { Button, Checkbox, Field, Input, Select, cn } from "@/ui/primitives";

export const FILTER_KEYS = ["q", "order_status", "province", "tracking_code", "product", "driver", "plate", "delivery_from", "delivery_to", "priority", "view"] as const;
export type OrderFilters = Partial<Record<(typeof FILTER_KEYS)[number], string>>;

const LABELS: Record<string, string> = {
  q: "جستجو", order_status: "وضعیت", province: "استان", tracking_code: "کد", product: "کالا", driver: "راننده", plate: "پلاک",
  delivery_from: "تحویل از", delivery_to: "تحویل تا", priority: "فوری", view: "نما",
};
// نماهای نام‌دار سرور (همان تعریف کارت‌های مرکز اقدام)
export const ORDER_VIEW_LABELS: Record<string, string> = { late: "دیرکرد", today: "فعال امروز", needs_update: "منتظر ثبت حرکت" };

const day = (offset: number) => { const d = new Date(); d.setDate(d.getDate() + offset); return isoDate(d); };
function weekRange() {
  const now = new Date();
  const sat = new Date(now.getFullYear(), now.getMonth(), now.getDate() - ((pyWeekday(now) - 5 + 7) % 7));
  return [isoDate(sat), isoDate(new Date(sat.getFullYear(), sat.getMonth(), sat.getDate() + 6))];
}
const PRESETS: { key: string; label: string; range: () => [string, string] }[] = [
  { key: "yesterday", label: "دیروز", range: () => [day(-1), day(-1)] },
  { key: "today", label: "امروز", range: () => [day(0), day(0)] },
  { key: "tomorrow", label: "فردا", range: () => [day(1), day(1)] },
  { key: "week", label: "این هفته", range: () => weekRange() as [string, string] },
];

/** فیلترها در آدرس صفحه نگه داشته می‌شوند (قابل اشتراک و بازگشت با دکمه Back) */
export function useOrderFilters() {
  const [params, setParams] = useSearchParams();
  const filters: OrderFilters = {};
  for (const k of FILTER_KEYS) { const v = params.get(k); if (v) filters[k] = v; }
  const setFilters = (next: OrderFilters) => {
    const clean = Object.fromEntries(Object.entries(next).filter(([, v]) => v)) as Record<string, string>;
    setParams(clean, { replace: true });
  };
  return [filters, setFilters] as const;
}

export function OrderSearch({ filters, onChange }: { filters: OrderFilters; onChange: (f: OrderFilters) => void }) {
  const { data: provinces = [] } = useProvinces();
  const advancedKeys = ["tracking_code", "product", "driver", "plate", "delivery_from", "priority"] as const;
  const [open, setOpen] = useState(advancedKeys.some(k => filters[k]));
  const [draft, setDraft] = useState<OrderFilters>(filters);
  const set = (k: keyof OrderFilters, v: string | undefined) => setDraft(d => ({ ...d, [k]: v || undefined }));
  const apply = (next: OrderFilters = draft) => {
    const valid = { ...next };
    for (const k of ["q", "tracking_code", "product", "driver", "plate"] as const) if (valid[k] && valid[k]!.trim().length < 2) delete valid[k];
    onChange(valid);
  };
  const presetActive = (r: [string, string]) => filters.delivery_from === r[0] && filters.delivery_to === r[1];
  const setPreset = (r: [string, string] | null) => {
    const next = { ...draft, delivery_from: r?.[0], delivery_to: r?.[1] };
    setDraft(next);
    apply(next);
  };
  const active = Object.entries(filters).filter(([, v]) => v);

  return (
    <div className="border-b border-border" data-testid="order-search">
      <form className="grid gap-3 p-4 md:grid-cols-[1fr_180px_170px_auto_auto_auto]" onSubmit={(e: FormEvent) => { e.preventDefault(); apply(); }}>
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" />
          <Input className="pr-10" placeholder="جستجو در کد، مشتری، کالا، راننده، پلاک، شهر…" value={draft.q ?? ""} onChange={e => set("q", e.target.value)} data-testid="search-q" />
        </div>
        <Select value={draft.order_status ?? ""} onChange={e => { set("order_status", e.target.value); apply({ ...draft, order_status: e.target.value || undefined }); }} data-testid="search-status">
          <option value="">همه وضعیت‌ها</option>
          {Object.entries(ORDER_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </Select>
        <Select value={draft.province ?? ""} onChange={e => { set("province", e.target.value); apply({ ...draft, province: e.target.value || undefined }); }} data-testid="search-province">
          <option value="">همه استان‌ها</option>{provinces.map(p => <option key={p} value={p}>{p}</option>)}
        </Select>
        <Button type="button" variant="ghost" icon={<SlidersHorizontal className="size-4" />} onClick={() => setOpen(o => !o)} data-testid="search-advanced-toggle">
          پیشرفته<ChevronDown className={cn("size-4 transition", open && "rotate-180")} /></Button>
        <Button variant="secondary" type="submit" icon={<Search className="size-4" />} data-testid="search-submit">جستجو</Button>
        <SavedViews page="orders" filters={filters} onApply={f => { setDraft(f as OrderFilters); onChange(f as OrderFilters); }} />
      </form>

      <div className="flex flex-wrap items-center gap-2 px-4 pb-3" data-testid="date-presets">
        <span className="text-xs text-muted">روز تحویل:</span>
        <button type="button" onClick={() => setPreset(null)} className={cn("rounded-full border px-3 py-1 text-xs transition",
          !filters.delivery_from ? "border-brand bg-brand text-brand-ink" : "border-border hover:border-border-strong")}>همه</button>
        {PRESETS.map(p => {
          const r = p.range();
          return <button key={p.key} type="button" onClick={() => setPreset(r)} data-preset={p.key}
            className={cn("rounded-full border px-3 py-1 text-xs transition", presetActive(r) ? "border-brand bg-brand text-brand-ink" : "border-border hover:border-border-strong")}>{p.label}</button>;
        })}
      </div>

      {open && (
        <div className="grid gap-4 border-t border-border bg-surface-2/50 p-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="search-advanced">
          <Field label="کد سفارش" hint="بخشی از کد هم کافی است"><Input className="ltr font-mono" value={draft.tracking_code ?? ""} onChange={e => set("tracking_code", e.target.value)} data-testid="search-code" /></Field>
          <Field label="کالا" hint="نام یا کد کالا"><Input value={draft.product ?? ""} onChange={e => set("product", e.target.value)} data-testid="search-product" /></Field>
          <Field label="راننده" hint="نام، نام کاربری یا کد راننده"><Input value={draft.driver ?? ""} onChange={e => set("driver", e.target.value)} data-testid="search-driver" /></Field>
          <Field label="پلاک" hint="مثلاً ۳۴۵ب یا ۱۲ب۳۴۵"><Input value={draft.plate ?? ""} onChange={e => set("plate", e.target.value)} data-testid="search-plate" /></Field>
          <Field label="تحویل از روز"><JalaliDateInput key={`f-${filters.delivery_from}`} value={draft.delivery_from} onChange={v => set("delivery_from", v ?? undefined)} fromYear={thisJalaliYear() - 1} toYear={thisJalaliYear() + 1} /></Field>
          <Field label="تا روز"><JalaliDateInput key={`t-${filters.delivery_to}`} value={draft.delivery_to} onChange={v => set("delivery_to", v ?? undefined)} fromYear={thisJalaliYear() - 1} toYear={thisJalaliYear() + 1} /></Field>
          <div className="flex items-end pb-2"><Checkbox label="فقط سفارش‌های فوری" checked={draft.priority === "true"} onChange={e => set("priority", e.target.checked ? "true" : undefined)} /></div>
          <div className="flex items-end justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => { setDraft({}); onChange({}); }}>پاک کردن همه</Button>
            <Button type="button" onClick={() => apply()} data-testid="search-apply">اعمال فیلترها</Button>
          </div>
        </div>
      )}

      {active.length > 0 && (
        <div className="flex flex-wrap gap-2 border-t border-border px-4 py-2.5" data-testid="active-filters">
          {active.map(([k, v]) => (
            <span key={k} className="flex items-center gap-1 rounded-full bg-brand-soft px-2.5 py-1 text-xs text-brand-strong">
              {LABELS[k]}: <b>{k.startsWith("delivery") ? faDate(v) : k === "order_status" ? ORDER_STATUS[v as keyof typeof ORDER_STATUS]?.label : k === "priority" ? "بله" : k === "view" ? ORDER_VIEW_LABELS[v] ?? v : v}</b>
              <button type="button" aria-label={`حذف فیلتر ${LABELS[k]}`} onClick={() => { const next = { ...filters, [k]: undefined }; setDraft(next); onChange(next); }}><X className="size-3" /></button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
