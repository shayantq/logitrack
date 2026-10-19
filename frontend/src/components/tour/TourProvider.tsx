/**
 * راهنمای تعاملی قدم‌به‌قدم: عنصر هر قدم روشن (spotlight) و کارت توضیح کنارش؛ «بعدی» / «متوجه شدم» و «رد شدن».
 * - فقط بار اول خودکار باز می‌شود: «دیده شد/رد شد» روی سرور ذخیره می‌شود (users.tour_state) — روی هر دستگاهی.
 * - اول راهنمای اصلی نقش، بعد در اولین بازدید هر صفحه راهنمای همان صفحه.
 * - کلیدها: Esc = رد شدن، Enter یا ← = بعدی، → = قبلی (راست‌به‌چپ).
 * - localStorage["tours-off"] = "1" باز شدن خودکار را خاموش می‌کند (برای تست خودکار).
 */
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useLocation } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Compass, X } from "lucide-react";
import { api, unwrap } from "@/api/client";
import { useMe, type Me } from "@/auth/AuthContext";
import { Button, cn } from "@/ui/primitives";
import { mainTourFor, pageTourFor, type Tour } from "./tours";

type TourApi = { start: (tour: Tour) => void; mainTour?: Tour; pageTour?: Tour };
const TourContext = createContext<TourApi>({ start: () => {} });
export const useTour = () => useContext(TourContext);

const PAD = 8;
const CARD_W = 340;
type Rect = { top: number; left: number; width: number; height: number };

function autoDisabled() {
  try { return localStorage.getItem("tours-off") === "1"; } catch { return false; }
}

function visibleRect(selector?: string): Rect | null {
  if (!selector) return null;
  const el = document.querySelector(selector);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return null;            // پنهان (مثلاً منوی کناری در موبایل)
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

export function TourProvider({ children }: { children: ReactNode }) {
  const me = useMe();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [active, setActive] = useState<Tour | null>(null);
  const [index, setIndex] = useState(0);
  const role = me.role;
  const mainTour = mainTourFor(role);
  const pageTour = pageTourFor(role, location.pathname);
  const state = me.tour_state ?? {};

  const save = useCallback((tour: Tour, result: "done" | "skipped") => {
    // فوراً در حافظه هم ثبت می‌شود تا تا پاسخ سرور دوباره باز نشود
    queryClient.setQueryData<Me>(["me"], old => old ? { ...old, tour_state: { ...(old.tour_state ?? {}), [tour.id]: result } } : old);
    unwrap(api.PUT("/users/me/tours/{tour_id}", { params: { path: { tour_id: tour.id } }, body: { state: result } })).catch(() => {});
  }, [queryClient]);

  const start = useCallback((tour: Tour) => { setIndex(0); setActive(tour); }, []);
  const finish = useCallback((result: "done" | "skipped") => {
    if (active) save(active, result);
    setActive(null);
  }, [active, save]);

  // بار اول: راهنمای اصلی؛ بعد از آن، راهنمای هر صفحه در اولین بازدید
  useEffect(() => {
    if (active || autoDisabled()) return;
    const next = mainTour && !state[mainTour.id] ? mainTour : pageTour && mainTour && state[mainTour.id] && !state[pageTour.id] ? pageTour : null;
    if (!next) return;
    const t = setTimeout(() => start(next), 900);       // صبر تا محتوای صفحه بارگذاری و انیمیشن ورودش تمام شود
    return () => clearTimeout(t);
  }, [active, mainTour, pageTour, state, start]);

  // با رفتن به صفحه دیگر، راهنمای صفحه قبلی بسته می‌شود (دیده‌شده حساب نمی‌شود)
  useEffect(() => { setActive(a => (a?.path ? null : a)); }, [location.pathname]);

  const value = useMemo(() => ({ start, mainTour, pageTour }), [start, mainTour, pageTour]);
  return (
    <TourContext.Provider value={value}>
      {children}
      {active && createPortal(
        <TourOverlay tour={active} index={index} onIndex={setIndex} onFinish={finish} />, document.body)}
    </TourContext.Provider>
  );
}

function TourOverlay({ tour, index, onIndex, onFinish }: {
  tour: Tour; index: number; onIndex: (i: number) => void; onFinish: (r: "done" | "skipped") => void;
}) {
  const step = tour.steps[index];
  const last = index === tour.steps.length - 1;
  const [rect, setRect] = useState<Rect | null>(null);
  const [view, setView] = useState({ w: window.innerWidth, h: window.innerHeight });
  const card = useRef<HTMLDivElement>(null);
  const primary = useRef<HTMLButtonElement>(null);
  const [cardH, setCardH] = useState(200);

  // عنصر هدف را وسط صفحه بیاور و موقعیتش را دنبال کن (اسکرول، تغییر اندازه، انیمیشن ورود صفحه)
  useLayoutEffect(() => {
    const el = step.target ? document.querySelector(step.target) : null;
    if (el && el.getBoundingClientRect().width > 1) el.scrollIntoView({ block: "center", behavior: "smooth" });
    let frame = 0;
    const tick = () => {
      const r = visibleRect(step.target);
      setRect(prev => (prev && r && Math.abs(prev.top - r.top) < 0.5 && Math.abs(prev.left - r.left) < 0.5
        && Math.abs(prev.width - r.width) < 0.5 && Math.abs(prev.height - r.height) < 0.5) || (!prev && !r) ? prev : r);
      setView(v => (v.w === window.innerWidth && v.h === window.innerHeight ? v : { w: window.innerWidth, h: window.innerHeight }));
      frame = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(frame);
  }, [step.target]);

  useLayoutEffect(() => { if (card.current) setCardH(card.current.offsetHeight); }, [index, rect === null]);
  useEffect(() => { primary.current?.focus({ preventScroll: true }); }, [index]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); onFinish("skipped"); }
      else if (e.key === "Enter" || e.key === "ArrowLeft") { e.preventDefault(); last ? onFinish("done") : onIndex(index + 1); }
      else if (e.key === "ArrowRight" && index > 0) { e.preventDefault(); onIndex(index - 1); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, last, onFinish, onIndex]);

  // جای کارت: زیر هدف، وگرنه بالا، وگرنه کنار؛ همیشه داخل صفحه
  const width = Math.min(CARD_W, view.w - 24);
  let pos: { top: number; left: number };
  if (!rect) {
    pos = { top: Math.max(16, (view.h - cardH) / 2), left: (view.w - width) / 2 };
  } else {
    const below = rect.top + rect.height + PAD + 12;
    const above = rect.top - PAD - 12 - cardH;
    const sideRight = rect.left - PAD - 12 - width;                      // سمت چپِ هدف (منوی کناری راست است)
    let top: number, left: number;
    if (below + cardH < view.h - 12) { top = below; left = rect.left + rect.width / 2 - width / 2; }
    else if (above > 12) { top = above; left = rect.left + rect.width / 2 - width / 2; }
    else if (sideRight > 12) { top = rect.top + rect.height / 2 - cardH / 2; left = sideRight; }
    else { top = view.h - cardH - 12; left = (view.w - width) / 2; }
    pos = { top: Math.min(Math.max(12, top), view.h - cardH - 12), left: Math.min(Math.max(12, left), view.w - width - 12) };
  }
  const hole = rect && { top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 };

  return (
    <div className="fixed inset-0 z-[70]" data-testid="tour" data-tour-id={tour.id} data-step={index} dir="rtl">
      {/* لایه تیره؛ کلیک روی آن راهنما را نمی‌بندد تا اشتباهی رد نشود */}
      {hole ? (
        <div className="pointer-events-none fixed rounded-2xl ring-2 ring-brand transition-all duration-500 ease-[cubic-bezier(.2,.8,.2,1)]"
          style={{ ...hole, boxShadow: "0 0 0 9999px rgb(4 10 32 / 0.6)" }} data-testid="tour-spotlight" />
      ) : (
        <div className="fixed inset-0 animate-[page-fade_.3s_ease-out] bg-[rgb(4_10_32/0.62)]" />
      )}
      <div className="fixed inset-0" />
      <div ref={card} role="dialog" aria-modal="true" aria-labelledby="tour-title"
        className="fixed rounded-2xl border border-border bg-surface p-5 shadow-float transition-[top,left] duration-500 ease-[cubic-bezier(.2,.8,.2,1)]"
        style={{ top: pos.top, left: pos.left, width }} data-testid="tour-card">
        <div key={`${tour.id}-${index}`} className="animate-pop">
          <div className="mb-2 flex items-center justify-between gap-3">
            <span className="flex items-center gap-1.5 text-xs font-medium text-brand"><Compass className="size-4" />راهنما</span>
            <button type="button" onClick={() => onFinish("skipped")} className="grid size-7 place-items-center rounded-lg text-muted transition hover:bg-surface-2 hover:text-text"
              aria-label="بستن راهنما"><X className="size-4" /></button>
          </div>
          <h2 id="tour-title" className="text-base font-bold">{step.title}</h2>
          <p className="mt-1.5 text-sm leading-7 text-text-2">{step.body}</p>
        </div>
        <div className="mt-4 flex items-center gap-2">
          {tour.steps.length > 1 && (
            <div className="flex items-center gap-1" aria-label={`قدم ${index + 1} از ${tour.steps.length}`}>
              {tour.steps.map((_, i) => (
                <span key={i} className={cn("h-1.5 rounded-full transition-all duration-300", i === index ? "w-5 bg-brand" : i < index ? "w-1.5 bg-brand/50" : "w-1.5 bg-border-strong")} />
              ))}
            </div>
          )}
          <div className="ms-auto flex items-center gap-1.5">
            <Button variant="ghost" size="sm" onClick={() => onFinish("skipped")} data-testid="tour-skip">رد شدن</Button>
            {index > 0 && <Button variant="secondary" size="sm" onClick={() => onIndex(index - 1)} data-testid="tour-back">قبلی</Button>}
            <Button ref={primary} size="sm" onClick={() => (last ? onFinish("done") : onIndex(index + 1))} data-testid="tour-next">
              {last ? "متوجه شدم" : "بعدی"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
