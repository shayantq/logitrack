/**
 * بسته‌بندی و ارسال (فصل ۱۴): سفارش‌های برداشت‌شده در بسته‌هایی با ابعاد و وزن واقعی بسته‌بندی و برگه بسته‌بندی چاپ
 * می‌شود؛ محموله‌ها روی خودرو با کنترل ظرفیت وزنی و حجمی بسته و با «تحویل به راننده» از انبار خارج می‌شوند.
 */
import { useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Package as PackageIcon, Plus, Printer, Trash2, Truck } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useToast } from "@/components/Toast";
import { useVehicles } from "@/hooks/data";
import { FULFILLMENT, SHIPMENT_STATUS } from "@/lib/labels";
import { faDateTime, faNumber } from "@/lib/format";
import { confirmDialog } from "@/ui/dialogs";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Field, Input, PageHeader, Select, Table, TableSkeleton } from "@/ui/primitives";
import { WarehousePicker, useInvalidateOperations, useWarehouseChoice } from "./shared";

type QueueOrder = Schemas["PackingQueueOut"];
type Slip = Schemas["PackingSlipOut"];

export default function ShippingPage() {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const choice = useWarehouseChoice();
  const warehouseId = choice.value ? Number(choice.value) : null;
  const [packing, setPacking] = useState<QueueOrder | null>(null);
  const [slipFor, setSlipFor] = useState<number | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [vehicle, setVehicle] = useState("");
  const { data: vehicles = [] } = useVehicles();
  const queue = useQuery({
    queryKey: ["packing-queue", warehouseId],
    queryFn: () => unwrap(api.GET("/shipping/queue", { params: { query: { warehouse_id: warehouseId } } })),
    enabled: !!warehouseId,
  });
  const shipments = useQuery({
    queryKey: ["shipments", warehouseId],
    queryFn: () => unwrap(api.GET("/shipping/shipments", { params: { query: { warehouse_id: warehouseId } } })),
    enabled: !!warehouseId,
  });
  const refresh = () => { invalidate(); queue.refetch(); shipments.refetch(); };
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/shipping/shipments", { body: { warehouse_id: warehouseId, vehicle_id: Number(vehicle), order_ids: selected } })),
    onSuccess: s => { toast.success(`محموله ${s.code} ساخته شد (${faNumber(s.weight_kg)} کیلوگرم).`); setSelected([]); refresh(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const dispatch = useMutation({
    mutationFn: (id: number) => unwrap(api.POST("/shipping/shipments/{shipment_id}/dispatch", { params: { path: { shipment_id: id } }, body: {} })),
    onSuccess: s => { toast.success(`محموله ${s.code} به راننده تحویل شد.`); refresh(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const cancel = useMutation({
    mutationFn: (id: number) => unwrap(api.POST("/shipping/shipments/{shipment_id}/cancel", { params: { path: { shipment_id: id } } })),
    onSuccess: () => { toast.success("محموله لغو شد."); refresh(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const packed = (queue.data ?? []).filter(o => o.fulfillment_state === "packed" && !o.shipment_id);

  return (
    <>
      <PageHeader eyebrow="انبار" title="بسته‌بندی و ارسال"
        subtitle="بسته‌بندی با ابعاد و وزن، برگه بسته‌بندی، و محموله با کنترل ظرفیت خودرو تا تحویل به راننده." />
      <div className="mb-4 w-64"><WarehousePicker choice={choice} /></div>
      <Card className="mb-5">
        <CardHeader title="سفارش‌های آماده بسته‌بندی و ارسال" icon={<PackageIcon className="size-4" />}
          subtitle="سفارش برداشت‌شده (یا بدون پیکینگ) را بسته‌بندی کنید؛ سفارش بسته‌بندی‌شده را برای محموله انتخاب کنید." />
        {queue.isLoading ? <TableSkeleton /> : queue.error ? <ErrorState error={queue.error} onRetry={queue.refetch} /> : !queue.data?.length ? (
          <EmptyState title="سفارش آماده‌ای نیست" />
        ) : (
          <Table testId="packing-queue">
            <thead><tr><th className="w-1" /><th>سفارش</th><th>آماده‌سازی</th><th>گیرنده</th><th>اقلام</th><th>بار بسته‌ها</th><th className="w-1" /></tr></thead>
            <tbody>
              {queue.data.map(o => (
                <tr key={o.id} data-testid="queue-row" data-code={o.tracking_code} data-state={o.fulfillment_state}>
                  <td>{o.fulfillment_state === "packed" && !o.shipment_id &&
                    <input type="checkbox" className="size-4 accent-[var(--brand)]" checked={selected.includes(o.id)} aria-label="انتخاب برای محموله"
                      onChange={() => setSelected(s => s.includes(o.id) ? s.filter(x => x !== o.id) : [...s, o.id])} data-testid="queue-select" />}</td>
                  <td className="whitespace-nowrap font-mono text-xs font-semibold ltr text-start">{o.tracking_code}</td>
                  <td><Badge tone={FULFILLMENT[o.fulfillment_state]?.tone ?? "muted"}>{o.fulfillment_label}</Badge>{o.shipment_id && <Badge className="ms-1">در محموله</Badge>}</td>
                  <td className="text-xs text-text-2">{o.recipient_name} · {o.destination_city}</td>
                  <td className="text-xs">{o.items.map(i => `${i.product_name} × ${faNumber(i.quantity)}`).join("، ")}</td>
                  <td className="whitespace-nowrap tnum text-xs">{o.packed_weight_kg ? `${faNumber(o.packed_weight_kg)} کیلو · ${faNumber(o.packed_volume_m3)} م³` : "—"}</td>
                  <td>
                    <div className="flex gap-1">
                      {!o.shipment_id && <Button size="sm" variant="soft" onClick={() => setPacking(o)} data-testid="queue-pack">{o.fulfillment_state === "packed" ? "بسته‌بندی دوباره" : "بسته‌بندی"}</Button>}
                      {o.fulfillment_state === "packed" && <Button size="icon" variant="ghost" aria-label="برگه بسته‌بندی" onClick={() => setSlipFor(o.id)} data-testid="queue-slip"><Printer className="size-4" /></Button>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {packed.length > 0 && (
          <div className="flex flex-wrap items-end gap-3 border-t border-border p-4">
            <Field label="خودرو" className="w-72">
              <Select value={vehicle} onChange={e => setVehicle(e.target.value)} data-testid="shipment-vehicle">
                <option value="">انتخاب خودرو...</option>
                {vehicles.filter(v => v.status !== "inactive" && v.status !== "maintenance").map(v => (
                  <option key={v.id} value={v.id}>{v.license_plate} — {faNumber(v.capacity_kg ?? 0)} کیلو</option>
                ))}
              </Select>
            </Field>
            <Button icon={<Truck className="size-4" />} disabled={!vehicle || !selected.length} loading={create.isPending} onClick={() => create.mutate()} data-testid="shipment-create">
              محموله با {faNumber(selected.length)} سفارش
            </Button>
          </div>
        )}
      </Card>
      <Card>
        <CardHeader title="محموله‌ها" icon={<Truck className="size-4" />} subtitle="ظرفیت وزنی و حجمی خودرو هنگام ساخت و تحویل دوباره کنترل می‌شود." />
        {!shipments.data?.length ? <EmptyState title="هنوز محموله‌ای نیست" /> : (
          <Table testId="shipments-table">
            <thead><tr><th>کد</th><th>وضعیت</th><th>خودرو / راننده</th><th>سفارش‌ها</th><th>بار</th><th>زمان</th><th className="w-1" /></tr></thead>
            <tbody>
              {shipments.data.map(s => (
                <tr key={s.id} data-testid="shipment-row" data-code={s.code} data-status={s.status}>
                  <td className="whitespace-nowrap font-mono text-xs font-semibold ltr text-start">{s.code}</td>
                  <td><Badge tone={SHIPMENT_STATUS[s.status]?.tone ?? "muted"} dot>{s.status_label}</Badge></td>
                  <td className="text-xs">{s.vehicle_plate ?? "—"}{s.driver_name ? ` · ${s.driver_name}` : ""}</td>
                  <td className="font-mono text-[11px] ltr text-start">{s.orders.map(o => o.tracking_code).join("، ")}</td>
                  <td className="whitespace-nowrap tnum text-xs">{faNumber(s.weight_kg)}{s.max_weight_kg ? ` / ${faNumber(s.max_weight_kg)}` : ""} کیلو
                    {s.max_volume_m3 ? ` · ${faNumber(s.volume_m3)} / ${faNumber(s.max_volume_m3)} م³` : ""}</td>
                  <td className="whitespace-nowrap text-xs text-text-2">{faDateTime(s.dispatched_at ?? s.created_at)}</td>
                  <td>{s.status === "open" && (
                    <div className="flex gap-1">
                      <Button size="sm" loading={dispatch.isPending && dispatch.variables === s.id} data-testid="shipment-dispatch"
                        onClick={() => confirmDialog({ title: `تحویل ${s.code} به راننده؟`, text: "حواله خروج همه سفارش‌ها صادر و وضعیتشان «بارگیری شد» می‌شود.", confirmLabel: "تحویل به راننده" })
                          .then(ok => ok && dispatch.mutate(s.id))}>تحویل به راننده</Button>
                      <Button size="sm" variant="ghost" onClick={() => cancel.mutate(s.id)}>لغو</Button>
                    </div>
                  )}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {packing && <PackModal order={packing} onClose={() => setPacking(null)} onDone={id => { refresh(); setSlipFor(id); }} />}
      <SlipModal orderId={slipFor} onClose={() => setSlipFor(null)} />
    </>
  );
}

type Box = { length: string; width: string; height: string; weight: string; items: Record<number, string> };

function PackModal({ order, onClose, onDone }: { order: QueueOrder; onClose: () => void; onDone: (id: number) => void }) {
  const toast = useToast();
  const [boxes, setBoxes] = useState<Box[]>([{ length: "40", width: "30", height: "30", weight: "",
    items: Object.fromEntries(order.items.map(i => [i.product_id, String(i.quantity)])) }]);
  const update = (i: number, patch: Partial<Box>) => setBoxes(bs => bs.map((b, j) => (j === i ? { ...b, ...patch } : b)));
  const totals = Object.fromEntries(order.items.map(i => [i.product_id, boxes.reduce((s, b) => s + (Number(b.items[i.product_id]) || 0), 0)]));
  const balanced = order.items.every(i => totals[i.product_id] === i.quantity);
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/shipping/orders/{order_id}/pack", { params: { path: { order_id: order.id } }, body: {
      packages: boxes.map(b => ({
        length_cm: Number(b.length), width_cm: Number(b.width), height_cm: Number(b.height), weight_kg: b.weight ? Number(b.weight) : null,
        items: order.items.filter(i => Number(b.items[i.product_id]) > 0).map(i => ({ product_id: i.product_id, quantity: Number(b.items[i.product_id]) })),
      })).filter(p => p.items.length) } })),
    onSuccess: () => { toast.success(`سفارش ${order.tracking_code} بسته‌بندی شد.`); onClose(); onDone(order.id); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <Modal open onClose={onClose} size="lg" title={`بسته‌بندی ${order.tracking_code}`} testId="pack-modal"
      description="ابعاد و وزن هر بسته؛ وزن خالی = وزن اقلام. مجموع اقلام بسته‌ها باید با سفارش برابر باشد."
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button>
        <Button type="submit" form="pack-form" loading={save.isPending} disabled={!balanced} data-testid="pack-save">ثبت بسته‌بندی</Button></>}>
      <form id="pack-form" className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        {boxes.map((b, i) => (
          <div key={i} className="space-y-3 rounded-xl border border-border p-3" data-testid="pack-box">
            <div className="flex items-center justify-between"><span className="text-sm font-semibold">بسته {faNumber(i + 1)}</span>
              <Button type="button" variant="ghost" size="icon" disabled={boxes.length === 1} onClick={() => setBoxes(boxes.filter((_, j) => j !== i))} aria-label="حذف بسته"><Trash2 className="size-4" /></Button></div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Field label="طول (س‌م)"><Input type="number" min={1} required value={b.length} onChange={e => update(i, { length: e.target.value })} /></Field>
              <Field label="عرض (س‌م)"><Input type="number" min={1} required value={b.width} onChange={e => update(i, { width: e.target.value })} /></Field>
              <Field label="ارتفاع (س‌م)"><Input type="number" min={1} required value={b.height} onChange={e => update(i, { height: e.target.value })} /></Field>
              <Field label="وزن (کیلو)"><Input type="number" min={0.01} step="0.01" placeholder="خودکار" value={b.weight} onChange={e => update(i, { weight: e.target.value })} /></Field>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {order.items.map(item => (
                <label key={item.product_id} className="flex items-center gap-2 text-sm">
                  <span className="flex-1 truncate">{item.product_name}</span>
                  <Input type="number" min={0} max={item.quantity} className="w-24" value={b.items[item.product_id] ?? ""}
                    onChange={e => update(i, { items: { ...b.items, [item.product_id]: e.target.value } })} data-testid="pack-qty" />
                </label>
              ))}
            </div>
          </div>
        ))}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Button type="button" size="sm" variant="soft" icon={<Plus className="size-4" />}
            onClick={() => setBoxes([...boxes, { length: "40", width: "30", height: "30", weight: "", items: {} }])}>بسته دیگر</Button>
          <span className={`text-xs ${balanced ? "text-success" : "text-danger"}`}>
            {order.items.map(i => `${i.product_name}: ${faNumber(totals[i.product_id])} از ${faNumber(i.quantity)}`).join(" · ")}
          </span>
        </div>
      </form>
    </Modal>
  );
}

function SlipModal({ orderId, onClose }: { orderId: number | null; onClose: () => void }) {
  const { data: slip } = useQuery({
    queryKey: ["packing-slip", orderId],
    queryFn: () => unwrap(api.GET("/shipping/orders/{order_id}/packing-slip", { params: { path: { order_id: orderId! } } })),
    enabled: orderId != null,
  });
  return (
    <Modal open={orderId != null} onClose={onClose} size="lg" testId="packing-slip" title={slip ? `برگه بسته‌بندی ${slip.tracking_code}` : "برگه بسته‌بندی"}
      footer={<Button icon={<Printer className="size-4" />} onClick={() => window.print()}>چاپ</Button>}>
      {!slip ? <div className="h-32 animate-pulse rounded-xl bg-surface-2" /> : <SlipBody slip={slip} />}
    </Modal>
  );
}

function SlipBody({ slip }: { slip: Slip }) {
  return (
    <div className="space-y-4 text-sm">
      <div className="grid gap-2 sm:grid-cols-2">
        <div><span className="text-muted">گیرنده: </span>{slip.recipient_name} — <span className="ltr">{slip.recipient_mobile}</span></div>
        <div><span className="text-muted">مقصد: </span>{slip.destination}</div>
        <div><span className="text-muted">جمع: </span>{faNumber(slip.packages.length)} بسته · {faNumber(slip.total_weight_kg)} کیلو · {faNumber(slip.total_volume_m3)} م³</div>
      </div>
      {slip.packages.map(p => (
        <div key={p.id} className="rounded-xl border border-border p-3" data-testid="slip-package">
          <div className="mb-2 flex flex-wrap justify-between gap-2 font-semibold"><span className="font-mono ltr">{p.code}</span>
            <span className="text-xs font-normal text-muted">{faNumber(p.length_cm)}×{faNumber(p.width_cm)}×{faNumber(p.height_cm)} س‌م · {faNumber(p.weight_kg)} کیلو</span></div>
          <ul className="space-y-1">{p.items.map(i => <li key={i.product_id} className="flex justify-between"><span>{i.product_name} <span className="font-mono text-xs text-muted">{i.product_sku}</span></span><span className="tnum">× {faNumber(i.quantity)}</span></li>)}</ul>
        </div>
      ))}
    </div>
  );
}
