/**
 * صف کار انبار برای گوشی: کار بعدی، محل، کالا و تعداد، و اجرای قدم‌به‌قدم با اسکن.
 * هر قدم یک ورودی بزرگ دارد و Enter بارکدخوان به قدم بعد می‌رود. درستی اسکن‌ها را همان سرویس برداشت و جانمایی می‌سنجد.
 */
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMe } from "@/auth/AuthContext";
import { AlertTriangle, ArrowRight, CheckCircle2, MapPin, Package, ScanLine } from "lucide-react";
import { api, errorMessage, newIdempotencyKey, unwrap, type Schemas } from "@/api/client";
import { useToast } from "@/components/Toast";
import { UpdatedAt } from "@/components/UpdatedAt";
import { faNumber } from "@/lib/format";
import { promptDialog } from "@/ui/dialogs";
import { Badge, Button, Card, EmptyState, ErrorState, Input, PageHeader, Select, Skeleton } from "@/ui/primitives";
import { WarehousePicker, useInvalidateOperations, useWarehouseChoice } from "./shared";

type Task =
  | { kind: "pick"; id: string; line: Schemas["PickLineOut"]; listCode: string; warehouseCode: string }
  | { kind: "putaway"; id: string; task: Schemas["PutawayTaskOut"] }
  | { kind: "receive"; id: string; receipt: Schemas["ReceiptOut"]; line: Schemas["ReceiptLineOut"] };

const remaining = (t: Task) => t.kind === "pick" ? t.line.quantity - t.line.picked_quantity : t.kind === "receive" ? t.line.outstanding : t.task.remaining;
const productOf = (t: Task) => t.kind === "receive"
  ? { name: t.line.product_name, code: t.line.product_sku, lot: null }
  : t.kind === "pick"
  ? { name: t.line.product_name, code: t.line.product_barcode ?? t.line.product_sku, lot: t.line.lot_number }
  : { name: t.task.product_name, code: t.task.product_barcode ?? t.task.product_sku, lot: t.task.lot_number };
const sourceOf = (t: Task) => t.kind === "receive" ? t.receipt.receiving_location_code ?? "محل تخلیه" : t.kind === "pick" ? t.line.location_code ?? t.warehouseCode : t.task.source_location_code ?? t.task.warehouse_code ?? "";

type StepKey = "source" | "product" | "lot" | "destination" | "quantity" | "reason";
interface Step { key: StepKey; title: string; expect: string }

function stepsOf(t: Task, manual: boolean): Step[] {
  const product = productOf(t);
  if (t.kind === "receive") {
    return [
      manual ? { key: "reason" as const, title: "دلیل ورود دستی را انتخاب کنید", expect: "" } : { key: "product" as const, title: "کالا را اسکن کنید", expect: product.code },
      { key: "quantity" as const, title: "تعداد شمارش‌شده", expect: `مانده ${faNumber(remaining(t))}` },
    ];
  }
  return [
    { key: "source" as const, title: "به این محل بروید و آن را اسکن کنید", expect: sourceOf(t) },
    { key: "product" as const, title: "کالا را اسکن کنید", expect: product.code },
    ...(product.lot ? [{ key: "lot" as const, title: "بچ را اسکن کنید", expect: product.lot }] : []),
    ...(t.kind === "putaway" ? [{ key: "destination" as const, title: "محل مقصد را اسکن کنید", expect: t.task.suggested_location_code ?? "محل مقصد" }] : []),
    { key: "quantity" as const, title: "تعداد را تأیید کنید", expect: `حداکثر ${faNumber(remaining(t))}` },
  ];
}

export default function MyTasksPage() {
  const choice = useWarehouseChoice();
  const warehouseId = choice.value ? Number(choice.value) : null;
  const [activeId, setActiveId] = useState<string | null>(null);
  const picks = useQuery({
    queryKey: ["pick-lists", warehouseId, "active"], enabled: !!warehouseId, refetchInterval: 30_000,
    queryFn: () => unwrap(api.GET("/picking/lists", { params: { query: { warehouse_id: warehouseId, status: "active" } } })),
  });
  const putaways = useQuery({
    queryKey: ["putaway-tasks", warehouseId, "active"], enabled: !!warehouseId, refetchInterval: 30_000,
    queryFn: () => unwrap(api.GET("/putaway/tasks", { params: { query: { warehouse_id: warehouseId, status: "active" } } })),
  });
  const receipts = useQuery({
    queryKey: ["receipts", warehouseId, "my-tasks"], enabled: !!warehouseId, refetchInterval: 30_000,
    queryFn: () => unwrap(api.GET("/inbound/receipts", { params: { query: { warehouse_id: warehouseId, with_lines: true } } })),
  });
  const tasks = useMemo<Task[]>(() => [
    // کالای بچ‌دار یا سریالی ورودی بیشتری دارد و در صفحه رسید ثبت می‌شود
    ...(receipts.data ?? []).filter(r => r.status === "open" || r.status === "receiving").flatMap(receipt => receipt.lines
      .filter(line => line.outstanding > 0 && !line.lot_tracked && !line.expiry_tracked && !line.serial_tracked)
      .map(line => ({ kind: "receive" as const, id: `receive-${line.id}`, receipt, line }))),
    ...[...(picks.data ?? [])].reverse().flatMap(list => list.lines.filter(l => l.status === "open").map(line => (
      { kind: "pick" as const, id: `pick-${line.id}`, line, listCode: list.code, warehouseCode: list.warehouse_code ?? "" }))),
    ...[...(putaways.data ?? [])].reverse().map(task => ({ kind: "putaway" as const, id: `putaway-${task.id}`, task })),
  ], [picks.data, putaways.data, receipts.data]);
  const active = tasks.find(t => t.id === activeId) ?? null;
  const me = useMe();
  const toast = useToast();
  const queryClient = useQueryClient();
  const refresh = () => ["pick-lists", "putaway-tasks", "receipts"].forEach(key => queryClient.invalidateQueries({ queryKey: [key] }));
  const claim = useMutation({
    mutationFn: async (t: Task) => {
      if (t.kind === "pick") await unwrap(api.POST("/picking/lines/{line_id}/claim", { params: { path: { line_id: t.line.id } } }));
      // رسید برداشتن ندارد: سقف مقدار و سند یکتا جلوی ثبت تکراری را می‌گیرد
      if (t.kind === "putaway") await unwrap(api.POST("/putaway/tasks/{task_id}/claim", { params: { path: { task_id: t.task.id } } }));
    },
    onSuccess: (_, t) => { setActiveId(t.id); refresh(); },
    onError: e => { toast.error(errorMessage(e)); refresh(); },
  });
  const release = (t: Task) => {
    setActiveId(null);
    if (t.kind === "receive") return;
    void (t.kind === "pick"
      ? api.POST("/picking/lines/{line_id}/release", { params: { path: { line_id: t.line.id } } })
      : api.POST("/putaway/tasks/{task_id}/release", { params: { path: { task_id: t.task.id } } })).then(refresh);
  };
  const heldByOther = (t: Task) => {
    if (t.kind === "receive") return null;
    const by = t.kind === "pick" ? t.line.claimed_by_id : t.task.claimed_by_id;
    const until = t.kind === "pick" ? t.line.claimed_until : t.task.claimed_until;
    const name = t.kind === "pick" ? t.line.claimed_by_name : t.task.claimed_by_name;
    return by && by !== me.id && until && new Date(`${until}Z`) > new Date() ? name ?? "همکار" : null;
  };
  const [next, ...rest] = tasks;
  const error = picks.error ?? putaways.error ?? receipts.error;
  const loading = !!warehouseId && (picks.isLoading || putaways.isLoading || receipts.isLoading);

  return (
    <div data-testid="my-tasks-page">
      <PageHeader eyebrow="انبار" title="صف کار من" subtitle="برداشت و جانمایی، به ترتیب اجرا" actions={<UpdatedAt at={picks.dataUpdatedAt} />} />
      {!choice.isManager && <div className="mb-4 max-w-sm"><WarehousePicker choice={choice} /></div>}
      {active ? <TaskRun key={active.id} task={active} onDone={() => setActiveId(null)} onBack={() => release(active)} /> :
        error ? <ErrorState error={error} onRetry={() => { void picks.refetch(); void putaways.refetch(); void receipts.refetch(); }} /> :
        loading ? <Skeleton className="h-64 rounded-2xl" /> :
        !next ? <Card><EmptyState icon={<CheckCircle2 className="size-5" />} title="کاری در صف نیست" text="کار تازه که برسد همین‌جا نمایش داده می‌شود." /></Card> : (
          <div className="space-y-4">
            <TaskCard task={next} primary holder={heldByOther(next)} busy={claim.isPending} onStart={() => claim.mutate(next)} />
            {rest.length > 0 && <h2 className="pt-2 text-sm font-bold text-muted">بعدی‌ها ({faNumber(rest.length)})</h2>}
            {rest.map(t => <TaskCard key={t.id} task={t} holder={heldByOther(t)} busy={claim.isPending} onStart={() => claim.mutate(t)} />)}
          </div>
        )}
    </div>
  );
}

function TaskCard({ task, primary, holder, busy, onStart }: { task: Task; primary?: boolean; holder: string | null; busy: boolean; onStart: () => void }) {
  const product = productOf(task);
  return (
    <Card className="p-4" data-testid={primary ? "task-next" : "task-row"} data-kind={task.kind}>
      <div className="flex items-center gap-2">
        <Badge tone={task.kind === "pick" ? "info" : task.kind === "receive" ? "success" : "violet"}>{task.kind === "pick" ? "برداشت" : task.kind === "receive" ? "دریافت" : "جانمایی"}</Badge>
        <span className="font-mono text-xs text-muted ltr">{task.kind === "pick" ? task.line.order_tracking_code : task.kind === "receive" ? task.receipt.code : task.task.code}</span>
      </div>
      <div className="mt-3 flex items-center gap-2 text-lg font-black"><MapPin className="size-5 shrink-0 text-brand" /><span className="font-mono ltr">{sourceOf(task) || "—"}</span></div>
      <div className="mt-2 flex items-center gap-2"><Package className="size-5 shrink-0 text-muted" /><span className="font-semibold">{product.name}</span></div>
      <div className="mt-1 text-sm text-muted">تعداد: <span className="font-bold text-text tnum">{faNumber(remaining(task))}</span></div>
      <Button className="mt-4 h-12 w-full" variant={primary ? "primary" : "secondary"} icon={<ScanLine className="size-5" />} loading={busy} disabled={!!holder} onClick={onStart} data-testid="task-start">{holder ? `در دست ${holder}` : "شروع"}</Button>
    </Card>
  );
}

function TaskRun({ task, onDone, onBack }: { task: Task; onDone: () => void; onBack: () => void }) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const [manual, setManual] = useState(false);
  const steps = useMemo(() => stepsOf(task, manual), [task, manual]);
  const [index, setIndex] = useState(0);
  const [values, setValues] = useState<Record<StepKey, string>>({ source: "", product: "", lot: "", destination: "", reason: "", quantity: String(remaining(task)) });
  const [reasonNote, setReasonNote] = useState("");
  const [key, setKey] = useState(newIdempotencyKey);
  const input = useRef<HTMLInputElement>(null);
  const step = steps[index];
  const last = index === steps.length - 1;
  useEffect(() => { input.current?.focus(); input.current?.select(); }, [index]);

  const done = () => { invalidate(); setKey(newIdempotencyKey()); onDone(); };
  const run = useMutation({
    mutationFn: async () => { await (task.kind === "receive"
      ? unwrap(api.POST("/inbound/receipts/{receipt_id}/receive", {
        params: { path: { receipt_id: task.receipt.id }, header: { "Idempotency-Key": key } },
        body: { lines: [{ line_id: task.line.id, quantity: Number(values.quantity), serial_numbers: [], condition: "good", entry_mode: manual ? "manual" : "scan",
          product_scan: manual ? null : values.product, manual_reason: manual ? values.reason as "no_barcode" : null, manual_note: manual && values.reason === "other" ? reasonNote : null }] } }))
      : task.kind === "pick"
      ? unwrap(api.POST("/picking/lines/{line_id}/pick", {
        params: { path: { line_id: task.line.id }, header: { "Idempotency-Key": key } },
        body: { source_scan: values.source, product_scan: values.product, lot_scan: values.lot || null, quantity: Number(values.quantity) } }))
      : unwrap(api.POST("/putaway/tasks/{task_id}/execute", {
        params: { path: { task_id: task.task.id }, header: { "Idempotency-Key": key } },
        body: { source_scan: values.source, product_scan: values.product, destination_scan: values.destination, lot_scan: values.lot || null, quantity: Number(values.quantity) } }))); },
    onSuccess: () => { toast.success("ثبت شد."); done(); },
    onError: e => { toast.error(errorMessage(e)); setKey(newIdempotencyKey()); invalidate(); },
  });
  const short = useMutation({
    mutationFn: (reason: string) => task.kind === "pick"
      ? unwrap(api.POST("/picking/lines/{line_id}/short", { params: { path: { line_id: task.line.id } }, body: { reason } }))
      : Promise.reject(new Error("unsupported")),
    onSuccess: () => { toast.success("کمبود ثبت شد."); done(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!values[step.key].trim()) return;
    if (last) run.mutate();
    else setIndex(i => i + 1);
  };

  return (
    <Card className="p-4" data-testid="task-run">
      <div className="flex items-center justify-between gap-2">
        <Button variant="ghost" size="sm" icon={<ArrowRight className="size-4" />} onClick={() => index ? setIndex(i => i - 1) : onBack()} data-testid="task-back">{index ? "قدم قبل" : "بازگشت به صف"}</Button>
        <span className="text-sm font-semibold tnum" data-testid="task-progress">قدم {faNumber(index + 1)} از {faNumber(steps.length)}</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden>
        <div className="h-full rounded-full bg-brand transition-[width] duration-200" style={{ width: `${((index + 1) / steps.length) * 100}%` }} />
      </div>
      <p className="mt-4 text-sm font-medium text-text-2">{productOf(task).name}</p>
      <form className="mt-4" onSubmit={submit}>
        <label className="block text-xl font-black" htmlFor="task-input">{step.title}</label>
        <div className="mt-2 font-mono text-lg text-brand ltr text-start" data-testid="task-expect">{step.expect}</div>
        {step.key === "reason" ? (
          <div className="mt-4 space-y-3">
            <Select required value={values.reason} onChange={e => setValues(v => ({ ...v, reason: e.target.value }))} data-testid="task-reason">
              <option value="">انتخاب کنید</option>
              <option value="no_barcode">کالا بارکد ندارد</option>
              <option value="label_damaged">برچسب خراب است</option>
              <option value="scanner_down">بارکدخوان کار نمی‌کند</option>
              <option value="other">سایر</option>
            </Select>
            {values.reason === "other" && <Input required minLength={3} maxLength={300} placeholder="توضیح" value={reasonNote} onChange={e => setReasonNote(e.target.value)} data-testid="task-reason-note" />}
          </div>
        ) : (
          <Input id="task-input" ref={input} className="mt-4 h-14 text-lg ltr font-mono" autoComplete="off" required
            type={step.key === "quantity" ? "number" : "text"} min={step.key === "quantity" ? 1 : undefined} max={step.key === "quantity" ? remaining(task) : undefined}
            value={values[step.key]} onChange={e => setValues(v => ({ ...v, [step.key]: e.target.value }))} data-testid="task-input" />
        )}
        <Button type="submit" className="mt-4 h-14 w-full text-base" loading={run.isPending} data-testid="task-submit">{last ? "ثبت" : "قدم بعد"}</Button>
      </form>
      <div className="mt-4 border-t border-border pt-3">
        {task.kind === "receive" ? (index === 0 && (
          <Button variant="ghost" size="sm" onClick={() => setManual(m => !m)} data-testid="task-toggle-manual">{manual ? "برگشت به اسکن" : "ورود دستی"}</Button>
        )) : task.kind === "pick" ? (
          <Button variant="ghost" size="sm" icon={<AlertTriangle className="size-4" />} data-testid="task-short"
            onClick={() => promptDialog({ title: "کمبود در محل", label: "شرح (مثلاً قفسه خالی بود)", required: true, minLength: 3, maxLength: 300 })
              .then(reason => reason && short.mutate(reason))}>این مقدار در محل نیست</Button>
        ) : (
          <Link to="/app/putaway" className="tap-target inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline"><AlertTriangle className="size-4" />ثبت مشکل در صفحه جانمایی</Link>
        )}
      </div>
    </Card>
  );
}
