/** فهرست رانندگان پیشنهادی برای یک سفارش (با امتیاز و دلیل) + رانندگانی که کنار گذاشته شدند و چرا */
import { useState } from "react";
import { Check, ChevronDown, Sparkles, UserX } from "lucide-react";
import type { Schemas } from "@/api/client";
import { PlateView } from "@/components/driver/DriverInputs";
import { VEHICLE_TYPES } from "@/lib/labels";
import { faNumber } from "@/lib/format";
import { Button, Skeleton, cn } from "@/ui/primitives";

type Candidate = Schemas["Candidate"];

function CapacityBar({ c, extraKg }: { c: Candidate; extraKg: number }) {
  const cap = c.capacity_kg || 1;
  const used = Math.min(100, (c.load_kg / cap) * 100);
  const adding = Math.min(100 - used, (extraKg / cap) * 100);
  return (
    <div className="mt-2">
      <div className="flex h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
        <div className="bg-text-2/40" style={{ width: `${used}%` }} />
        <div className="bg-brand" style={{ width: `${adding}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-muted">
        <span>این سفارش {faNumber(Math.round(extraKg))} کیلو</span>
        <span>ظرفیت {faNumber(c.capacity_kg)} · رزرو {faNumber(Math.round(c.load_kg))}</span>
      </div>
    </div>
  );
}

export function SuggestionList({ data, loading, weightKg, selected, onSelect, onAssign, assigning }: {
  data?: Schemas["SuggestResponse"]; loading?: boolean; weightKg: number;
  selected?: number | null; onSelect?: (vehicleId: number) => void;
  onAssign?: (vehicleId: number) => void; assigning?: number | null;
}) {
  const [showExcluded, setShowExcluded] = useState(false);
  if (loading && !data) return <div className="space-y-2"><Skeleton className="h-20 rounded-xl" /><Skeleton className="h-20 rounded-xl" /></div>;
  if (!data) return null;

  return (
    <div className="space-y-2" data-testid="suggestions">
      {data.candidates.length === 0 && (
        <p className="rounded-xl border border-warning/30 bg-warning-soft px-4 py-3 text-sm text-warning">
          در این بازه هیچ راننده‌ای با ظرفیت و شیفت مناسب در دسترس نیست. دلایل را پایین ببینید یا زمان تحویل را تغییر دهید.
        </p>
      )}
      {data.candidates.map((c, i) => {
        const isSelected = selected === c.vehicle_id;
        const Tag = onSelect ? "button" : "div";
        return (
          <Tag key={c.vehicle_id} type={onSelect ? "button" : undefined} onClick={onSelect ? () => onSelect(c.vehicle_id) : undefined}
            data-testid="suggestion" data-vehicle={c.vehicle_id}
            className={cn("block w-full rounded-2xl border p-3 text-start transition",
              isSelected ? "border-brand bg-brand-soft ring-2 ring-brand/30" : "border-border bg-surface", onSelect && "hover:border-border-strong")}>
            <div className="flex flex-wrap items-center gap-2">
              {onSelect && (
                <span className={cn("grid size-5 place-items-center rounded-full border-2", isSelected ? "border-brand bg-brand text-brand-ink" : "border-border-strong")}>
                  {isSelected && <Check className="size-3" strokeWidth={3} />}
                </span>
              )}
              <span className="font-bold">{c.driver_name}</span>
              {i === 0 && <span className="flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-bold text-warning"><Sparkles className="size-3" />بهترین گزینه</span>}
              <span className="text-xs text-muted">{c.vehicle_model || VEHICLE_TYPES[c.vehicle_type ?? ""]}</span>
              <PlateView plate={c.license_plate} className="h-7 origin-right scale-90" />
              <span className="ms-auto font-mono text-xs text-muted" title="امتیاز">{faNumber(Math.round(c.score))}</span>
              {onAssign && <Button size="sm" loading={assigning === c.vehicle_id} onClick={() => onAssign(c.vehicle_id)} data-testid="assign-suggestion">تخصیص</Button>}
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {c.reasons.map(r => <span key={r} className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-text-2">{r}</span>)}
            </div>
            <CapacityBar c={c} extraKg={weightKg} />
          </Tag>
        );
      })}

      {data.excluded.length > 0 && (
        <div className="rounded-2xl border border-border">
          <button type="button" onClick={() => setShowExcluded(s => !s)} data-testid="excluded-toggle"
            className="flex w-full items-center gap-2 px-4 py-3 text-sm text-muted hover:text-text">
            <UserX className="size-4" />{faNumber(data.excluded.length)} راننده دیگر مناسب این سفارش نیستند — چرا؟
            <ChevronDown className={cn("ms-auto size-4 transition", showExcluded && "rotate-180")} />
          </button>
          {showExcluded && (
            <ul className="divide-y divide-border border-t border-border text-sm" data-testid="excluded">
              {data.excluded.map(c => (
                <li key={c.vehicle_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5">
                  <span className="font-medium">{c.driver_name ?? "بدون راننده"}</span>
                  <span className="text-xs text-muted">{c.vehicle_model} · {c.license_plate}</span>
                  <span className="ms-auto text-xs text-danger">{c.reason}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
