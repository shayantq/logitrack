/**
 * پیکینگ (فصل ۱۴): فهرست برداشت تک‌سفارشی، دسته‌ای، موجی (روز تحویل) یا منطقه‌ای؛ سطرها به ترتیب FEFO و مسیر محل‌ها.
 * برداشت هر سطر با اسکن محل، کالا و بچ تأیید و کالا به محل آماده‌سازی منتقل می‌شود؛ کمبود محل «کسری» و
 * باقی‌مانده از محل دیگر برنامه‌ریزی می‌شود.
 */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, ListChecks, Plus, ScanLine, X } from "lucide-react";
import { api, errorMessage, newIdempotencyKey, unwrap, type Schemas } from "@/api/client";
import { useToast } from "@/components/Toast";
import { PICK_LIST_STATUS, PICK_STRATEGIES } from "@/lib/labels";
import { faDate, faNumber } from "@/lib/format";
import { DateField } from "@/ui/datetime";
import { promptDialog } from "@/ui/dialogs";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, SegmentedControl, Select, Table, TableSkeleton, cn } from "@/ui/primitives";
import { LocationSelect, WarehousePicker, scanKeyDown, useInvalidateOperations, useLocations, useWarehouseChoice } from "./shared";

type Line = Schemas["PickLineOut"];
type Strategy = Schemas["PickListCreate"]["strategy"];

export default function PickingPage() {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const choice = useWarehouseChoice();
  const warehouseId = choice.value ? Number(choice.value) : null;
  const [status, setStatus] = useState<"active" | "picked" | "canceled">("active");
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const { data: lists, isLoading, error, refetch } = useQuery({
    queryKey: ["pick-lists", warehouseId, status],
    queryFn: () => unwrap(api.GET("/picking/lists", { params: { query: { warehouse_id: warehouseId, status } } })),
    enabled: !!warehouseId,
  });
  const cancel = useMutation({
    mutationFn: (args: { id: number; reason: string }) => unwrap(api.POST("/picking/lists/{pick_list_id}/cancel", {
      params: { path: { pick_list_id: args.id } }, body: { reason: args.reason } })),
    onSuccess: () => { toast.success("فهرست برداشت لغو شد."); invalidate(); },
    onError: e => toast.error(errorMessage(e)),
  });

  return (
    <>
      <PageHeader eyebrow="انبار" title="پیکینگ"
        subtitle="برداشت سفارش‌ها از قفسه با مسیر محل‌ها و اول‌منقضی، اول‌خروج — هر برداشت با اسکن محل، کالا و بچ."
        actions={<Button icon={<Plus className="size-4" />} disabled={!warehouseId} onClick={() => setCreating(true)} data-testid="pick-new">فهرست برداشت</Button>} />
      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-border p-4">
          <div className="w-64"><WarehousePicker choice={choice} /></div>
          <SegmentedControl value={status} onChange={setStatus} options={[
            { value: "active", label: "باز" }, { value: "picked", label: "برداشت‌شده" }, { value: "canceled", label: "لغوشده" }]} />
        </div>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : !lists?.length ? (
          <EmptyState icon={<ListChecks className="size-5" />} title="فهرست برداشتی نیست"
            text="از سفارش‌های رزروشده یک فهرست برداشت بسازید." />
        ) : (
          <Table testId="pick-lists-table">
            <thead><tr><th>کد</th><th>روش</th><th>وضعیت</th><th>سفارش‌ها</th><th>پیشرفت</th><th>آماده‌سازی</th><th className="w-1" /></tr></thead>
            <tbody>
              {lists.map(pl => (
                <tr key={pl.id} className="cursor-pointer hover:bg-surface-2" onClick={() => setOpenId(pl.id)} data-testid="pick-list-row" data-code={pl.code} data-status={pl.status}>
                  <td className="whitespace-nowrap font-mono text-xs font-semibold ltr text-start">{pl.code}</td>
                  <td className="text-xs">{pl.strategy_label}{pl.zone_code ? ` · ${pl.zone_code}` : ""}{pl.wave_date ? ` · ${faDate(pl.wave_date)}` : ""}</td>
                  <td><Badge tone={PICK_LIST_STATUS[pl.status]?.tone ?? "muted"} dot>{pl.status_label}</Badge></td>
                  <td className="max-w-56 font-mono text-[11px] ltr text-start">{pl.orders.join("، ")}</td>
                  <td className="whitespace-nowrap tnum">{faNumber(pl.picked_quantity)} / {faNumber(pl.total_quantity)}</td>
                  <td className="font-mono text-xs ltr text-start">{pl.staging_code ?? "—"}</td>
                  <td onClick={e => e.stopPropagation()}>
                    {pl.status === "open" && <Button size="sm" variant="ghost" icon={<X className="size-3.5" />}
                      onClick={() => promptDialog({ title: `لغو ${pl.code}`, label: "دلیل", required: true, minLength: 3, maxLength: 300, danger: true })
                        .then(reason => reason && cancel.mutate({ id: pl.id, reason }))}>لغو</Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {creating && warehouseId && <NewPickListModal warehouseId={warehouseId} onClose={() => setCreating(false)} onCreated={setOpenId} />}
      <PickListModal id={openId} onClose={() => setOpenId(null)} />
    </>
  );
}

function NewPickListModal({ warehouseId, onClose, onCreated }: { warehouseId: number; onClose: () => void; onCreated: (id: number) => void }) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const { data: candidates = [] } = useQuery({
    queryKey: ["pick-candidates", warehouseId],
    queryFn: () => unwrap(api.GET("/picking/candidates", { params: { query: { warehouse_id: warehouseId } } })),
  });
  const { data: locations = [] } = useLocations(warehouseId);
  const zones = locations.filter(l => !l.is_leaf);
  const [strategy, setStrategy] = useState<Strategy>("single");
  const [selected, setSelected] = useState<number[]>([]);
  const [wave, setWave] = useState("");
  const [zone, setZone] = useState("");
  const [staging, setStaging] = useState("");
  const toggle = (id: number) => setSelected(s => strategy === "single" ? [id] : s.includes(id) ? s.filter(x => x !== id) : [...s, id]);
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/picking/lists", { body: {
      warehouse_id: warehouseId, strategy, order_ids: strategy === "single" || strategy === "batch" ? selected : null,
      wave_date: strategy === "wave" ? wave || null : null, zone_location_id: strategy === "zone" && zone ? Number(zone) : null,
      staging_location_id: staging ? Number(staging) : null,
    } })),
    onSuccess: pl => {
      toast.success(`فهرست ${pl.code} با ${faNumber(pl.lines.length)} سطر ساخته شد.` + (pl.skipped_orders?.length ? ` (${pl.skipped_orders.length} سفارش موجودی قابل برداشت نداشت)` : ""));
      invalidate(); onClose(); onCreated(pl.id);
    },
    onError: e => toast.error(errorMessage(e)),
  });
  const needsOrders = strategy === "single" || strategy === "batch";
  return (
    <Modal open onClose={onClose} size="lg" title="فهرست برداشت جدید" testId="pick-new-modal"
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button>
        <Button type="submit" form="pick-form" loading={save.isPending} disabled={needsOrders && !selected.length} data-testid="pick-create">ساخت فهرست</Button></>}>
      <form id="pick-form" className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" role="radiogroup" data-testid="pick-strategy">
          {Object.entries(PICK_STRATEGIES).map(([k, v]) => (
            <button key={k} type="button" role="radio" aria-checked={strategy === k} data-strategy={k}
              onClick={() => { setStrategy(k as Strategy); setSelected([]); }}
              className={cn("rounded-xl border p-3 text-start transition", strategy === k ? "border-brand bg-brand-soft" : "border-border hover:bg-surface-2")}>
              <div className="text-sm font-semibold">{v.label}</div><div className="mt-0.5 text-[11px] leading-4 text-muted">{v.hint}</div>
            </button>
          ))}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          {strategy === "wave" && <Field label="روز تحویل"><DateField required value={wave} onChange={setWave} testId="pick-wave" /></Field>}
          {strategy === "zone" && (
            <Field label="منطقه">
              <Select required value={zone} onChange={e => setZone(e.target.value)} data-testid="pick-zone">
                <option value="">انتخاب کنید...</option>{zones.map(z => <option key={z.id} value={z.id}>{z.code} ({z.level_label})</option>)}
              </Select>
            </Field>
          )}
          <Field label="محل آماده‌سازی" hint="کالای برداشت‌شده به اینجا منتقل می‌شود (اختیاری)">
            <LocationSelect warehouseId={warehouseId} value={staging} onChange={setStaging} types={["staging", "shipping"]} empty="بدون انتقال" testId="pick-staging" />
          </Field>
        </div>
        {needsOrders && (
          <div className="max-h-72 overflow-y-auto rounded-xl border border-border" data-testid="pick-candidates">
            {!candidates.length ? <p className="p-4 text-sm text-muted">سفارش رزروشده‌ای که هنوز برداشت نشده باشد نیست.</p> : candidates.map(c => (
              <label key={c.id} className="flex cursor-pointer items-center gap-3 border-b border-border px-3 py-2 last:border-0 hover:bg-surface-2" data-testid="pick-candidate" data-id={c.id}>
                <input type={strategy === "single" ? "radio" : "checkbox"} className="size-4 accent-[var(--brand)]" checked={selected.includes(c.id)} onChange={() => toggle(c.id)} />
                <span className="font-mono text-xs font-semibold ltr">{c.tracking_code}</span>
                {c.priority && <Badge tone="danger">فوری</Badge>}
                <span className="text-xs text-text-2">{c.recipient_name} · {c.destination_city} · {faDate(c.delivery_day)}</span>
                <span className="ms-auto tnum text-xs">{faNumber(c.items)} عدد</span>
              </label>
            ))}
          </div>
        )}
      </form>
    </Modal>
  );
}

function PickListModal({ id, onClose }: { id: number | null; onClose: () => void }) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const [active, setActive] = useState<Line | null>(null);
  const { data: pl } = useQuery({
    queryKey: ["pick-list", id],
    queryFn: () => unwrap(api.GET("/picking/lists/{pick_list_id}", { params: { path: { pick_list_id: id! } } })),
    enabled: id != null,
  });
  const short = useMutation({
    mutationFn: (args: { line: Line; reason: string }) => unwrap(api.POST("/picking/lines/{line_id}/short", {
      params: { path: { line_id: args.line.id } }, body: { reason: args.reason } })),
    onSuccess: r => { toast.success(`کسری ثبت شد؛ ${faNumber(r.replanned ?? 0)} عدد از محل دیگر برنامه‌ریزی شد.`); invalidate(); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <>
      <Modal open={id != null} onClose={onClose} size="xl" testId="pick-list-detail"
        title={pl ? <span className="flex items-center gap-2"><span className="font-mono ltr">{pl.code}</span><Badge tone={PICK_LIST_STATUS[pl.status]?.tone ?? "muted"} dot>{pl.status_label}</Badge></span> : "فهرست برداشت"}
        description={pl && `${pl.strategy_label} · ${faNumber(pl.picked_quantity)} از ${faNumber(pl.total_quantity)} عدد${pl.staging_code ? ` · آماده‌سازی ${pl.staging_code}` : ""}`}>
        {!pl ? <div className="h-40 animate-pulse rounded-xl bg-surface-2" /> : (
          <div className="overflow-x-auto">
            <table className="table-base" data-testid="pick-lines">
              <thead><tr><th>#</th><th>محل</th><th>کالا</th><th>بچ / انقضا</th><th>سفارش</th><th>مقدار</th><th className="w-1" /></tr></thead>
              <tbody>
                {pl.lines.map(line => (
                  <tr key={line.id} data-testid="pick-line" data-status={line.status} className={cn(line.status !== "open" && "opacity-60")}>
                    <td className="tnum text-xs text-muted">{faNumber(line.sequence)}</td>
                    <td className="whitespace-nowrap font-mono text-sm font-bold ltr text-start">{line.location_code ?? "بدون محل"}</td>
                    <td className="min-w-40"><div className="font-medium">{line.product_name}</div><div className="font-mono text-xs text-muted">{line.product_sku}</div></td>
                    <td className="font-mono text-xs ltr text-start">{line.lot_number ?? "—"}{line.expiry_date ? ` · ${faDate(line.expiry_date)}` : ""}</td>
                    <td className="whitespace-nowrap font-mono text-xs ltr text-start">{line.order_tracking_code}</td>
                    <td className="whitespace-nowrap tnum">{faNumber(line.picked_quantity)} / {faNumber(line.quantity)}
                      {line.status === "short" && <Badge tone="danger" className="ms-1">کسری</Badge>}</td>
                    <td>
                      {line.status === "open" && (
                        <div className="flex gap-1">
                          <Button size="sm" icon={<ScanLine className="size-3.5" />} onClick={() => setActive(line)} data-testid="pick-line-scan">برداشت</Button>
                          <Button size="icon" variant="ghost" aria-label="کسری" data-testid="pick-line-short"
                            onClick={() => promptDialog({ title: "کمبود در محل", label: "شرح (مثلاً قفسه خالی بود)", required: true, minLength: 3, maxLength: 300 })
                              .then(reason => reason && short.mutate({ line, reason }))}><AlertTriangle className="size-4" /></Button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Modal>
      <PickScanModal line={active} warehouseCode={pl?.warehouse_code ?? ""} onClose={() => setActive(null)} />
    </>
  );
}

function PickScanModal({ line, warehouseCode, onClose }: { line: Line | null; warehouseCode: string; onClose: () => void }) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const [scans, setScans] = useState({ source: "", product: "", lot: "", quantity: "" });
  const [key, setKey] = useState(newIdempotencyKey);
  const refs = { source: useRef<HTMLInputElement>(null), product: useRef<HTMLInputElement>(null), lot: useRef<HTMLInputElement>(null),
    quantity: useRef<HTMLInputElement>(null) };
  useEffect(() => {
    if (line) {
      setScans({ source: "", product: "", lot: "", quantity: String(line.quantity - line.picked_quantity) });
      setTimeout(() => refs.source.current?.focus(), 50);
    }
  }, [line?.id]);
  const set = (k: keyof typeof scans) => (e: { target: { value: string } }) => setScans(s => ({ ...s, [k]: e.target.value }));
  const run = useMutation({
    mutationFn: () => unwrap(api.POST("/picking/lines/{line_id}/pick", {
      params: { path: { line_id: line!.id }, header: { "Idempotency-Key": key } },
      body: { source_scan: scans.source, product_scan: scans.product, lot_scan: scans.lot || null, quantity: Number(scans.quantity) } })),
    onSuccess: () => { toast.success("برداشت ثبت شد."); invalidate(); setKey(newIdempotencyKey()); onClose(); },
    onError: e => { toast.error(errorMessage(e)); setKey(newIdempotencyKey()); },
  });
  if (!line) return null;
  return (
    <Modal open onClose={onClose} title={`برداشت از ${line.location_code ?? "بدون محل"}`} testId="pick-scan-modal"
      description={`${line.product_name} (${line.product_sku}) — سفارش ${line.order_tracking_code}`}
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="pick-scan-form" loading={run.isPending} data-testid="pick-confirm">تأیید برداشت</Button></>}>
      <form id="pick-scan-form" className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); run.mutate(); }}>
        <Field label="۱. اسکن محل" hint={line.location_code ? `محل ${line.location_code}` : `بدون محل: کد انبار (${warehouseCode})`}>
          <Input ref={refs.source} required className="ltr font-mono" autoComplete="off" value={scans.source} onChange={set("source")}
            onKeyDown={scanKeyDown(() => refs.product.current?.focus())} data-testid="pick-scan-source" />
        </Field>
        <Field label="۲. اسکن کالا" hint={line.product_barcode ?? line.product_sku}>
          <Input ref={refs.product} required className="ltr font-mono" autoComplete="off" value={scans.product} onChange={set("product")}
            onKeyDown={scanKeyDown(() => (line.lot_number ? refs.lot : refs.quantity).current?.focus())} data-testid="pick-scan-product" />
        </Field>
        {line.lot_number && (
          <Field label="اسکن بچ" hint={`اول‌منقضی: بچ ${line.lot_number}`}>
            <Input ref={refs.lot} required className="ltr font-mono" autoComplete="off" value={scans.lot} onChange={set("lot")}
              onKeyDown={scanKeyDown(() => refs.quantity.current?.focus())} />
          </Field>
        )}
        <Field label="۳. تعداد" hint={`حداکثر ${faNumber(line.quantity - line.picked_quantity)}`}>
          <Input ref={refs.quantity} type="number" min={1} max={line.quantity - line.picked_quantity} required value={scans.quantity} onChange={set("quantity")} data-testid="pick-scan-qty" />
        </Field>
      </form>
    </Modal>
  );
}
