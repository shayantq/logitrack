import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MapPin, MapPinned, Phone, Truck, UserRound } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { SuggestionList } from "@/components/dispatch/SuggestionList";
import { OrderRouteCard } from "@/components/map/RouteCard";
import { OrderSettlement } from "./OrderSettlement";
import { OrderTimeline } from "./OrderTimeline";
import { OrderStatusBadge } from "@/components/StatusBadges";
import { useToast } from "@/components/Toast";
import { useUsers, useVehicles } from "@/hooks/data";
import { nextStatusesFor, orderStatusLabel, type OrderStatus } from "@/lib/labels";
import { faNumber, faShortDateTime } from "@/lib/format";
import { Modal } from "@/ui/overlays";
import { Badge, Button, ErrorState, Input, Select, Spinner } from "@/ui/primitives";
import { confirmDialog } from "@/ui/dialogs";

function InfoBlock({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface-2 p-4">
      <div className="mb-1.5 flex items-center gap-2 text-xs text-muted">{icon}{title}</div>
      <div className="text-sm">{children}</div>
    </div>
  );
}

export function OrderDetailModal({ orderId, onClose }: { orderId: number | null; onClose: () => void }) {
  const me = useMe();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [nextStatus, setNextStatus] = useState<OrderStatus | "">("");
  const [note, setNote] = useState("");
  const isAdmin = me.role === "org_admin";
  const { data: vehicles = [] } = useVehicles(orderId !== null);
  const { data: users = [] } = useUsers(orderId !== null && isAdmin);

  const { data: order, isLoading, error, refetch } = useQuery({
    queryKey: ["order", orderId],
    queryFn: () => unwrap(api.GET("/orders/{order_id}", { params: { path: { order_id: orderId! } } })),
    enabled: orderId !== null,
    refetchInterval: 15_000,   // تغییر وضعیت توسط راننده بدون بستن پنجره دیده شود
  });

  const refresh = (updated?: Schemas["OrderDetailResponse"]) => {
    if (updated) queryClient.setQueryData(["order", orderId], updated);
    for (const key of ["orders", "products", "vehicles", "stats", "movements"]) queryClient.invalidateQueries({ queryKey: [key] });
    setNextStatus(""); setNote("");
  };
  const changeStatus = useMutation({
    mutationFn: () => unwrap(api.PUT("/orders/{order_id}/status", {
      params: { path: { order_id: orderId! } }, body: { order_status: nextStatus as OrderStatus, note: note || null },
    })),
    onSuccess: o => { toast.success(`وضعیت به «${orderStatusLabel(o.status)}» تغییر کرد.`); refresh(o); },
    onError: e => toast.error(errorMessage(e)),
  });
  const canAssign = order?.status === "pending" && (me.role === "org_admin" || me.role === "warehouse_manager");
  const suggestions = useQuery({
    queryKey: ["order-suggestions", orderId, order?.status],
    queryFn: () => unwrap(api.GET("/dispatch/orders/{order_id}/suggestions", { params: { path: { order_id: orderId! } } })),
    enabled: !!canAssign,
  });
  const assign = useMutation({
    mutationFn: (vehicleId?: number) => unwrap(api.PUT("/orders/{order_id}/assign", {
      params: { path: { order_id: orderId! } }, body: vehicleId ? { vehicle_id: vehicleId } : {},
    })),
    onSuccess: o => { toast.success("خودرو به سفارش تخصیص داده شد."); refresh(o); },
    onError: e => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: () => unwrap(api.DELETE("/orders/{order_id}", { params: { path: { order_id: orderId! } } })),
    onSuccess: () => { toast.success("سفارش حذف شد."); refresh(); onClose(); },
    onError: e => toast.error(errorMessage(e)),
  });

  const vehicle = order ? vehicles.find(v => v.id === order.vehicle_id) : undefined;
  const driver = vehicle ? users.find(u => u.id === vehicle.driver_id) : undefined;
  const nextOptions = order ? nextStatusesFor(me.role, order.status) : [];

  return (
    <Modal open={orderId !== null} onClose={onClose} size="lg" testId="order-detail"
      title={order ? <span className="flex flex-wrap items-center gap-3"><span className="font-mono ltr">{order.tracking_code}</span><OrderStatusBadge status={order.status} />
        {order.priority && <Badge tone="danger">فوری</Badge>}</span> : "جزئیات سفارش"}
      footer={<>
        <Button variant="secondary" onClick={onClose}>بستن</Button>
        {isAdmin && order && <Button variant="outline-danger" loading={remove.isPending}
          onClick={() => confirmDialog({ title: `سفارش ${order.tracking_code} حذف شود؟`, text: "این کار برگشت‌پذیر نیست.", confirmLabel: "حذف سفارش", danger: true }).then(ok => ok && remove.mutate())}>حذف سفارش</Button>}
      </>}>
      {isLoading && <div className="grid place-items-center py-10"><Spinner /></div>}
      {error && <ErrorState error={error} onRetry={refetch} />}
      {order && (
        <div className="space-y-6">
          <div className="grid gap-3 sm:grid-cols-2">
            <InfoBlock icon={<UserRound className="size-3.5" />} title="مشتری / تحویل‌گیرنده">
              <div className="font-medium">{order.customer?.name ?? "—"}</div>
              <div className="text-muted">{order.recipient_name} <span className="font-mono ltr">{order.recipient_mobile}</span></div>
            </InfoBlock>
            <InfoBlock icon={<MapPin className="size-3.5" />} title="مقصد">
              <div className="font-medium">{order.destination_province} / {order.destination_city}</div>
              <div className="text-muted">{order.destination_address}{order.destination_postal_code && ` — ${order.destination_postal_code}`}</div>
            </InfoBlock>
            <InfoBlock icon={<Truck className="size-3.5" />} title="خودرو / راننده">
              {vehicle ? <><div className="font-medium">{vehicle.model ?? vehicle.type} — {vehicle.license_plate}</div><div className="text-muted">{driver?.full_name ?? driver?.username ?? ""}</div></>
                : <span className="text-muted">هنوز خودرو تخصیص نیافته</span>}
            </InfoBlock>
            <InfoBlock icon={<Phone className="size-3.5" />} title="بازه تحویل و جمع">
              <div className="font-medium">{faShortDateTime(order.delivery_window_start)} تا {faShortDateTime(order.delivery_window_end)}</div>
              <div className="text-muted">{faNumber(order.total_quantity)} عدد · {faNumber(order.total_weight_kg)} کیلوگرم · {faNumber(order.total_price)} ریال</div>
            </InfoBlock>
          </div>

          <div className="overflow-hidden rounded-xl border border-border">
            <table className="table-base">
              <thead><tr><th>کالا</th><th>تعداد</th><th>قیمت واحد (لحظه ثبت)</th><th>جمع</th></tr></thead>
              <tbody>
                {order.items.map(i => (
                  <tr key={i.id}>
                    <td><div className="font-medium">{i.product_name}</div><div className="font-mono text-xs text-muted">{i.product_sku}</div></td>
                    <td className="tnum">{faNumber(i.quantity)}</td><td className="tnum">{faNumber(i.unit_price)}</td>
                    <td className="tnum font-medium">{faNumber(i.unit_price * i.quantity)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {order.notes && <p className="rounded-xl bg-surface-2 px-4 py-3 text-sm text-text-2">{order.notes}</p>}

          <section data-testid="order-route">
            <h4 className="mb-3 flex items-center gap-2 text-sm font-bold"><MapPinned className="size-4 text-brand" />مسیر روی نقشه</h4>
            <OrderRouteCard orderId={order.id} canReport={isAdmin} mapClassName="h-56 sm:h-72" />
          </section>

          {(isAdmin || me.role === "warehouse_manager") && <OrderSettlement order={order} />}

          {canAssign && (
            <div className="space-y-3 rounded-xl border border-warning/30 bg-warning-soft/40 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
                <span className="font-semibold text-warning">این سفارش هنوز راننده ندارد — رانندگان پیشنهادی:</span>
                <Button size="sm" variant="secondary" icon={<Truck className="size-4" />} loading={assign.isPending && assign.variables === undefined}
                  onClick={() => assign.mutate(undefined)}>تخصیص خودکار خودرو</Button>
              </div>
              <SuggestionList data={suggestions.data} loading={suggestions.isLoading} weightKg={order.total_weight_kg}
                onAssign={id => assign.mutate(id)} assigning={assign.isPending ? assign.variables ?? null : null} />
            </div>
          )}

          {nextOptions.length > 0 && (
            <div className="grid gap-2 rounded-xl border border-border p-4 sm:grid-cols-[200px_1fr_auto]">
              <Select value={nextStatus} onChange={e => setNextStatus(e.target.value as OrderStatus)} data-testid="next-status" aria-label="وضعیت بعدی">
                <option value="">تغییر وضعیت به...</option>
                {nextOptions.map(s => <option key={s} value={s}>{orderStatusLabel(s)}</option>)}
              </Select>
              <Input placeholder="توضیح (اختیاری)" value={note} onChange={e => setNote(e.target.value)} />
              <Button disabled={!nextStatus} loading={changeStatus.isPending} onClick={() => changeStatus.mutate()} data-testid="apply-status">ثبت</Button>
            </div>
          )}

          <OrderTimeline orderId={order.id} version={`${order.status}-${order.history.length}-${order.priority}`} />
        </div>
      )}
    </Modal>
  );
}
