/**
 * رسیدن مستقیم به یک مورد از لینک (مثلاً کلیک روی اعلان: /app/inventory?product=12)
 * پارامتر از آدرس خوانده و پاک می‌شود، onHit صدا زده می‌شود (مثلاً باز کردن جزئیات یا پاک کردن جستجو)،
 * و ردیفی که data-focus="<param>-<id>" دارد به وسط صفحه می‌آید و چند لحظه برجسته می‌شود (کلاس focus-flash).
 */
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

export function useDeepLink(param: string, { ready = true, onHit }: { ready?: boolean; onHit?: (id: number) => void } = {}): number | null {
  const [params, setParams] = useSearchParams();
  const raw = params.get(param);
  const [flash, setFlash] = useState<number | null>(null);
  const hit = useRef(onHit);
  hit.current = onHit;

  useEffect(() => {
    if (!raw || !ready) return;
    setParams(p => { p.delete(param); return p; }, { replace: true });
    const id = Number(raw);
    if (!Number.isInteger(id) || id <= 0) return;
    hit.current?.(id);
    setFlash(null);
    requestAnimationFrame(() => setFlash(id));      // کلیک دوباره روی همان اعلان هم دوباره برجسته می‌کند
  }, [raw, ready, param, setParams]);

  useEffect(() => {
    if (flash == null) return;
    const t1 = window.setTimeout(() => document.querySelector(`[data-focus="${param}-${flash}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 60);
    const t2 = window.setTimeout(() => setFlash(null), 3000);
    return () => { window.clearTimeout(t1); window.clearTimeout(t2); };
  }, [flash, param]);

  return flash;
}
