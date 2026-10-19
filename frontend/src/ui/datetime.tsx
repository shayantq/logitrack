/**
 * تاریخ شمسی و ساعت — جایگزین تقویم و ساعت انگلیسی پیش‌فرض کروم (input type=date/time).
 * مقدار مثل قبل ISO است: تاریخ «YYYY-MM-DD» (میلادی) و ساعت «HH:MM»؛ فقط نمایش و انتخاب شمسی/فارسی است.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, Clock3, X } from "lucide-react";
import { JALALI_MONTHS, isoToJalali, jalaliMonthLength, jalaliToIso, todayJalali } from "@/lib/jalali";
import { Popover } from "./popover";
import { cn } from "./primitives";

const FA = (v: number | string) => String(v).replace(/\d/g, d => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);
const pad = (n: number) => String(n).padStart(2, "0");
const WEEK = ["ش", "ی", "د", "س", "چ", "پ", "ج"];

const TRIGGER = cn("flex h-10 w-full items-center gap-2 rounded-xl border border-border-strong bg-surface px-3.5 text-start text-sm text-text transition",
  "focus:border-brand focus:outline-none focus:ring-4 focus:ring-brand/15 disabled:cursor-not-allowed disabled:opacity-60");

export function formatJalali(iso: string) {
  if (!iso) return "";
  const { jy, jm, jd } = isoToJalali(iso);
  return `${FA(jd)} ${JALALI_MONTHS[jm - 1]} ${FA(jy)}`;
}

export function DateField({ value, onChange, required, disabled, placeholder = "انتخاب تاریخ", clearable = !required, testId, className, "aria-label": ariaLabel }: {
  value: string; onChange: (iso: string) => void; required?: boolean; disabled?: boolean; placeholder?: string;
  clearable?: boolean; testId?: string; className?: string; "aria-label"?: string;
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const today = todayJalali();
  const start = value ? isoToJalali(value) : today;
  const [view, setView] = useState({ jy: start.jy, jm: start.jm });
  useEffect(() => { if (open) { const s = value ? isoToJalali(value) : todayJalali(); setView({ jy: s.jy, jm: s.jm }); } }, [open, value]);

  const days = jalaliMonthLength(view.jy, view.jm);
  // ستون روز اول ماه (شنبه = ۰)
  const offset = (new Date(`${jalaliToIso(view.jy, view.jm, 1)}T12:00:00`).getDay() + 1) % 7;
  const selected = value ? isoToJalali(value) : null;
  const shift = (delta: number) => setView(v => {
    const m = v.jm + delta;
    return m < 1 ? { jy: v.jy - 1, jm: 12 } : m > 12 ? { jy: v.jy + 1, jm: 1 } : { jy: v.jy, jm: m };
  });
  const pick = (iso: string) => { onChange(iso); setOpen(false); trigger.current?.focus(); };

  return (
    <div className="relative" data-field-root data-date-field>
      <button ref={trigger} type="button" disabled={disabled} onClick={() => setOpen(o => !o)} data-testid={testId} data-value={value}
        aria-label={ariaLabel ?? placeholder} aria-haspopup="dialog" aria-expanded={open} data-focus-target
        className={cn(TRIGGER, open && "border-brand ring-4 ring-brand/15", className)}>
        <CalendarDays className="size-4 shrink-0 text-muted" />
        <span className={cn("min-w-0 flex-1 truncate", !value && "text-muted")}>{value ? formatJalali(value) : placeholder}</span>
        {clearable && value && !disabled && (
          <span role="button" tabIndex={-1} aria-label="پاک کردن" onClick={e => { e.stopPropagation(); onChange(""); }}
            className="grid size-6 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-text"><X className="size-3.5" /></span>
        )}
      </button>
      <input tabIndex={-1} aria-hidden className="sr-only" required={required} value={value} onChange={() => {}} />

      <Popover anchor={trigger} open={open} onClose={() => setOpen(false)} width={288} maxHeight={400} testId={testId && `${testId}-calendar`}>
        <div className="p-3">
          <div className="mb-3 flex items-center justify-between">
            <button type="button" onClick={() => shift(-1)} className="grid size-8 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-text" aria-label="ماه قبل"><ChevronRight className="size-4" /></button>
            <div className="text-sm font-bold">{JALALI_MONTHS[view.jm - 1]} {FA(view.jy)}</div>
            <button type="button" onClick={() => shift(1)} className="grid size-8 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-text" aria-label="ماه بعد"><ChevronLeft className="size-4" /></button>
          </div>
          <div className="grid grid-cols-7 gap-1 text-center text-[11px] text-muted">{WEEK.map(w => <div key={w} className="py-1">{w}</div>)}</div>
          <div className="grid grid-cols-7 gap-1" role="grid">
            {Array.from({ length: offset }, (_, i) => <div key={`e${i}`} />)}
            {Array.from({ length: days }, (_, i) => {
              const d = i + 1;
              const iso = jalaliToIso(view.jy, view.jm, d);
              const isSel = selected?.jy === view.jy && selected?.jm === view.jm && selected?.jd === d;
              const isToday = today.jy === view.jy && today.jm === view.jm && today.jd === d;
              const friday = (offset + i) % 7 === 6;
              return (
                <button key={d} type="button" onClick={() => pick(iso)} data-day={iso}
                  className={cn("grid aspect-square place-items-center rounded-lg text-sm tnum transition",
                    isSel ? "bg-brand font-bold text-brand-ink shadow-sm" : "hover:bg-surface-2",
                    !isSel && isToday && "font-bold text-brand ring-1 ring-inset ring-brand/50",
                    !isSel && friday && "text-danger")}>
                  {FA(d)}
                </button>
              );
            })}
          </div>
          <div className="mt-3 flex items-center justify-between border-t border-border pt-3 text-xs">
            <button type="button" className="font-semibold text-brand hover:underline" onClick={() => pick(jalaliToIso(today.jy, today.jm, today.jd))}>امروز</button>
            {clearable && value && <button type="button" className="text-muted hover:text-danger" onClick={() => pick("")}>پاک کردن</button>}
          </div>
        </div>
      </Popover>
    </div>
  );
}

export function TimeField({ value, onChange, required, disabled, step = 5, testId, className, "aria-label": ariaLabel }: {
  value: string; onChange: (hhmm: string) => void; required?: boolean; disabled?: boolean; step?: number;
  testId?: string; className?: string; "aria-label"?: string;
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  const hoursRef = useRef<HTMLDivElement>(null);
  const minutesRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [h, m] = value ? value.split(":").map(Number) : [NaN, NaN];
  const minutes = useMemo(() => {
    const list = Array.from({ length: 60 / step }, (_, i) => i * step);
    if (!Number.isNaN(m) && !list.includes(m)) list.push(m);
    return list.sort((a, b) => a - b);
  }, [step, m]);
  const set = (hour: number, minute: number, close: boolean) => {
    onChange(`${pad(hour)}:${pad(minute)}`);
    if (close) { setOpen(false); trigger.current?.focus(); }
  };
  useEffect(() => {
    if (!open) return;
    requestAnimationFrame(() => {
      hoursRef.current?.querySelector("[data-selected=true]")?.scrollIntoView({ block: "center" });
      minutesRef.current?.querySelector("[data-selected=true]")?.scrollIntoView({ block: "center" });
    });
  }, [open]);

  const cell = (selected: boolean) => cn("w-full rounded-lg py-1.5 text-center text-sm tnum transition",
    selected ? "bg-brand font-bold text-brand-ink" : "hover:bg-surface-2");
  return (
    <div className="relative" data-field-root data-time-field>
      <button ref={trigger} type="button" disabled={disabled} onClick={() => setOpen(o => !o)} data-testid={testId} data-value={value}
        aria-label={ariaLabel ?? "ساعت"} aria-haspopup="dialog" aria-expanded={open} data-focus-target
        className={cn(TRIGGER, open && "border-brand ring-4 ring-brand/15", className)}>
        <Clock3 className="size-4 shrink-0 text-muted" />
        <span className={cn("flex-1 tnum", !value && "text-muted")}>{value ? FA(value) : "--:--"}</span>
      </button>
      <input tabIndex={-1} aria-hidden className="sr-only" required={required} value={value} onChange={() => {}} />
      <Popover anchor={trigger} open={open} onClose={() => setOpen(false)} width={200} maxHeight={300} testId={testId && `${testId}-picker`}>
        <div className="grid min-h-0 flex-1 grid-cols-2 divide-x divide-x-reverse divide-border">
          <div className="flex min-h-0 flex-col">
            <div className="border-b border-border py-1.5 text-center text-[11px] text-muted">ساعت</div>
            <div ref={hoursRef} className="max-h-60 space-y-0.5 overflow-y-auto p-1">
              {Array.from({ length: 24 }, (_, hour) => (
                <button key={hour} type="button" data-selected={hour === h} data-hour={hour} className={cell(hour === h)}
                  onClick={() => set(hour, Number.isNaN(m) ? 0 : m, false)}>{FA(pad(hour))}</button>
              ))}
            </div>
          </div>
          <div className="flex min-h-0 flex-col">
            <div className="border-b border-border py-1.5 text-center text-[11px] text-muted">دقیقه</div>
            <div ref={minutesRef} className="max-h-60 space-y-0.5 overflow-y-auto p-1">
              {minutes.map(minute => (
                <button key={minute} type="button" data-selected={minute === m} data-minute={minute} className={cell(minute === m)}
                  onClick={() => set(Number.isNaN(h) ? 9 : h, minute, true)}>{FA(pad(minute))}</button>
              ))}
            </div>
          </div>
        </div>
      </Popover>
    </div>
  );
}
