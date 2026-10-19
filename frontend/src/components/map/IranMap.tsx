/**
 * نقشه ایران با مسیرهای شهربه‌شهر سفارش‌ها (مرحله ۱۰).
 * هر مسیر یک منحنی نقطه‌چین است که به اندازه پیشرفت سفارش پر می‌شود؛ نشانگر خودرو روی نقطه فعلی است.
 * با انتخاب یک مسیر، نقشه نرم روی همان مسیر زوم می‌کند.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { Schemas } from "@/api/client";
import { cn } from "@/ui/primitives";
import { MAP_HEIGHT, MAP_WIDTH, PROVINCE_PATHS, project } from "./iranGeo";
import { progressAt, routeShape, type Pt } from "./geometry";

export type RoutePoint = Schemas["RoutePoint"];
export type RouteProgress = Schemas["RouteProgress"];
export type MapRoute = { id: number | string; points: RoutePoint[]; progress: RouteProgress; status: string; priority?: boolean };
type Box = { x: number; y: number; w: number; h: number };

const FULL: Box = { x: 0, y: 0, w: MAP_WIDTH, h: MAP_HEIGHT };

/** رنگ هر وضعیت (کلاس‌های Tailwind روی توکن‌های تم) */
function tone(status: string) {
  if (status === "delivered") return { stroke: "stroke-success", fill: "fill-success" };
  if (status === "failed" || status === "canceled" || status === "expired") return { stroke: "stroke-danger", fill: "fill-danger" };
  if (status === "in_transit") return { stroke: "stroke-brand", fill: "fill-brand" };
  return { stroke: "stroke-warning", fill: "fill-warning" };
}

function boxAround(pts: Pt[]): Box {
  if (!pts.length) return FULL;
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const w = Math.max(240, (maxX - minX) * 1.5), h = Math.max(200, (maxY - minY) * 1.5);
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  return { x: cx - w / 2, y: cy - h / 2, w, h };
}

/** جابه‌جایی نرم viewBox */
function useTweenBox(target: Box) {
  const [box, setBox] = useState(target);
  const current = useRef(target);
  useEffect(() => {
    const from = current.current;
    const start = performance.now();
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    const step = (now: number) => {
      const t = reduced ? 1 : Math.min(1, (now - start) / 700);
      const e = 1 - Math.pow(1 - t, 3);
      const next = { x: from.x + (target.x - from.x) * e, y: from.y + (target.y - from.y) * e, w: from.w + (target.w - from.w) * e, h: from.h + (target.h - from.h) * e };
      current.current = next;
      setBox(next);
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target.x, target.y, target.w, target.h]);
  return box;
}

/** پیشرفت با انیمیشن از مقدار قبلی به مقدار جدید (کیلومتر) */
function useTweenKm(target: number) {
  const [km, setKm] = useState(0);
  const current = useRef(0);
  useEffect(() => {
    const from = current.current;
    const start = performance.now();
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    const step = (now: number) => {
      const t = reduced ? 1 : Math.min(1, (now - start) / 1400);
      const e = 1 - Math.pow(1 - t, 3);
      current.current = from + (target - from) * e;
      setKm(current.current);
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target]);
  return km;
}

export function IranMap({ routes, selectedId = null, onSelect, className, focus = "auto", testId = "iran-map" }: {
  routes: MapRoute[]; selectedId?: number | string | null; onSelect?: (id: number | string | null) => void;
  className?: string;
  /** auto: اگر یک مسیر انتخاب شده یا فقط یک مسیر هست، روی آن زوم کن */
  focus?: "auto" | "none";
  testId?: string;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const focusRoute = selectedId != null ? routes.find(r => r.id === selectedId) : routes.length === 1 ? routes[0] : undefined;
  const target = useMemo(
    () => (focus === "auto" && focusRoute ? boxAround(focusRoute.points.map(p => project(p.lat, p.lon))) : FULL),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [focus, focusRoute?.id, focusRoute?.points.length],
  );
  const box = useTweenBox(target);
  // اندازه عناصر (خط، نقطه، متن) بر حسب پیکسل واقعی صفحه — مستقل از زوم و اندازه کادر
  const wrap = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 700, h: 600 });
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setSize({ w: entry.contentRect.width || 700, h: entry.contentRect.height || 600 }));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  // preserveAspectRatio=meet: مقیاس واقعی را ضلع محدودکننده تعیین می‌کند
  const k = Math.max(box.w / size.w, box.h / size.h);
  const highlight = new Set(focusRoute ? [focusRoute.points[0]?.province, focusRoute.points[focusRoute.points.length - 1]?.province] : []);
  const ordered = [...routes].sort((a, b) => (a.id === focusRoute?.id ? 1 : 0) - (b.id === focusRoute?.id ? 1 : 0));

  return (
    <div ref={wrap} className={cn("relative overflow-hidden rounded-2xl border border-border bg-bg-2", className)} data-testid={testId}>
      <svg viewBox={`${box.x} ${box.y} ${box.w} ${box.h}`} className="block size-full" role="img" aria-label="نقشه مسیر سفارش‌ها"
        onClick={e => { if (e.target === e.currentTarget) onSelect?.(null); }}>
        <g>
          {Object.entries(PROVINCE_PATHS).map(([name, d]) => (
            <path key={name} d={d} data-province={name}
              className={cn("transition-colors duration-300", highlight.has(name) ? "fill-brand-soft" : hovered === name ? "fill-surface" : "fill-surface-2/80", "stroke-border")}
              strokeWidth={0.8 * k} strokeLinejoin="round"
              onMouseEnter={() => setHovered(name)} onMouseLeave={() => setHovered(h => (h === name ? null : h))}
              onClick={() => onSelect?.(null)} />
          ))}
        </g>
        {ordered.map(r => (
          <RouteLayer key={r.id} route={r} k={k} selected={r.id === focusRoute?.id} dimmed={focusRoute != null && r.id !== focusRoute.id}
            detailed={r.id === focusRoute?.id || routes.length === 1} onSelect={onSelect} />
        ))}
      </svg>
      {hovered && <div className="pointer-events-none absolute end-3 top-3 rounded-lg bg-surface/90 px-2.5 py-1 text-xs font-medium shadow-sm backdrop-blur">{hovered}</div>}
      <div className="pointer-events-none absolute bottom-1.5 start-2 text-[10px] text-muted ltr">© OpenStreetMap</div>
    </div>
  );
}

function RouteLayer({ route, k, selected, dimmed, detailed, onSelect }: {
  route: MapRoute; k: number; selected: boolean; dimmed: boolean; detailed: boolean; onSelect?: (id: number | string) => void;
}) {
  const pts = useMemo(() => route.points.map(p => project(p.lat, p.lon)), [route.points]);
  const shape = useMemo(() => routeShape(pts, route.points.map(p => p.km)), [pts, route.points]);
  const km = useTweenKm(route.progress.km_done);
  const done = progressAt(shape, km);
  const c = tone(route.status);
  const width = (selected ? 3.2 : detailed ? 2.6 : 1.8) * k;
  const moving = route.status === "in_transit";
  const passed = route.progress.passed_seq;
  const last = route.points.length - 1;
  const labelSeqs = new Set(detailed ? (route.points.length <= 9 ? route.points.map(p => p.seq) : [0, last, passed, passed + 1]) : []);

  if (pts.length === 1) {
    // مبدأ و مقصد در یک شهر
    const [x, y] = pts[0];
    return (
      <g className={cn("cursor-pointer transition-opacity", dimmed && "opacity-40")} onClick={() => onSelect?.(route.id)} data-route={route.id}>
        <circle cx={x} cy={y} r={7 * k} className={cn(c.fill, "opacity-25")}>
          {moving && <animate attributeName="r" values={`${5 * k};${12 * k};${5 * k}`} dur="2s" repeatCount="indefinite" />}
        </circle>
        <circle cx={x} cy={y} r={4 * k} className={cn(c.fill, "stroke-surface")} strokeWidth={1.5 * k} />
        {detailed && <Label x={x} y={y - 9 * k} k={k} text={route.points[0].label} strong />}
      </g>
    );
  }

  return (
    <g className={cn("transition-opacity duration-300", dimmed && "opacity-35")} data-route={route.id}>
      {/* مسیر کامل: نقطه‌چین */}
      <path d={shape.d} fill="none" className="stroke-border-strong" strokeWidth={width * 0.8}
        strokeDasharray={`${2.5 * k} ${4 * k}`} strokeLinecap="round" />
      {/* بخش پیموده‌شده */}
      {done.d && <path d={done.d} fill="none" className={c.stroke} strokeWidth={width} strokeLinecap="round" />}
      {/* ناحیه کلیک */}
      {onSelect && <path d={shape.d} fill="none" stroke="transparent" strokeWidth={14 * k} className="cursor-pointer"
        onClick={e => { e.stopPropagation(); onSelect(route.id); }} />}

      {route.points.map((p, i) => {
        const [x, y] = pts[i];
        const isEnd = i === 0 || i === last;
        if (!detailed && !isEnd) return null;
        const reached = i <= passed;
        return (
          <g key={p.seq} className="pointer-events-none">
            {i === last ? (
              <circle cx={x} cy={y} r={(detailed ? 6.5 : 4) * k} className={cn(reached ? c.fill : "fill-surface", c.stroke)} strokeWidth={2 * k} />
            ) : i === 0 ? (
              <rect x={x - 5 * k} y={y - 5 * k} width={10 * k} height={10 * k} rx={2.5 * k}
                className={cn(reached ? c.fill : "fill-surface", c.stroke)} strokeWidth={2 * k} />
            ) : (
              <circle cx={x} cy={y} r={3.8 * k} className={reached ? c.fill : "fill-surface stroke-border-strong"} strokeWidth={1.6 * k} />
            )}
            {labelSeqs.has(p.seq) && <Label x={x} y={y - 10 * k} k={k} text={p.label + (p.approx ? " (حدودی)" : "")} strong={isEnd} />}
          </g>
        );
      })}

      {/* خودرو */}
      {done.point && passed >= 0 && route.status !== "delivered" && (
        <g className="pointer-events-none" data-vehicle>
          {moving && (
            <circle cx={done.point[0]} cy={done.point[1]} r={8 * k} className={cn(c.fill, "opacity-30")}>
              <animate attributeName="r" values={`${7 * k};${17 * k};${7 * k}`} dur="2s" repeatCount="indefinite" />
              <animate attributeName="opacity" values=".45;0;.45" dur="2s" repeatCount="indefinite" />
            </circle>
          )}
          <circle cx={done.point[0]} cy={done.point[1]} r={6.5 * k} className={cn(c.fill, "stroke-surface")} strokeWidth={2.5 * k} />
        </g>
      )}
    </g>
  );
}

function Label({ x, y, k, text, strong }: { x: number; y: number; k: number; text: string; strong?: boolean }) {
  return (
    <text x={x} y={y} textAnchor="middle" fontSize={(strong ? 13 : 11.5) * k} fontWeight={strong ? 700 : 500}
      className="fill-text stroke-surface" strokeWidth={3 * k} paintOrder="stroke" strokeLinejoin="round">{text}</text>
  );
}
