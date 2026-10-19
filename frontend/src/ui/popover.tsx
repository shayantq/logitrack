/**
 * پنجره شناور زیر/بالای یک عنصر (برای فهرست انتخاب، تقویم و ساعت) — جایگزین پنجره‌های پیش‌فرض مرورگر.
 * در portal رندر می‌شود تا داخل مودال‌ها و جدول‌ها بریده نشود؛ با اسکرول و تغییر اندازه جابه‌جا می‌شود.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { cn } from "./primitives";

type Place = { top: number; left: number; width: number; maxHeight: number; above: boolean };

export function Popover({ anchor, open, onClose, children, width = "anchor", maxHeight = 320, className, testId }: {
  anchor: RefObject<HTMLElement | null>; open: boolean; onClose: () => void; children: ReactNode;
  /** «anchor» = هم‌عرض عنصر (حداقل ۱۸۰)، یا عدد ثابت */
  width?: "anchor" | number; maxHeight?: number; className?: string; testId?: string;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<Place | null>(null);

  const measure = useCallback(() => {
    const el = anchor.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const w = width === "anchor" ? Math.max(r.width, 180) : width;
    const below = window.innerHeight - r.bottom - 12;
    const above = r.top - 12;
    const placeAbove = below < Math.min(maxHeight, 220) && above > below;
    // راست‌چین: لبه راست پنجره با لبه راست عنصر (در صورت جا نشدن، داخل صفحه نگه داشته می‌شود)
    let left = r.right - w;
    left = Math.min(Math.max(8, left), window.innerWidth - w - 8);
    setPlace({
      top: placeAbove ? r.top - 6 : r.bottom + 6, left, width: w,
      maxHeight: Math.max(160, Math.min(maxHeight, placeAbove ? above : below)), above: placeAbove,
    });
  }, [anchor, width, maxHeight]);

  useLayoutEffect(() => { if (open) measure(); }, [open, measure]);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (panel.current?.contains(t) || anchor.current?.contains(t)) return;
      onClose();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); anchor.current?.focus(); } };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [open, onClose, measure, anchor]);

  if (!open || !place) return null;
  return createPortal(
    <div ref={panel} dir="rtl" data-testid={testId} data-popover
      style={{ top: place.top, left: place.left, width: place.width, maxHeight: place.maxHeight,
        transform: place.above ? "translateY(-100%)" : undefined, transformOrigin: place.above ? "bottom" : "top" }}
      className={cn("fixed z-[70] flex flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-float animate-pop", className)}>
      {children}
    </div>,
    // داخل مودال‌ها همان‌جا رندر شود تا تله فوکوس و «کلیک بیرون» مودال آن را قطع نکند
    anchor.current?.closest<HTMLElement>("[role=dialog]") ?? document.body,
  );
}
