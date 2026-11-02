/**
 * تلاش‌های تحویل سفارش و مدرک هر کدام، و تعیین تکلیف تحویل ناموفق.
 * کالای سفارش ناموفق تا تصمیم سر جایش می‌ماند: تحویل دوباره (بازه و خودروی تازه)، برگشت به انبار، یا اختلاف.
 */
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Camera, RotateCcw, Scale, Undo2 } from "lucide-react";
import { api, authFetch, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { useVehicles } from "@/hooks/data";
import { faNumber, faShortDateTime } from "@/lib/format";
import { confirmDialog, promptDialog } from "@/ui/dialogs";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Field, Input, Select, Textarea, ErrorState } from "@/ui/primitives";

type Order = Schemas["OrderDetailResponse"];
type Body = Schemas["ResolveFailureRequest"];

export const FAILURE_RESOLUTION: Record<string, string> = {
  redeliver: "تحویل دوباره", return_to_warehouse: "برگشت به انبار", dispute: "اختلاف در حال رسیدگی",
};

/** datetime-local به وقت مرورگر؛ مقدار پیش‌فرض فردا */
function localInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
const tomorrowAt = (hour: number) => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(hour, 0, 0, 0); return d; };

export function DeliveryAttempts({ order }: { order: Order }) {
  const [photo, setPhoto] = useState<string | null>(null);
  const toast = useToast();
  const { data = [], error, refetch } = useQuery({
    queryKey: ["order-attempts", order.id, order.delivery_attempt_count, order.failure_resolution],
    queryFn: () => unwrap(api.GET("/orders/{order_id}/attempts", { params: { path: { order_id: order.id } } })),
    enabled: (order.delivery_attempt_count ?? 0) > 0,
  });
  const showPhoto = async (attempt: number, evidence: number) => {
    const res = await authFetch(`/orders/${order.id}/attempts/${attempt}/evidence/${evidence}/file`);
    if (res.ok) setPhoto(URL.createObjectURL(await res.blob()));
    else toast.error("عکس در دسترس نیست.");
  };
  if (error) return <ErrorState error={error} onRetry={refetch} />;
  if (!data.length) return null;
  return (
    <section data-testid="delivery-attempts">
      <h4 className="mb-3 text-sm font-bold">تلاش‌های تحویل</h4>
      <ul className="divide-y divide-border rounded-xl border border-border text-sm">
        {data.map(a => (
          <li key={a.id} className="space-y-1 px-4 py-3" data-testid="attempt-row" data-outcome={a.outcome}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">تلاش {faNumber(a.attempt_no)}</span>
              <Badge tone={a.outcome === "delivered" ? "success" : "danger"}>{a.outcome === "delivered" ? "تحویل شد" : a.failure_reason_label ?? "ناموفق"}</Badge>
              <span className="text-xs text-muted">{faShortDateTime(a.at)}{a.driver_name && ` — ${a.driver_name}`}</span>
            </div>
            {a.evidence.map(e => (
              <div key={e.id} className="flex flex-wrap items-center gap-2 text-xs text-text-2" data-testid="attempt-evidence">
                {e.file_deleted ? <Badge tone="muted">فایل طبق سیاست نگهداری پاک شده</Badge> : (
                  <Button size="sm" variant="ghost" icon={<Camera className="size-4" />} onClick={() => showPhoto(a.attempt_no, e.id)} data-testid="attempt-photo">عکس</Button>
                )}
                <span>{e.delivery_method_label}{e.method_note && `: ${e.method_note}`}</span>
                <span className="text-muted">{e.uploaded_at ? faShortDateTime(e.uploaded_at) : "زمان ثبت نشده"} · {e.uploaded_by_name ?? "آپلودکننده ثبت نشده"}</span>
              </div>
            ))}
            {a.recipient_name && <p className="text-text-2">تحویل‌گیرنده: {a.recipient_name}{a.recipient_role_label && ` (${a.recipient_role_label})`}</p>}
            {a.exception_note && <p className="text-warning">کمبود یا آسیب: {a.exception_note}</p>}
            {a.partial && <ul className="text-text-2" data-testid="attempt-lines">{a.lines.filter(l => l.returned_quantity > 0).map(l => <li key={l.product_name}>{l.product_name}: {faNumber(l.delivered_quantity)} تحویل، {faNumber(l.returned_quantity)} برگشتی{l.reason && ` — ${l.reason}`}</li>)}</ul>}
            {a.note && <p className="text-text-2">{a.note}</p>}
            {a.next_attempt_at && <p className="text-xs text-muted">پیشنهاد راننده برای تلاش بعدی: {faShortDateTime(a.next_attempt_at)}</p>}
            {a.resolution_label && <p className="text-xs text-muted">تصمیم: {a.resolution_label}{a.resolved_by_name && ` — ${a.resolved_by_name}`}{a.resolved_at && ` · ${faShortDateTime(a.resolved_at)}`}</p>}
          </li>
        ))}
      </ul>
      <Modal open={!!photo} onClose={() => setPhoto(null)} title="عکس مدرک تحویل" size="lg">
        {photo && <img src={photo} alt="مدرک تحویل" className="mx-auto max-h-[70dvh] rounded-xl" data-testid="attempt-photo-image" />}
      </Modal>
    </section>
  );
}

export function FailureResolution({ order, onDone }: { order: Order; onDone: (updated: Order) => void }) {
  const me = useMe();
  const toast = useToast();
  const isAdmin = me.role === "org_admin";
  const [redelivering, setRedelivering] = useState(false);
  const [start, setStart] = useState(() => localInput(tomorrowAt(9)));
  const [end, setEnd] = useState(() => localInput(tomorrowAt(17)));
  const [vehicle, setVehicle] = useState("");
  const [note, setNote] = useState("");
  const { data: vehicles = [] } = useVehicles(redelivering);
  const resolve = useMutation({
    mutationFn: (body: Body) => unwrap(api.POST("/orders/{order_id}/resolve-failure", { params: { path: { order_id: order.id } }, body })),
    onSuccess: o => { toast.success("تصمیم ثبت شد."); setRedelivering(false); onDone(o); },
    onError: e => toast.error(errorMessage(e)),
  });
  const decide = (resolution: Body["resolution"], extra: Partial<Body> = {}) => resolve.mutate({ resolution, ...extra } as Body);

  const askReturn = async () => {
    const ok = await confirmDialog({
      title: "کالا به انبار برگردد؟", text: "رزرو آزاد می‌شود یا کالای خارج‌شده «در انتظار بازرسی» وارد انبار می‌شود. این تصمیم پایانی است.",
      confirmLabel: "برگشت به انبار", danger: true,
    });
    if (ok) decide("return_to_warehouse");
  };
  const askDispute = async () => {
    const reason = await promptDialog({ title: "ثبت اختلاف", label: "شرح اختلاف", required: false, multiline: true, confirmLabel: "ثبت و ساخت تیکت" });
    if (reason !== null) decide("dispute", { note: reason || null });
  };

  return (
    <section className="space-y-3 rounded-xl border border-danger/30 bg-danger-soft/40 p-4" data-testid="failure-panel">
      <p className="text-sm font-semibold text-danger">
        {order.failure_resolution === "dispute" ? "اختلاف در حال رسیدگی است؛ بعد از نتیجه، سرنوشت کالا را مشخص کنید." : "تحویل ناموفق بود. کالا تا تصمیم شما سر جایش می‌ماند."}
      </p>
      <div className="flex flex-wrap gap-2">
        {isAdmin && <Button size="sm" icon={<RotateCcw className="size-4" />} onClick={() => setRedelivering(v => !v)} data-testid="resolve-redeliver">تحویل دوباره</Button>}
        <Button size="sm" variant="secondary" icon={<Undo2 className="size-4" />} loading={resolve.isPending} onClick={askReturn} data-testid="resolve-return">برگشت به انبار</Button>
        {isAdmin && order.failure_resolution !== "dispute" && <Button size="sm" variant="ghost" icon={<Scale className="size-4" />} onClick={askDispute} data-testid="resolve-dispute">ثبت اختلاف</Button>}
      </div>
      {redelivering && (
        <div className="grid gap-3 sm:grid-cols-2" data-testid="redeliver-form">
          <Field label="شروع بازه تازه"><Input type="datetime-local" value={start} onChange={e => setStart(e.target.value)} data-testid="redeliver-start" /></Field>
          <Field label="پایان بازه تازه"><Input type="datetime-local" value={end} onChange={e => setEnd(e.target.value)} data-testid="redeliver-end" /></Field>
          <Field label="خودرو">
            <Select value={vehicle} onChange={e => setVehicle(e.target.value)} data-testid="redeliver-vehicle">
              <option value="">انتخاب خودکار</option>
              {vehicles.filter(v => v.status !== "inactive" && v.status !== "maintenance").map(v => <option key={v.id} value={v.id}>{v.license_plate}</option>)}
            </Select>
          </Field>
          <Field label="توضیح (اختیاری)"><Textarea rows={1} value={note} onChange={e => setNote(e.target.value)} maxLength={500} /></Field>
          <div className="sm:col-span-2">
            <Button loading={resolve.isPending} data-testid="redeliver-save" disabled={!start || !end}
              onClick={() => decide("redeliver", {
                delivery_window_start: new Date(start).toISOString(), delivery_window_end: new Date(end).toISOString(),
                vehicle_id: vehicle ? Number(vehicle) : null, note: note || null,
              })}>ثبت تحویل دوباره</Button>
          </div>
        </div>
      )}
    </section>
  );
}
