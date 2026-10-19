/** بازه گزارش با میان‌بُرهای شمسی (این ماه، ماه قبل، سه ماه اخیر، امسال) + انتخاب دلخواه */
import { useState } from "react";
import { jalaliMonthLength, jalaliToIso, todayJalali } from "@/lib/jalali";
import { DateField } from "@/ui/datetime";
import { SegmentedControl } from "@/ui/primitives";

export type Preset = "month" | "last_month" | "quarter" | "year" | "custom";
export type Period = { preset: Preset; from: string; to: string };

const PRESETS: { value: Preset; label: string }[] = [
  { value: "month", label: "این ماه" }, { value: "last_month", label: "ماه قبل" },
  { value: "quarter", label: "سه ماه اخیر" }, { value: "year", label: "امسال" }, { value: "custom", label: "دلخواه" },
];

function shift(jy: number, jm: number, by: number) {
  const index = jy * 12 + (jm - 1) + by;
  return { jy: Math.floor(index / 12), jm: (index % 12) + 1 };
}

export function presetRange(preset: Exclude<Preset, "custom">): { from: string; to: string } {
  const t = todayJalali();
  const today = jalaliToIso(t.jy, t.jm, t.jd);
  if (preset === "last_month") {
    const m = shift(t.jy, t.jm, -1);
    return { from: jalaliToIso(m.jy, m.jm, 1), to: jalaliToIso(m.jy, m.jm, jalaliMonthLength(m.jy, m.jm)) };
  }
  if (preset === "quarter") {
    const m = shift(t.jy, t.jm, -2);
    return { from: jalaliToIso(m.jy, m.jm, 1), to: today };
  }
  if (preset === "year") return { from: jalaliToIso(t.jy, 1, 1), to: today };
  return { from: jalaliToIso(t.jy, t.jm, 1), to: today };
}

export function usePeriod(initial: Exclude<Preset, "custom"> = "month") {
  return useState<Period>(() => ({ preset: initial, ...presetRange(initial) }));
}

export function PeriodPicker({ value, onChange }: { value: Period; onChange: (p: Period) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-3" data-testid="period-picker">
      <SegmentedControl value={value.preset} options={PRESETS}
        onChange={p => onChange(p === "custom" ? { ...value, preset: p } : { preset: p, ...presetRange(p) })} />
      <div className="flex flex-wrap items-center gap-2">
        <DateField aria-label="از تاریخ" placeholder="از تاریخ" required value={value.from} testId="period-from" className="w-44"
          onChange={v => v && onChange({ ...value, preset: "custom", from: v })} />
        <span className="text-xs text-muted">تا</span>
        <DateField aria-label="تا تاریخ" placeholder="تا تاریخ" required value={value.to} testId="period-to" className="w-44"
          onChange={v => v && onChange({ ...value, preset: "custom", to: v })} />
      </div>
    </div>
  );
}

/** «۱۵۰٫۷ میلیون» — برای محور نمودار و کارت‌ها */
export function faMoneyShort(v: number): string {
  const fmt = (n: number) => n.toLocaleString("fa-IR", { maximumFractionDigits: 1 });
  if (Math.abs(v) >= 1e9) return `${fmt(v / 1e9)} میلیارد`;
  if (Math.abs(v) >= 1e6) return `${fmt(v / 1e6)} میلیون`;
  return v.toLocaleString("fa-IR");
}
