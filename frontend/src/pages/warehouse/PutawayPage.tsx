/**
 * جانمایی (فصل ۹): وظایف بردن کالا از محل تخلیه به محل نگهداری با مقصد پیشنهادی سیستم (ظرفیت و قاعده اختلاط).
 * اجرا فقط با اسکن کالا، محل مبدأ و محل مقصد؛ بارکدخوان مثل صفحه‌کلید عمل می‌کند و Enter به ورودی بعدی می‌رود.
 * اسکن اشتباه یا نقض ظرفیت رد و در شمارنده خطای وظیفه ثبت می‌شود؛ مقصد پر/مسدود با «گزارش مشکل» کنار می‌رود.
 */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeftRight, MapPin, Plus, RefreshCw, ScanLine, X } from "lucide-react";
import { api, errorMessage, isServerError, newIdempotencyKey, unwrap, type Schemas } from "@/api/client";
import { useToast } from "@/components/Toast";
import { useProducts } from "@/hooks/data";
import { PUTAWAY_PROBLEMS, PUTAWAY_STATUS, STOCK_STATUS, type StockStatus } from "@/lib/labels";
import { faDate, faNumber } from "@/lib/format";
import { promptDialog } from "@/ui/dialogs";
import { Menu, MenuItem, Modal, Tooltip } from "@/ui/overlays";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, SegmentedControl, Select, Table, TableSkeleton } from "@/ui/primitives";
import { LocationSelect, STATUS_KEYS, StatusBadge, WarehousePicker, scanKeyDown, useInvalidateOperations, useWarehouseChoice } from "./shared";

type Task = Schemas["PutawayTaskOut"];

export default function PutawayPage() {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const choice = useWarehouseChoice();
  const [status, setStatus] = useState<"active" | "done" | "canceled">("active");
  const [executing, setExecuting] = useState<Task | null>(null);
  const [creating, setCreating] = useState(false);
  const [moving, setMoving] = useState(false);
  const warehouseId = choice.value ? Number(choice.value) : null;
  const { data: tasks, isLoading, error, refetch } = useQuery({
    queryKey: ["putaway-tasks", status, warehouseId],
    queryFn: () => unwrap(api.GET("/putaway/tasks", { params: { query: { status, warehouse_id: warehouseId } } })),
    enabled: !!warehouseId,
  });
  const problem = useMutation({
    mutationFn: (args: { task: Task; problem: string; note?: string }) => unwrap(api.POST("/putaway/tasks/{task_id}/problem", {
      params: { path: { task_id: args.task.id } }, body: { problem: args.problem as never, note: args.note || null } })),
    onSuccess: t => { toast.success(t.status === "canceled" ? "وظیفه بسته شد." : `مقصد جدید: ${t.suggested_location_code ?? "—"}`); invalidate(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const cancel = useMutation({
    mutationFn: (args: { task: Task; reason: string }) => unwrap(api.POST("/putaway/tasks/{task_id}/cancel", {
      params: { path: { task_id: args.task.id } }, body: { reason: args.reason } })),
    onSuccess: () => { toast.success("وظیفه لغو شد."); invalidate(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const resuggest = useMutation({
    mutationFn: (task: Task) => unwrap(api.POST("/putaway/tasks/{task_id}/suggest", { params: { path: { task_id: task.id } } })),
    onSuccess: t => { toast.success(t.suggested_location_code ? `مقصد پیشنهادی: ${t.suggested_location_code}` : "محل مناسبی پیدا نشد."); invalidate(); },
    onError: e => toast.error(errorMessage(e)),
  });
  async function report(task: Task, code: string) {
    const note = await promptDialog({ title: PUTAWAY_PROBLEMS[code], label: "توضیح (اختیاری)", maxLength: 200, confirmLabel: "ثبت مشکل" });
    if (note !== null) problem.mutate({ task, problem: code, note });
  }

  return (
    <>
      <PageHeader eyebrow="انبار" title="جانمایی"
        subtitle="از محل تخلیه تا قفسه: مقصد پیشنهادی بر اساس ظرفیت و قاعده اختلاط محل‌ها؛ اجرا فقط با اسکن کالا، مبدأ و مقصد."
        actions={<>
          <Button variant="secondary" icon={<ArrowLeftRight className="size-4" />} disabled={!warehouseId} onClick={() => setMoving(true)} data-testid="location-move-open">جابه‌جایی دستی</Button>
          <Button icon={<Plus className="size-4" />} disabled={!warehouseId} onClick={() => setCreating(true)} data-testid="putaway-new">وظیفه جدید</Button>
        </>} />
      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-border p-4">
          <div className="w-64"><WarehousePicker choice={choice} /></div>
          <SegmentedControl value={status} onChange={setStatus} options={[
            { value: "active", label: "باز" }, { value: "done", label: "انجام‌شده" }, { value: "canceled", label: "لغوشده" }]} />
        </div>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : !tasks?.length ? (
          <EmptyState icon={<MapPin className="size-5" />} title={status === "active" ? "وظیفه جانمایی بازی نیست" : "موردی نیست"}
            text={status === "active" ? "پس از دریافت رسید یا بازرسی، برای کالای محل تخلیه خودکار وظیفه ساخته می‌شود." : undefined} />
        ) : (
          <Table testId="putaway-table">
            <thead><tr><th>وظیفه</th><th>کالا</th><th>وضعیت کیفی</th><th>مقدار</th><th>از</th><th>به (پیشنهاد)</th><th>خطا</th><th className="w-1" /></tr></thead>
            <tbody>
              {tasks.map(t => (
                <tr key={t.id} data-testid="putaway-row" data-code={t.code} data-status={t.status}>
                  <td className="whitespace-nowrap"><div className="font-mono text-xs font-semibold ltr text-start">{t.code}</div><Badge tone={PUTAWAY_STATUS[t.status]?.tone ?? "muted"}>{PUTAWAY_STATUS[t.status]?.label}</Badge>{t.task_type === "replenishment" && <Badge tone="brand" className="ms-1">تأمین مجدد</Badge>}</td>
                  <td className="min-w-40"><div className="font-medium">{t.product_name}</div><div className="font-mono text-xs text-muted">{t.product_sku}{t.lot_number ? ` · بچ ${t.lot_number}` : ""}{t.expiry_date ? ` · ${faDate(t.expiry_date)}` : ""}</div></td>
                  <td><StatusBadge status={t.stock_status} /></td>
                  <td className="whitespace-nowrap tnum">{faNumber(t.quantity_done)} / {faNumber(t.quantity)}</td>
                  <td className="font-mono text-xs ltr text-start">{t.source_location_code ?? "بدون محل"}</td>
                  <td className="font-mono text-xs ltr text-start" data-testid="putaway-suggested">{t.status === "done" ? t.destination_location_code : t.suggested_location_code ?? <span className="text-warning">بدون پیشنهاد</span>}</td>
                  <td className="text-xs">{t.failure_count ? <Tooltip content={t.last_error ?? ""}><Badge tone="danger"><AlertTriangle className="size-3" />{faNumber(t.failure_count)} · {PUTAWAY_PROBLEMS[t.last_problem ?? ""] ?? ""}</Badge></Tooltip> : "—"}</td>
                  <td>
                    {(t.status === "open" || t.status === "partial") && (
                      <div className="flex gap-1">
                        <Button size="sm" icon={<ScanLine className="size-3.5" />} onClick={() => setExecuting(t)} data-testid="putaway-execute">اجرا</Button>
                        <Menu trigger={<Button size="icon" variant="ghost" aria-label="بیشتر" data-testid="putaway-more"><AlertTriangle className="size-4" /></Button>}>
                          <MenuItem icon={<RefreshCw className="size-4" />} onSelect={() => resuggest.mutate(t)}>پیشنهاد دوباره مقصد</MenuItem>
                          {(["destination_full", "destination_blocked", "item_damaged", "item_missing"] as const).map(code => (
                            <MenuItem key={code} icon={<AlertTriangle className="size-4" />} onSelect={() => report(t, code)}>{PUTAWAY_PROBLEMS[code]}</MenuItem>
                          ))}
                          <MenuItem danger icon={<X className="size-4" />} onSelect={() => promptDialog({ title: `لغو ${t.code}`, label: "دلیل", required: true, minLength: 3, maxLength: 300, danger: true })
                            .then(reason => reason && cancel.mutate({ task: t, reason }))}>لغو وظیفه</MenuItem>
                        </Menu>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <ExecuteModal task={executing} onClose={() => setExecuting(null)} />
      {creating && warehouseId && <NewTaskModal warehouseId={warehouseId} onClose={() => setCreating(false)} />}
      {moving && warehouseId && <MoveModal warehouseId={warehouseId} onClose={() => setMoving(false)} />}
    </>
  );
}

function ExecuteModal({ task, onClose }: { task: Task | null; onClose: () => void }) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const [scans, setScans] = useState({ product: "", source: "", lot: "", destination: "", quantity: "" });
  const [key, setKey] = useState(newIdempotencyKey);
  const refs = { product: useRef<HTMLInputElement>(null), source: useRef<HTMLInputElement>(null), lot: useRef<HTMLInputElement>(null),
    destination: useRef<HTMLInputElement>(null), quantity: useRef<HTMLInputElement>(null) };
  useEffect(() => {
    if (task) {
      setScans({ product: "", source: "", lot: "", destination: "", quantity: String(task.remaining) });
      // اسکنر بارکد سریع است: اگر کاربر در همین فاصله به فیلد بعدی رفته، فوکوس از زیر دستش کشیده نشود
      setTimeout(() => {
        const moved = [refs.source, refs.lot, refs.destination, refs.quantity].some(r => r.current && r.current === document.activeElement);
        if (!moved) refs.product.current?.focus();
      }, 50);
    }
  }, [task?.id]);
  const set = (k: keyof typeof scans) => (e: { target: { value: string } }) => setScans(s => ({ ...s, [k]: e.target.value }));
  // مقصدهای برتر با دلیل (تجمیع، محل خالی، نزدیکی مسیر بر اساس ABC)
  const options = useQuery({
    queryKey: ["putaway-suggestions", task?.id, task?.suggested_location_code], enabled: !!task,
    queryFn: () => unwrap(api.GET("/putaway/tasks/{task_id}/suggestions", { params: { path: { task_id: task!.id } } })),
  });
  const run = useMutation({
    mutationFn: () => unwrap(api.POST("/putaway/tasks/{task_id}/execute", {
      params: { path: { task_id: task!.id }, header: { "Idempotency-Key": key } },
      body: { product_scan: scans.product, source_scan: scans.source, destination_scan: scans.destination,
        lot_scan: scans.lot || null, quantity: Number(scans.quantity) },
    })),
    onSuccess: t => {
      toast.success(t.status === "done" ? `جانمایی ${t.code} انجام شد (${t.destination_location_code}).` : `${faNumber(t.remaining)} عدد از ${t.code} باقی مانده است.`);
      invalidate(); setKey(newIdempotencyKey()); onClose();
    },
    // خطای اسکن/قاعده در شمارنده خطای وظیفه ثبت شده است؛ تلاش بعدی درخواست تازه است
    onError: e => { toast.error(errorMessage(e)); setKey(newIdempotencyKey()); invalidate(); },
  });
  if (!task) return null;
  const sourceHint = task.source_location_code ? `محل ${task.source_location_code}` : `کالا بدون محل است؛ کد انبار (${task.warehouse_code}) را اسکن کنید`;
  return (
    <Modal open onClose={onClose} title={`اجرای جانمایی ${task.code}`} testId="putaway-modal"
      description={`${task.product_name} (${task.product_sku}) — ${faNumber(task.remaining)} عدد «${STOCK_STATUS[task.stock_status as StockStatus]?.label ?? task.stock_status}»`}
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="putaway-form" loading={run.isPending} data-testid="putaway-confirm">تأیید جانمایی</Button></>}>
      <form id="putaway-form" className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); run.mutate(); }}>
        <div className="flex items-center gap-3 rounded-xl bg-brand-soft/60 p-3 text-sm">
          <MapPin className="size-5 shrink-0 text-brand" />
          <div>مقصد پیشنهادی: <span className="font-mono text-base font-bold ltr" data-testid="putaway-target">{task.suggested_location_code ?? "—"}</span>
            {!task.suggested_location_code && <div className="text-xs text-warning">محل مناسبی پیدا نشد؛ یک محل نگهداری با ظرفیت آزاد را اسکن کنید.</div>}
            {options.data?.[0] && <div className="text-xs text-text-2" data-testid="putaway-reason">چرا: {options.data[0].reason}</div>}</div>
        </div>
        {(options.data?.length ?? 0) > 1 && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs" data-testid="putaway-alternatives">
            <span className="text-muted">جایگزین‌ها:</span>
            {options.data!.slice(1).map(o => (
              <Tooltip key={o.location_id} content={o.reason}>
                <button type="button" className="rounded-lg border border-border px-2 py-1 font-mono transition hover:border-brand"
                  onClick={() => setScans(s => ({ ...s, destination: o.barcode }))}>{o.code}</button>
              </Tooltip>
            ))}
          </div>
        )}
        <Field label="۱. اسکن کالا" hint={`SKU، بارکد کالا یا بارکد کارتن — ${task.product_barcode ?? task.product_sku}`}>
          <Input ref={refs.product} required className="ltr font-mono" autoComplete="off" value={scans.product} onChange={set("product")}
            onKeyDown={scanKeyDown(() => refs.source.current?.focus())} data-testid="scan-product" />
        </Field>
        <Field label="۲. اسکن محل مبدأ" hint={sourceHint}>
          <Input ref={refs.source} required className="ltr font-mono" autoComplete="off" value={scans.source} onChange={set("source")}
            onKeyDown={scanKeyDown(() => (task.lot_number ? refs.lot : refs.destination).current?.focus())} data-testid="scan-source" />
        </Field>
        {task.lot_number && (
          <Field label="اسکن بچ" hint={`بچ ${task.lot_number}`}>
            <Input ref={refs.lot} required className="ltr font-mono" autoComplete="off" value={scans.lot} onChange={set("lot")}
              onKeyDown={scanKeyDown(() => refs.destination.current?.focus())} data-testid="scan-lot" />
          </Field>
        )}
        <Field label="۳. اسکن محل مقصد" hint="می‌تواند غیر از پیشنهاد باشد اگر جا داشته باشد">
          <Input ref={refs.destination} required className="ltr font-mono" autoComplete="off" value={scans.destination} onChange={set("destination")}
            onKeyDown={scanKeyDown(() => refs.quantity.current?.focus())} data-testid="scan-destination" />
        </Field>
        <Field label="تعداد" hint={`حداکثر ${faNumber(task.remaining)} — اجرای ناقص مجاز است`}>
          <Input ref={refs.quantity} type="number" min={1} max={task.remaining} required value={scans.quantity} onChange={set("quantity")} data-testid="scan-qty" />
        </Field>
      </form>
    </Modal>
  );
}

function NewTaskModal({ warehouseId, onClose }: { warehouseId: number; onClose: () => void }) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const { data: products = [] } = useProducts();
  const [form, setForm] = useState({ product: "", quantity: "1", status: "available", source: "", lot: "" });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm(f => ({ ...f, [k]: e.target.value }));
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/putaway/tasks", { body: {
      warehouse_id: warehouseId, product_id: Number(form.product), quantity: Number(form.quantity), stock_status: form.status as StockStatus,
      source_location_id: form.source ? Number(form.source) : null, lot_number: form.lot || null } })),
    onSuccess: t => { toast.success(`وظیفه ${t.code} ساخته شد${t.suggested_location_code ? ` — مقصد ${t.suggested_location_code}` : ""}.`); invalidate(); onClose(); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <Modal open onClose={onClose} title="وظیفه جانمایی دستی" testId="putaway-new-modal"
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="task-form" loading={save.isPending}>ساخت وظیفه</Button></>}>
      <form id="task-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        <Field label="کالا" className="sm:col-span-2">
          <Select required value={form.product} onChange={set("product")} searchable>
            <option value="">انتخاب کالا...</option>{products.map(p => <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>)}
          </Select>
        </Field>
        <Field label="محل مبدأ"><LocationSelect warehouseId={warehouseId} value={form.source} onChange={v => setForm(f => ({ ...f, source: v }))} /></Field>
        <Field label="وضعیت کیفی"><Select value={form.status} onChange={set("status")}>{STATUS_KEYS.filter(s => s !== "pending").map(s => <option key={s} value={s}>{STOCK_STATUS[s].label}</option>)}</Select></Field>
        <Field label="تعداد"><Input type="number" min={1} required value={form.quantity} onChange={set("quantity")} /></Field>
        <Field label="بچ" hint="اختیاری"><Input className="ltr uppercase" value={form.lot} onChange={set("lot")} /></Field>
      </form>
    </Modal>
  );
}

function MoveModal({ warehouseId, onClose }: { warehouseId: number; onClose: () => void }) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const { data: products = [] } = useProducts();
  const [form, setForm] = useState({ product: "", from: "", to: "", quantity: "1", status: "available", lot: "", reason: "" });
  const [key, setKey] = useState(newIdempotencyKey);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm(f => ({ ...f, [k]: e.target.value }));
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/inventory/location-moves", { params: { header: { "Idempotency-Key": key } }, body: {
      warehouse_id: warehouseId, product_id: Number(form.product), from_location_id: form.from ? Number(form.from) : null,
      to_location_id: Number(form.to), quantity: Number(form.quantity), stock_status: form.status as StockStatus,
      lot_number: form.lot || null, reason: form.reason || null } })),
    onSuccess: d => { toast.success(`سند جابه‌جایی ${d.code} ثبت شد.`); invalidate(); onClose(); },
    onError: e => { toast.error(errorMessage(e)); if (isServerError(e)) setKey(newIdempotencyKey()); },
  });
  return (
    <Modal open onClose={onClose} title="جابه‌جایی بین محل‌ها" testId="location-move-modal"
      description="سند «جابه‌جایی بین محل‌ها» (MV) با کنترل ظرفیت و قاعده اختلاط مقصد؛ وضعیت کیفی و بچ عوض نمی‌شود."
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="move-form" loading={save.isPending} data-testid="location-move-save">ثبت جابه‌جایی</Button></>}>
      <form id="move-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        <Field label="کالا" className="sm:col-span-2">
          <Select required value={form.product} onChange={set("product")} searchable data-testid="move-product">
            <option value="">انتخاب کالا...</option>{products.map(p => <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>)}
          </Select>
        </Field>
        <Field label="از محل"><LocationSelect warehouseId={warehouseId} value={form.from} onChange={v => setForm(f => ({ ...f, from: v }))} testId="move-from" /></Field>
        <Field label="به محل *"><LocationSelect warehouseId={warehouseId} value={form.to} onChange={v => setForm(f => ({ ...f, to: v }))} empty="انتخاب کنید..." required testId="move-to" /></Field>
        <Field label="تعداد"><Input type="number" min={1} required value={form.quantity} onChange={set("quantity")} data-testid="move-qty" /></Field>
        <Field label="وضعیت کیفی"><Select value={form.status} onChange={set("status")}>{STATUS_KEYS.map(s => <option key={s} value={s}>{STOCK_STATUS[s].label}</option>)}</Select></Field>
        <Field label="بچ" hint="اختیاری"><Input className="ltr uppercase" value={form.lot} onChange={set("lot")} /></Field>
        <Field label="توضیح"><Input maxLength={500} value={form.reason} onChange={set("reason")} /></Field>
      </form>
    </Modal>
  );
}
