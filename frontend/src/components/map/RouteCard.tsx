/** کارت مسیر سفارش: نقشه + خلاصه پیشرفت + شهرهای مسیر؛ برای راننده دکمه «رسیدم به ...» (مرحله ۱۰) */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Flag, MapPinned, Navigation, Undo2, Warehouse } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useToast } from "@/components/Toast";
import { faNumber, faShortDateTime } from "@/lib/format";
import { Badge, Button, Skeleton, cn } from "@/ui/primitives";
import { IranMap } from "./IranMap";
import { confirmDialog } from "@/ui/dialogs";

type RouteData = Pick<Schemas["OrderRoute"], "available" | "total_km" | "points" | "progress" | "checkpoints"> &
  Partial<Pick<Schemas["OrderRoute"], "reason" | "departed_at" | "warehouse_name">>;

export function RouteView({ route, status, id = "route", onReport, onUndo, busy = false, mapClassName = "h-64 sm:h-80" }: {
  route: RouteData; status: string; id?: number | string;
  onReport?: (seq: number) => void; onUndo?: () => void; busy?: boolean; mapClassName?: string;
}) {
  if (!route.available) {
    return (
      <div className="flex items-start gap-3 rounded-xl bg-surface-2 px-4 py-3 text-sm text-text-2" data-testid="route-unavailable">
        <MapPinned className="mt-0.5 size-4 shrink-0 text-muted" />{route.reason ?? "مسیر این سفارش روی نقشه مشخص نیست."}
      </div>
    );
  }
  const p = route.progress;
  const total = route.total_km ?? 0;
  const percent = Math.round(p.fraction * 100);
  const moving = status === "in_transit";
  const before = ["pending", "assigned", "picking_up", "picked_up"].includes(status);
  const reachedAt = new Map(route.checkpoints.map(c => [c.seq, c.reached_at]));
  const reporters = new Map(route.checkpoints.map(c => [c.seq, c.reported_by]));
  const last = route.points.length - 1;

  return (
    <div className="space-y-4" data-testid="route-view">
      <IranMap routes={[{ id, points: route.points, progress: p, status }]} className={mapClassName} />

      <div className="rounded-xl border border-border p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div className="text-sm font-bold">
            {before ? "هنوز حرکت نکرده" : status === "delivered" ? "به مقصد رسید" : moving ? "در مسیر" : "متوقف شد"}
            <span className="ms-2 font-normal text-muted">
              {total > 0 ? <>{faNumber(p.km_done)} از {faNumber(total)} کیلومتر</> : "داخل شهر"}
            </span>
          </div>
          <span className="font-mono text-sm font-bold text-brand tnum" data-testid="route-percent">{faNumber(percent)}٪</span>
        </div>
        <div className="mt-2.5 h-2 overflow-hidden rounded-full bg-surface-2">
          <div className="h-full rounded-full bg-linear-to-l from-brand to-accent transition-[width] duration-1000 ease-out" style={{ width: `${percent}%` }} />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-text-2">
          {moving && p.eta && <span>رسیدن تقریبی: <b className="text-text">{faShortDateTime(p.eta)}</b></span>}
          {p.last_report && <span>آخرین گزارش راننده: رسیدن به <b className="text-text">{p.last_report.city}</b> ({faShortDateTime(p.last_report.at)})</span>}
          {moving && p.estimated && <Badge tone="info">پیشرفت بین دو گزارش، تخمینی است</Badge>}
          {before && total > 0 && <span>مسیر پیش‌بینی‌شده: {faNumber(route.points.length)} شهر</span>}
        </div>
      </div>

      <ol className="relative max-h-96 space-y-0 overflow-y-auto pe-1" data-testid="route-cities">
        {route.points.map((pt, i) => {
          const passed = i <= p.passed_seq;
          const isNext = moving && i === p.next_seq;
          const canReport = onReport && moving && i >= 1 && p.next_seq != null && i >= p.next_seq;
          const at = i === 0 ? route.departed_at : reachedAt.get(pt.seq);
          return (
            <li key={pt.seq} className="relative flex gap-3 pb-4 last:pb-0" data-testid="route-city" data-passed={passed} data-seq={pt.seq}>
              {i < last && <span className={cn("absolute start-[13px] top-7 h-[calc(100%-1.25rem)] w-0.5 rounded-full", i < p.passed_seq ? "bg-brand" : "bg-border")} aria-hidden="true" />}
              <span className={cn("relative z-10 grid size-7 shrink-0 place-items-center rounded-full border-2 transition",
                passed ? "border-brand bg-brand text-brand-ink" : isNext ? "border-brand bg-surface text-brand" : "border-border-strong bg-surface text-muted")}>
                {i === 0 ? <Warehouse className="size-3.5" /> : i === last ? <Flag className="size-3.5" /> : passed ? <Check className="size-3.5" strokeWidth={3} /> :
                  isNext ? <Navigation className="size-3.5 animate-pulse" /> : <span className="size-1.5 rounded-full bg-current" />}
              </span>
              <div className="min-w-0 flex-1 pt-0.5">
                <div className="flex flex-wrap items-center gap-x-2 text-sm">
                  <span className={cn("font-semibold", !passed && !isNext && "text-text-2")}>{pt.label}</span>
                  {pt.approx && <span className="text-xs text-muted">(روی نقشه: مرکز استان)</span>}
                  {pt.province !== pt.label && <span className="text-xs text-muted">{pt.province}</span>}
                  <span className="ms-auto font-mono text-[11px] text-muted tnum">{faNumber(pt.km)} کیلومتر</span>
                </div>
                {at && <div className="mt-0.5 text-xs text-muted">{i === 0 ? "حرکت" : "رسید"}: {faShortDateTime(at)}{reporters.get(pt.seq) ? ` — ${reporters.get(pt.seq)}` : ""}</div>}
                {canReport && (
                  <Button size="sm" variant={isNext ? "primary" : "ghost"} className="mt-2" loading={busy && isNext} disabled={busy}
                    onClick={() => onReport!(pt.seq)} data-testid={isNext ? "report-next" : "report-city"}>
                    <MapPinned className="size-3.5" />رسیدم به {pt.label}
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      {onUndo && moving && route.checkpoints.length > 0 && (
        <button type="button" onClick={onUndo} disabled={busy} className="inline-flex items-center gap-1.5 text-xs text-muted transition hover:text-danger" data-testid="report-undo">
          <Undo2 className="size-3.5" />گزارش آخر اشتباه بود؟ برگرداندن
        </button>
      )}
    </div>
  );
}

/** مسیر یک سفارش با دریافت خودکار هر ۱۵ ثانیه؛ با canReport، راننده/ادمین می‌تواند رسیدن به شهر را ثبت کند */
export function OrderRouteCard({ orderId, canReport = false, mapClassName }: { orderId: number; canReport?: boolean; mapClassName?: string }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["order-route", orderId],
    queryFn: () => unwrap(api.GET("/orders/{order_id}/route", { params: { path: { order_id: orderId } } })),
    refetchInterval: 15_000,
  });
  const update = (route: Schemas["OrderRoute"]) => {
    queryClient.setQueryData(["order-route", orderId], route);
    queryClient.invalidateQueries({ queryKey: ["map-orders"] });
  };
  const report = useMutation({
    mutationFn: (seq: number) => unwrap(api.POST("/orders/{order_id}/checkpoints", { params: { path: { order_id: orderId } }, body: { seq } })),
    onSuccess: (route, seq) => { update(route); toast.success(`رسیدن به ${route.points[seq]?.label ?? ""} ثبت شد.`); },
    onError: e => toast.error(errorMessage(e)),
  });
  const undo = useMutation({
    mutationFn: () => unwrap(api.DELETE("/orders/{order_id}/checkpoints/last", { params: { path: { order_id: orderId } } })),
    onSuccess: route => { update(route); toast.success("آخرین گزارش برگردانده شد."); },
    onError: e => toast.error(errorMessage(e)),
  });

  if (isLoading || !data) return <Skeleton className="h-64 w-full rounded-2xl" />;
  return (
    <RouteView route={data} status={data.status} id={orderId} mapClassName={mapClassName}
      onReport={canReport ? seq => report.mutate(seq) : undefined}
      onUndo={canReport ? () => { confirmDialog({ title: "آخرین گزارش موقعیت برگردانده شود؟", text: "پیشرفت مسیر به گزارش قبلی برمی‌گردد.", confirmLabel: "برگرداندن", danger: true }).then(ok => ok && undo.mutate()); } : undefined}
      busy={report.isPending || undo.isPending} />
  );
}
