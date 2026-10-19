import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CalendarClock, Clock, Lock, MapPin, MapPinned, Package, Phone, Truck } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { OrderRouteCard } from "@/components/map/RouteCard";
import { OrderStatusBadge, VehicleStatusBadge } from "@/components/StatusBadges";
import { useToast } from "@/components/Toast";
import { ACTIVE_ORDER_STATUSES, VEHICLE_STATUS, VEHICLE_TYPES, type OrderStatus } from "@/lib/labels";
import { faDate, faNumber, faShortDateTime } from "@/lib/format";
import { Link } from "react-router-dom";
import { EMPLOYMENT, WEEK, hhmm, isoDate, pyWeekday } from "@/lib/schedule";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, Skeleton, cn } from "@/ui/primitives";
import { promptDialog } from "@/ui/dialogs";

/** مراحل سفر از دید راننده */
const STEPS: { status: OrderStatus; label: string }[] = [
  { status: "assigned", label: "تخصیص" }, { status: "picking_up", label: "در راه انبار" },
  { status: "picked_up", label: "بارگیری" }, { status: "in_transit", label: "در مسیر" }, { status: "delivered", label: "تحویل" },
];
const NEXT_STEPS: Partial<Record<OrderStatus, [OrderStatus, string, "primary" | "soft" | "secondary"][]>> = {
  assigned: [["picking_up", "در راه انبار هستم", "soft"], ["picked_up", "بار را تحویل گرفتم", "secondary"]],
  picking_up: [["picked_up", "بار را تحویل گرفتم", "primary"]],
  // تحویل فقط پس از ثبت حرکت — تا مسیر روی نقشه و زمان سفر ثبت شود
  picked_up: [["in_transit", "حرکت به سمت مقصد", "primary"]],
  in_transit: [["delivered", "تحویل داده شد", "primary"]],
};
const DRIVER_VEHICLE_STATUSES = ["available", "on_route", "maintenance", "inactive"] as const;

function TripProgress({ status }: { status: string }) {
  const index = STEPS.findIndex(s => s.status === status);
  return (
    <div className="flex items-center gap-1">
      {STEPS.map((s, i) => (
        <div key={s.status} className="flex flex-1 flex-col items-center gap-1.5">
          <div className={cn("h-1.5 w-full rounded-full transition-colors", i <= index ? "bg-brand" : "bg-surface-2")} />
          <span className={cn("text-[10px]", i <= index ? "font-semibold text-brand" : "text-muted")}>{s.label}</span>
        </div>
      ))}
    </div>
  );
}

/** روز تحویل سفارش (تاریخ محلی شروع بازه) */
const deliveryDay = (o: Schemas["OrderResponse"]) => isoDate(new Date(/[zZ]|[+-]\d\d:\d\d$/.test(o.delivery_window_start) ? o.delivery_window_start : `${o.delivery_window_start}Z`));

function OrderCard({ order, locked = false }: { order: Schemas["OrderResponse"]; locked?: boolean }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const change = useMutation({
    mutationFn: ({ status, note }: { status: OrderStatus; note: string | null }) =>
      unwrap(api.PUT("/orders/{order_id}/status", { params: { path: { order_id: order.id } }, body: { order_status: status, note } })),
    onSuccess: () => { toast.success("وضعیت سفارش ثبت شد."); queryClient.invalidateQueries({ queryKey: ["orders"] }); queryClient.invalidateQueries({ queryKey: ["vehicles"] }); },
    onError: e => toast.error(errorMessage(e)),
  });
  // سفارش روزهای آینده تا روز تحویل قفل است (سرور هم همین را اجبار می‌کند)
  const steps = locked ? [] : NEXT_STEPS[order.status as OrderStatus] ?? [];
  const canFail = !locked && ["assigned", "picking_up", "picked_up", "in_transit"].includes(order.status);
  const [showRoute, setShowRoute] = useState(false);

  return (
    <Card className="overflow-hidden" data-testid="driver-order">
      <div className="space-y-4 p-5">
        <div className="flex items-start justify-between gap-2">
          <div>
            <span className="font-mono text-lg font-bold ltr">{order.tracking_code}</span>
            {order.priority && <Badge tone="danger" className="ms-2">فوری</Badge>}
          </div>
          <OrderStatusBadge status={order.status} />
        </div>
        <TripProgress status={order.status} />
        <div className="space-y-2 text-sm">
          <div className="flex gap-2"><MapPin className="mt-0.5 size-4 shrink-0 text-danger" /><span>{order.destination_province} / {order.destination_city} — {order.destination_address}</span></div>
          <div className="flex items-center gap-2"><Phone className="size-4 shrink-0 text-muted" /><span>{order.recipient_name}</span>
            {order.recipient_mobile && <a href={`tel:${order.recipient_mobile}`} className="font-mono font-semibold text-brand ltr">{order.recipient_mobile}</a>}</div>
          <div className="flex items-center gap-2 text-text-2"><Clock className="size-4 shrink-0 text-muted" />{faShortDateTime(order.delivery_window_start)} تا {faShortDateTime(order.delivery_window_end)}</div>
          <div className="flex gap-2 text-text-2"><Package className="mt-0.5 size-4 shrink-0 text-muted" />{order.items.map(i => `${i.product_name} ×${i.quantity}`).join("، ")} — {faNumber(order.total_weight_kg)} کیلوگرم</div>
        </div>
      </div>
      {order.status === "in_transit" ? (
        <div className="border-t border-border p-5" data-testid="driver-route">
          <div className="mb-3 text-sm font-bold">مسیر و گزارش موقعیت</div>
          <p className="mb-3 text-xs leading-6 text-muted">با رسیدن به هر شهر، دکمه «رسیدم به ...» را بزنید تا سازمان و مشتری پیشرفت شما را روی نقشه ببینند.</p>
          <OrderRouteCard orderId={order.id} canReport mapClassName="h-52" />
        </div>
      ) : !locked && order.status !== "delivered" && (
        <div className="border-t border-border px-5 py-3">
          <button type="button" className="inline-flex items-center gap-1.5 text-sm font-medium text-brand" onClick={() => setShowRoute(v => !v)} data-testid="driver-route-toggle">
            <MapPinned className="size-4" />{showRoute ? "بستن مسیر" : "مشاهده مسیر روی نقشه"}
          </button>
          {showRoute && <div className="mt-3 animate-fade"><OrderRouteCard orderId={order.id} mapClassName="h-52" /></div>}
        </div>
      )}
      {locked && (
        <div className="flex items-center gap-2 border-t border-border bg-surface-2 px-5 py-3 text-sm text-muted" data-testid="order-locked">
          <Lock className="size-4 shrink-0" />این سفارش برای {faDate(order.delivery_window_start)} است؛ از همان روز می‌توانید بارگیری و تحویل را ثبت کنید.
        </div>
      )}
      {(steps.length > 0 || canFail) && (
        <div className="flex flex-wrap gap-2 border-t border-border bg-surface-2 p-4">
          {steps.map(([status, label, variant]) => (
            <Button key={status} variant={variant} className="flex-1" loading={change.isPending} onClick={() => change.mutate({ status, note: null })}>{label}</Button>
          ))}
          {canFail && <Button variant="outline-danger" onClick={() => {
            promptDialog({ title: "ثبت تحویل ناموفق", label: "علت عدم تحویل", placeholder: "مثلاً مشتری در دسترس نبود", required: false,
              multiline: true, confirmLabel: "ثبت ناموفق", danger: true }).then(note => { if (note !== null) change.mutate({ status: "failed", note: note || null }); });
          }}>ناموفق</Button>}
        </div>
      )}
    </Card>
  );
}

export default function DriverPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const vehicles = useQuery({ queryKey: ["vehicles"], queryFn: () => unwrap(api.GET("/vehicles/")) });
  const orders = useQuery({ queryKey: ["orders", "driver"], queryFn: () => unwrap(api.GET("/orders/", { params: { query: { limit: 100 } } })), refetchInterval: 15_000 });
  const vehicle = vehicles.data?.[0];
  const setVehicleStatus = useMutation({
    mutationFn: (status: (typeof DRIVER_VEHICLE_STATUSES)[number]) =>
      unwrap(api.PUT("/vehicles/{vehicle_id}/status", { params: { path: { vehicle_id: vehicle!.id } }, body: { vehicle_status: status } })),
    onSuccess: () => { toast.success("وضعیت خودرو ثبت شد."); queryClient.invalidateQueries({ queryKey: ["vehicles"] }); },
    onError: e => toast.error(errorMessage(e)),
  });

  const active = (orders.data ?? []).filter(o => ACTIVE_ORDER_STATUSES.includes(o.status as OrderStatus));
  const todayIso = isoDate(new Date());
  const actionable = active.filter(o => deliveryDay(o) <= todayIso);
  const upcoming = active.filter(o => deliveryDay(o) > todayIso).sort((a, b) => a.delivery_window_start.localeCompare(b.delivery_window_start));
  const finished = (orders.data ?? []).filter(o => !ACTIVE_ORDER_STATUSES.includes(o.status as OrderStatus)).slice(0, 8);

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader eyebrow="راننده" title="خودرو و سفارش‌های من" subtitle="وضعیت هر سفارش را مرحله‌به‌مرحله ثبت کنید — هر ۱۵ ثانیه به‌روز می‌شود." />
      <Card className="mb-6" data-testid="driver-vehicle">
        <CardHeader title={<span className="flex items-center gap-2"><Truck className="size-5 text-brand" />خودروی من</span>}
          actions={vehicle && <VehicleStatusBadge status={vehicle.status} />} />
        <div className="p-5">
          {vehicles.isLoading ? <Skeleton className="h-24" /> : vehicles.error ? <ErrorState error={vehicles.error} onRetry={vehicles.refetch} /> : !vehicle ? (
            <p className="text-sm text-muted">هیچ خودرویی به شما اختصاص داده نشده — با ادمین سازمان هماهنگ کنید.</p>
          ) : (
            <>
              <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                {[["خودرو", vehicle.model ?? "—"], ["پلاک", vehicle.license_plate], ["نوع", VEHICLE_TYPES[vehicle.type ?? ""] ?? vehicle.type], ["ظرفیت", `${faNumber(vehicle.capacity_kg)} کیلوگرم`]].map(([k, v]) => (
                  <div key={k}><dt className="text-xs text-muted">{k}</dt><dd className="mt-0.5 font-semibold">{v}</dd></div>
                ))}
              </dl>
              <div className="mt-4 text-xs text-muted">تغییر وضعیت خودرو</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {DRIVER_VEHICLE_STATUSES.map(s => (
                  <Button key={s} size="sm" variant={vehicle.status === s ? "primary" : "secondary"} disabled={setVehicleStatus.isPending || vehicle.status === s}
                    onClick={() => setVehicleStatus.mutate(s)}>{VEHICLE_STATUS[s]}</Button>
                ))}
              </div>
            </>
          )}
        </div>
      </Card>

      <MySchedule />

      <h2 className="mb-3 font-bold">سفارش‌های امروز <span className="text-muted">({faNumber(actionable.length)})</span></h2>
      {orders.isLoading ? <Skeleton className="h-48 rounded-2xl" /> : orders.error ? <ErrorState error={orders.error} onRetry={orders.refetch} /> : (
        <div className="space-y-4">
          {actionable.length === 0 && <Card><EmptyState icon={<Package className="size-5" />} title="برای امروز سفارش فعالی ندارید" text="سفارش‌های جدید به‌محض تخصیص اینجا ظاهر می‌شوند." /></Card>}
          {actionable.map(o => <OrderCard key={o.id} order={o} />)}
          {upcoming.length > 0 && (
            <div className="space-y-4 pt-2" data-testid="upcoming-orders">
              <h2 className="font-bold">سفارش‌های روزهای آینده <span className="text-muted">({faNumber(upcoming.length)})</span></h2>
              {upcoming.map(o => <OrderCard key={o.id} order={o} locked />)}
            </div>
          )}
          {finished.length > 0 && (
            <Card>
              <CardHeader title="آخرین سفارش‌های تمام‌شده" />
              <ul className="divide-y divide-border">
                {finished.map(o => (
                  <li key={o.id} className="flex items-center justify-between gap-2 px-5 py-3 text-sm">
                    <span className="font-mono ltr">{o.tracking_code}</span><span className="text-text-2">{o.destination_city}</span><OrderStatusBadge status={o.status} />
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

/** برنامه کاری راننده (شیفت‌های هفتگی و مرخصی‌های پیش‌رو) — فقط ادمین سازمان تغییرش می‌دهد */
function MySchedule() {
  const { data } = useQuery({ queryKey: ["my-schedule"], queryFn: () => unwrap(api.GET("/dispatch/my-schedule")) });
  if (!data) return null;
  const now = new Date();
  const today = pyWeekday(now);
  // تاریخ هر روز همین هفته (شنبه تا جمعه) برای لینک به «برنامه و کارنامه»
  const saturday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - ((today - 5 + 7) % 7));
  const dateOf = (weekday: number) => isoDate(new Date(saturday.getFullYear(), saturday.getMonth(), saturday.getDate() + ((weekday - 5 + 7) % 7)));
  return (
    <Card className="mb-6" data-testid="my-schedule">
      <CardHeader title={<span className="flex items-center gap-2"><CalendarClock className="size-5 text-brand" />برنامه کاری من</span>}
        actions={<div className="flex gap-1.5"><Badge tone="brand">{EMPLOYMENT[data.employment_type]}</Badge>{data.intercity && <Badge tone="info">بین‌شهری</Badge>}</div>} />
      <div className="p-5">
        {data.shifts.length === 0 ? <p className="text-sm text-muted">برنامه کاری برای شما ثبت نشده است؛ با ادمین سازمان هماهنگ کنید.</p> : (
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {WEEK.map(w => {
              const shifts = data.shifts.filter(s => s.weekday === w.weekday);
              return (
                <li key={w.weekday}>
                  <Link to={`/app/driver/agenda?day=${dateOf(w.weekday)}`} data-testid="schedule-day-link"
                    className={cn("block rounded-xl border px-3 py-2 transition hover:border-brand", w.weekday === today ? "border-brand bg-brand-soft" : "border-border",
                      !shifts.length && "opacity-60")}>
                    <div className="text-xs font-semibold">{w.name}{w.weekday === today && " (امروز)"}</div>
                    <div className="mt-0.5 font-mono text-sm ltr text-right">{shifts.length ? shifts.map(s => `${hhmm(s.start_time)}–${hhmm(s.end_time)}`).join("، ") : "تعطیل"}</div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          {data.max_daily_orders ? <p className="text-xs text-muted">سقف سفارش روزانه: {faNumber(data.max_daily_orders)}</p> : <span />}
          <div className="flex gap-2">
            <Link to="/app/driver/agenda" className="text-sm font-medium text-brand">برنامه و کارنامه ←</Link>
            <Link to="/app/driver/requests?new=leave" className="text-sm font-medium text-brand" data-testid="quick-leave">درخواست مرخصی ←</Link>
          </div>
        </div>
        {data.time_off.length > 0 && (
          <div className="mt-4 space-y-1.5">
            {data.time_off.map(t => (
              <p key={t.id} className="rounded-xl bg-warning-soft px-3 py-2 text-sm text-warning">مرخصی: {faDate(t.starts_at)} تا {faDate(new Date(new Date(t.ends_at + "Z").getTime() - 1).toISOString())}{t.reason && ` — ${t.reason}`}</p>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
