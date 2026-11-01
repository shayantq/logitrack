/**
 * عملیات میدانی در جزئیات سفارش: شمارش برگشت از راننده، درخواست‌های مشتری، تماس با گیرنده و تحویل به راننده دیگر.
 * هر بخش فقط وقتی داده دارد یا اقدامی ممکن است نمایش داده می‌شود.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { useVehicles } from "@/hooks/data";
import { faNumber, faShortDateTime } from "@/lib/format";
import { promptDialog } from "@/ui/dialogs";
import { Badge, Button, Field, Input, Select } from "@/ui/primitives";

type Order = Schemas["OrderDetailResponse"];
const refreshKeys = ["orders", "stats", "movements", "action-center", "order-timeline"];

function useRefresh(orderId: number, keys: string[]) {
  const queryClient = useQueryClient();
  return () => {
    for (const key of [...keys, ...refreshKeys]) queryClient.invalidateQueries({ queryKey: [key] });
    queryClient.invalidateQueries({ queryKey: ["order", orderId] });
  };
}

function ReturnCard({ orderId, row }: { orderId: number; row: Schemas["DriverReturnOut"] }) {
  const toast = useToast();
  const refresh = useRefresh(orderId, ["driver-returns"]);
  const [counts, setCounts] = useState<Record<number, string>>({});
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const value = (id: number, expected: number) => counts[id] ?? String(expected);
  const receive = useMutation({
    mutationFn: () => unwrap(api.POST("/orders/{order_id}/driver-returns/{return_id}/receive", {
      params: { path: { order_id: orderId, return_id: row.id } },
      body: { lines: row.lines.map(l => ({ product_id: l.product_id, received_quantity: Number(value(l.product_id, l.expected_quantity)), shortage_reason: reasons[l.product_id] || null })) },
    })),
    onSuccess: () => { toast.success("برگشت در انبار ثبت شد و کالا منتظر بازرسی است."); refresh(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const open = row.status === "open";
  return (
    <div className="space-y-3 rounded-xl border border-border p-4 text-sm" data-testid="driver-return" data-status={row.status}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={open ? "warning" : "success"}>{open ? "در انتظار برگشت" : "در انبار ثبت شد"}</Badge>
        <span className="text-text-2">{row.reason}</span>
        <span className="text-xs text-muted">{faShortDateTime(row.received_at ?? row.created_at)}{row.received_by && ` — ${row.received_by}`}</span>
      </div>
      {row.lines.map(l => (
        <div key={l.product_id} className="grid items-end gap-2 sm:grid-cols-[1fr_7rem_1.4fr]">
          <div>{l.product_name} <span className="text-xs text-muted">({faNumber(l.expected_quantity)} عدد)</span></div>
          {open ? <>
            <Field label="شمرده‌شده"><Input type="number" min={0} max={l.expected_quantity} value={value(l.product_id, l.expected_quantity)} data-testid="return-count"
              onChange={e => setCounts(c => ({ ...c, [l.product_id]: e.target.value }))} /></Field>
            {Number(value(l.product_id, l.expected_quantity)) < l.expected_quantity
              ? <Field label="دلیل کسری"><Input value={reasons[l.product_id] ?? ""} maxLength={500} data-testid="return-reason" onChange={e => setReasons(r => ({ ...r, [l.product_id]: e.target.value }))} /></Field>
              : <span />}
          </> : <div className="sm:col-span-2 text-text-2">رسید: {faNumber(l.received_quantity ?? 0)} عدد{l.shortage_reason && ` — کسری: ${l.shortage_reason}`}</div>}
        </div>
      ))}
      {open && <Button size="sm" loading={receive.isPending} onClick={() => receive.mutate()} data-testid="return-receive">ثبت در انبار</Button>}
    </div>
  );
}

export function DriverReturns({ order }: { order: Order }) {
  const { data = [] } = useQuery({
    queryKey: ["driver-returns", order.id, order.stock_state, order.delivery_attempt_count],
    queryFn: () => unwrap(api.GET("/orders/{order_id}/driver-returns", { params: { path: { order_id: order.id } } })),
  });
  if (!data.length) return null;
  return (
    <section className="space-y-2" data-testid="driver-returns">
      <h4 className="text-sm font-bold">برگشت کالا از راننده</h4>
      {data.map(row => <ReturnCard key={row.id} orderId={order.id} row={row} />)}
    </section>
  );
}

export function CustomerRequests({ order }: { order: Order }) {
  const toast = useToast();
  const refresh = useRefresh(order.id, ["customer-requests"]);
  const { data = [] } = useQuery({
    queryKey: ["customer-requests", order.id, order.status],
    queryFn: () => unwrap(api.GET("/orders/{order_id}/customer-requests", { params: { path: { order_id: order.id } } })),
  });
  const decide = useMutation({
    mutationFn: ({ id, approve, note }: { id: number; approve: boolean; note: string | null }) =>
      unwrap(api.POST("/customer-requests/{request_id}/decide", { params: { path: { request_id: id } }, body: { approve, note } })),
    onSuccess: () => { toast.success("تصمیم ثبت شد."); refresh(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const ask = async (id: number, approve: boolean) => {
    const note = await promptDialog({ title: approve ? "تأیید درخواست" : "رد درخواست", label: "پاسخ به مشتری", required: !approve, multiline: true, confirmLabel: approve ? "تأیید" : "رد" });
    if (note !== null) decide.mutate({ id, approve, note: note || null });
  };
  if (!data.length) return null;
  return (
    <section className="space-y-2" data-testid="customer-requests">
      <h4 className="text-sm font-bold">درخواست‌های مشتری</h4>
      {data.map(q => {
        const address = q.kind === "address_change" ? q.payload as Record<string, string> : null;
        return (
          <div key={q.id} className="space-y-2 rounded-xl border border-border p-4 text-sm" data-testid="customer-request" data-kind={q.kind} data-status={q.status}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{q.kind_label}</span>
              <Badge tone={q.status === "pending" ? "warning" : q.status === "approved" ? "success" : "muted"}>{q.status_label}</Badge>
              <span className="text-xs text-muted">{faShortDateTime(q.created_at)}</span>
            </div>
            {address && <p className="text-text-2">نشانی تازه: {address.destination_province} / {address.destination_city} — {address.destination_address}</p>}
            {q.note && <p className="text-text-2">{q.note}</p>}
            {q.decision_note && <p className="text-xs text-muted">پاسخ: {q.decision_note}{q.decided_by && ` — ${q.decided_by}`}</p>}
            {q.status === "pending" && (
              <div className="flex gap-2">
                <Button size="sm" onClick={() => ask(q.id, true)} data-testid="request-approve">{q.kind === "dispute" ? "بستن پرونده" : "تأیید"}</Button>
                <Button size="sm" variant="ghost" onClick={() => ask(q.id, false)} data-testid="request-reject">رد</Button>
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}

export function ContactLog({ order }: { order: Order }) {
  const { data = [] } = useQuery({
    queryKey: ["order-contacts", order.id, order.status],
    queryFn: () => unwrap(api.GET("/orders/{order_id}/contacts", { params: { path: { order_id: order.id } } })),
  });
  if (!data.length) return null;
  return (
    <section data-testid="contact-log">
      <h4 className="mb-2 text-sm font-bold">تماس با گیرنده</h4>
      <ul className="divide-y divide-border rounded-xl border border-border text-sm">
        {data.map(c => <li key={c.id} className="flex flex-wrap gap-2 px-4 py-2"><b>{c.outcome_label}</b><span className="text-xs text-muted">{c.method_label} · {faShortDateTime(c.at)}{c.user_name && ` — ${c.user_name}`}</span>{c.note && <span className="w-full text-text-2">{c.note}</span>}</li>)}
      </ul>
    </section>
  );
}

export function HandoverPanel({ order }: { order: Order }) {
  const me = useMe();
  const toast = useToast();
  const refresh = useRefresh(order.id, ["order-handovers"]);
  const [vehicle, setVehicle] = useState("");
  const moving = order.status === "picked_up" || order.status === "in_transit";
  const { data: vehicles = [] } = useVehicles(moving);
  const { data = [] } = useQuery({
    queryKey: ["order-handovers", order.id, order.vehicle_id],
    queryFn: () => unwrap(api.GET("/orders/{order_id}/handovers", { params: { path: { order_id: order.id } } })),
  });
  const request = useMutation({
    mutationFn: () => unwrap(api.POST("/orders/{order_id}/handovers", { params: { path: { order_id: order.id } }, body: { to_vehicle_id: Number(vehicle), note: null } })),
    onSuccess: () => { toast.success("درخواست برای راننده مقصد فرستاده شد."); setVehicle(""); refresh(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const waiting = data.some(h => h.status === "requested");
  const canStart = me.role === "org_admin" && moving && !waiting;
  if (!canStart && !data.length) return null;
  return (
    <section className="space-y-2" data-testid="handover-panel">
      <h4 className="text-sm font-bold">تحویل بین رانندگان</h4>
      {data.map(h => <p key={h.id} className="text-sm text-text-2" data-testid="handover-row" data-status={h.status}>به {h.to_driver} ({h.to_vehicle_plate}) — {h.status === "requested" ? "منتظر تأیید راننده" : h.status === "accepted" ? "تحویل شد" : `رد شد${h.response_note ? `: ${h.response_note}` : ""}`}</p>)}
      {canStart && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="خودروی مقصد" className="w-64">
            <Select value={vehicle} onChange={e => setVehicle(e.target.value)} data-testid="handover-vehicle">
              <option value="">انتخاب خودرو...</option>
              {vehicles.filter(v => v.id !== order.vehicle_id && v.status !== "inactive" && v.status !== "maintenance").map(v => <option key={v.id} value={v.id}>{v.license_plate}</option>)}
            </Select>
          </Field>
          <Button size="sm" variant="secondary" disabled={!vehicle} loading={request.isPending} onClick={() => request.mutate()} data-testid="handover-request">درخواست تحویل</Button>
        </div>
      )}
    </section>
  );
}
