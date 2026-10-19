/** نقشه ارسال‌ها (مرحله ۱۰): همه محموله‌ها روی نقشه ایران با پیشرفت هر مسیر؛ به‌روزرسانی خودکار هر ۱۵ ثانیه */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Map as MapIcon, Navigation, Search, Timer, Truck } from "lucide-react";
import { api, unwrap, type Schemas } from "@/api/client";
import { IranMap } from "@/components/map/IranMap";
import { OrderStatusBadge } from "@/components/StatusBadges";
import { faNumber, faShortDateTime } from "@/lib/format";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, SegmentedControl, Skeleton, cn } from "@/ui/primitives";
import { OrderDetailModal } from "./orders/OrderDetailModal";

type Scope = "active" | "in_transit" | "today";
type MapOrder = Schemas["MapOrder"];

const norm = (s: string) => s.replace(/[يى]/g, "ی").replace(/ك/g, "ک").replace(/\s|‌/g, "").toLowerCase();

export default function MapPage() {
  const [scope, setScope] = useState<Scope>("active");
  const [selected, setSelected] = useState<number | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [q, setQ] = useState("");

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["map-orders", scope],
    queryFn: () => unwrap(api.GET("/map/orders", { params: { query: { scope } } })),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  });
  const orders = data?.orders ?? [];
  const mapped = orders.filter(o => o.available);
  const term = norm(q);
  const listed = useMemo(() => orders.filter(o => !term ||
    norm(`${o.tracking_code} ${o.destination_city} ${o.destination_province} ${o.driver_name ?? ""} ${o.plate ?? ""} ${o.warehouse_name ?? ""}`).includes(term)),
  [orders, term]);
  const active = orders.find(o => o.order_id === selected) ?? null;
  const moving = orders.filter(o => o.status === "in_transit").length;
  const waiting = orders.filter(o => ["pending", "assigned", "picking_up", "picked_up"].includes(o.status)).length;

  return (
    <>
      <PageHeader eyebrow="عملیات" title="نقشه ارسال‌ها" subtitle="مسیر شهربه‌شهر هر محموله و پیشرفت آن بر اساس گزارش رانندگان"
        actions={<SegmentedControl value={scope} onChange={v => { setScope(v); setSelected(null); }} options={[
          { value: "active", label: "فعال" }, { value: "in_transit", label: "در مسیر" }, { value: "today", label: "امروز" },
        ]} />} />

      {data && data.unmapped > 0 && (
        <div className="mb-5 flex flex-wrap items-center gap-3 rounded-xl border border-warning/30 bg-warning-soft/50 px-4 py-3 text-sm" data-testid="map-unmapped">
          <AlertTriangle className="size-4 shrink-0 text-warning" />
          <span className="flex-1">{faNumber(data.unmapped)} سفارش روی نقشه نیست، چون شهر انبار مبدأ یا مقصدش مشخص نیست.</span>
          <Link to="/app/warehouses" className="font-semibold text-brand hover:underline">تکمیل شهر انبارها</Link>
        </div>
      )}

      <div className="mb-5 grid grid-cols-3 gap-3">
        <MiniStat icon={<Navigation className="size-4" />} label="در مسیر" value={moving} tone="text-brand" />
        <MiniStat icon={<Timer className="size-4" />} label="منتظر حرکت" value={waiting} tone="text-warning" />
        <MiniStat icon={<MapIcon className="size-4" />} label="روی نقشه" value={mapped.length} tone="text-text" />
      </div>

      {error ? <ErrorState error={error} onRetry={refetch} /> : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div className="space-y-4">
            {isLoading ? <Skeleton className="h-[60vh] w-full rounded-2xl" /> : (
              <IranMap routes={mapped.map(o => ({ id: o.order_id, points: o.points, progress: o.progress, status: o.status, priority: o.priority }))}
                selectedId={selected} onSelect={id => setSelected(id as number | null)} focus="auto"
                className="h-[52vh] min-h-[380px] lg:h-[62vh]" testId="map-page-map" />
            )}
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted">
              <Legend className="bg-brand" label="در مسیر" /><Legend className="bg-warning" label="منتظر حرکت" />
              <Legend className="bg-success" label="تحویل‌شده" /><Legend className="bg-danger" label="ناموفق / لغو" />
              <span>بخش پررنگ هر مسیر = پیموده‌شده؛ نقطه‌چین = باقی‌مانده</span>
            </div>
            {active && <SelectedPanel order={active} onDetails={() => setDetailId(active.order_id)} onClose={() => setSelected(null)} />}
          </div>

          <Card className="flex max-h-[75vh] flex-col overflow-hidden">
            <div className="border-b border-border p-3">
              <label className="relative block">
                <Search className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
                <input value={q} onChange={e => setQ(e.target.value)} placeholder="کد، شهر، راننده یا پلاک"
                  className="h-10 w-full rounded-xl border border-border bg-surface ps-9 pe-3 text-sm outline-none focus:border-brand" data-testid="map-search" />
              </label>
            </div>
            <div className="flex-1 overflow-y-auto" data-testid="map-list">
              {isLoading ? <div className="space-y-2 p-3">{[0, 1, 2].map(i => <Skeleton key={i} className="h-20 w-full" />)}</div> :
                listed.length === 0 ? <EmptyState icon={<Truck className="size-5" />} title="محموله‌ای در این بخش نیست" /> :
                  listed.map(o => <OrderRow key={o.order_id} order={o} active={o.order_id === selected}
                    onClick={() => setSelected(o.available ? (o.order_id === selected ? null : o.order_id) : null)} />)}
            </div>
          </Card>
        </div>
      )}
      <OrderDetailModal orderId={detailId} onClose={() => setDetailId(null)} />
    </>
  );
}

function MiniStat({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: number; tone: string }) {
  return (
    <div className="card flex items-center gap-3 px-4 py-3">
      <span className={cn("grid size-9 place-items-center rounded-xl bg-surface-2", tone)}>{icon}</span>
      <div><div className="text-xs text-muted">{label}</div><div className="text-lg font-black tnum">{faNumber(value)}</div></div>
    </div>
  );
}

function Legend({ className, label }: { className: string; label: string }) {
  return <span className="inline-flex items-center gap-1.5"><span className={cn("h-1 w-5 rounded-full", className)} />{label}</span>;
}

function OrderRow({ order: o, active, onClick }: { order: MapOrder; active: boolean; onClick: () => void }) {
  const percent = Math.round(o.progress.fraction * 100);
  const origin = o.points[0]?.label ?? o.warehouse_name ?? "—";
  const dest = o.points[o.points.length - 1]?.label ?? o.destination_city ?? "—";
  return (
    <button type="button" onClick={onClick} data-testid="map-row" data-order={o.tracking_code} aria-pressed={active}
      className={cn("block w-full border-b border-border px-4 py-3 text-start transition last:border-b-0",
        active ? "bg-brand-soft/60" : "hover:bg-surface-2")}>
      <div className="flex items-center gap-2">
        <span className="font-mono text-sm font-bold ltr">{o.tracking_code}</span>
        {o.priority && <Badge tone="danger">فوری</Badge>}
        <span className="ms-auto"><OrderStatusBadge status={o.status} /></span>
      </div>
      <div className="mt-1.5 flex items-center gap-1.5 text-sm text-text-2">
        <span className="truncate">{origin}</span><ArrowLeft className="size-3.5 shrink-0 text-muted" /><span className="truncate font-medium text-text">{dest}</span>
      </div>
      {o.available ? (
        <div className="mt-2 flex items-center gap-2">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
            <div className={cn("h-full rounded-full transition-[width] duration-700", o.status === "in_transit" ? "bg-brand" : "bg-warning")} style={{ width: `${percent}%` }} />
          </div>
          <span className="font-mono text-[11px] text-muted tnum">{faNumber(percent)}٪</span>
        </div>
      ) : <div className="mt-1.5 text-xs text-warning">روی نقشه نیست — {o.reason}</div>}
      <div className="mt-1 text-xs text-muted">{o.driver_name ?? "بدون راننده"}{o.plate ? ` · ${o.plate}` : ""}</div>
    </button>
  );
}

function SelectedPanel({ order: o, onDetails, onClose }: { order: MapOrder; onDetails: () => void; onClose: () => void }) {
  const p = o.progress;
  const next = p.next_seq != null ? o.points[p.next_seq] : null;
  const current = p.passed_seq >= 0 ? o.points[p.passed_seq] : null;
  return (
    <Card className="animate-fade p-5" data-testid="map-selected">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono font-bold ltr">{o.tracking_code}</span><OrderStatusBadge status={o.status} />
        <span className="ms-auto font-mono text-lg font-black text-brand tnum">{faNumber(Math.round(p.fraction * 100))}٪</span>
      </div>
      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <Item label="مسیر" value={`${o.points[0]?.label} ← ${o.points[o.points.length - 1]?.label}`} />
        <Item label="پیموده / کل" value={o.total_km ? `${faNumber(p.km_done)} / ${faNumber(o.total_km)} کیلومتر` : "داخل شهر"} />
        <Item label={o.status === "in_transit" ? "آخرین شهر / شهر بعدی" : "وضعیت مسیر"}
          value={o.status === "in_transit" ? `${current?.label ?? "—"} / ${next?.label ?? "مقصد"}` : "هنوز حرکت نکرده"} />
        <Item label="رسیدن تقریبی" value={p.eta ? faShortDateTime(p.eta) : `تا ${faShortDateTime(o.delivery_window_end)}`} />
      </dl>
      {p.last_report && <p className="mt-3 text-xs text-muted">آخرین گزارش راننده: رسیدن به {p.last_report.city} — {faShortDateTime(p.last_report.at)}</p>}
      <div className="mt-4 flex gap-2">
        <Button size="sm" onClick={onDetails} data-testid="map-open-order">جزئیات سفارش</Button>
        <Button size="sm" variant="ghost" onClick={onClose}>نمای کل ایران</Button>
      </div>
    </Card>
  );
}

function Item({ label, value }: { label: string; value: React.ReactNode }) {
  return <div><dt className="text-xs text-muted">{label}</dt><dd className="mt-0.5 font-semibold">{value}</dd></div>;
}
