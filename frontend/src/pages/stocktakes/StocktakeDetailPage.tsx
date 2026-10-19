/**
 * یک انبارگردانی: شمارش کور (مناسب گوشی، ذخیره با Enter یا خروج از فیلد) ← بررسی مغایرت توسط ادمین
 * (دلیل هر مغایرت، شمارش مجدد اقلام مشکوک) ← تأیید و اصلاح موجودی.
 */
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Check, CheckCircle2, Plus, RotateCcw, Search, Send, X } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useToast } from "@/components/Toast";
import { useProducts } from "@/hooks/data";
import { faDate, faDateTime, faNumber } from "@/lib/format";
import { confirmDialog, promptDialog } from "@/ui/dialogs";
import { Badge, Button, Card, ErrorState, Input, PageHeader, SegmentedControl, Select, Skeleton, StatCard, cn } from "@/ui/primitives";
import { STOCKTAKE_STATUS } from "./StocktakesPage";

type Detail = Schemas["StocktakeDetail"];
type Line = Detail["lines"][number];
const REASONS: Record<string, string> = {
  unknown: "نامشخص", damage: "خرابی و آسیب", loss: "مفقودی یا سرقت", entry_error: "خطای ثبت قبلی", unrecorded: "ورود/خروج ثبت‌نشده",
};
const STEPS = [["counting", "شمارش"], ["review", "بررسی ادمین"], ["approved", "اصلاح موجودی"]] as const;

export default function StocktakeDetailPage() {
  const { id } = useParams();
  const stId = Number(id);
  const toast = useToast();
  const queryClient = useQueryClient();
  const key = ["stocktake", stId];
  const { data: st, isLoading, error, refetch } = useQuery({
    queryKey: key, queryFn: () => unwrap(api.GET("/stocktakes/{stocktake_id}", { params: { path: { stocktake_id: stId } } })),
  });
  const set = (d: Detail) => {
    queryClient.setQueryData(key, d);
    queryClient.invalidateQueries({ queryKey: ["stocktakes"] });
    queryClient.invalidateQueries({ queryKey: ["stocktakes-summary"] });
  };
  const run = useMutation({ mutationFn: (fn: () => Promise<Detail>) => fn(), onSuccess: set, onError: e => toast.error(errorMessage(e)) });
  const path = { params: { path: { stocktake_id: stId } } };

  if (isLoading) return <Skeleton className="h-96" />;
  if (error || !st) return <ErrorState error={error} onRetry={refetch} />;
  const stepIndex = st.status === "approved" ? 2 : st.status === "review" ? 1 : 0;

  return (
    <>
      <PageHeader eyebrow="انبارگردانی" title={st.title ?? st.code}
        subtitle={<span className="flex flex-wrap items-center gap-2"><span className="font-mono ltr">{st.code}</span> · {st.warehouse_name} · {st.scope === "full" ? "کامل" : "بخشی"}
          <Badge tone={STOCKTAKE_STATUS[st.status].tone} dot>{STOCKTAKE_STATUS[st.status].label}</Badge></span>}
        actions={<>
          <Link to="/app/stocktakes" className="inline-flex h-9 items-center gap-1.5 rounded-xl px-3 text-sm text-text-2 hover:bg-surface-2"><ArrowRight className="size-4" />همه انبارگردانی‌ها</Link>
          {st.can_cancel && <Button size="sm" variant="ghost" icon={<X className="size-4" />} data-testid="stocktake-cancel"
            onClick={() => confirmDialog({ title: "انبارگردانی لغو شود؟", text: "شمارش‌ها نگه داشته می‌شوند ولی موجودی اصلاح نمی‌شود.", confirmLabel: "لغو انبارگردانی", danger: true })
              .then(ok => ok && run.mutate(() => unwrap(api.POST("/stocktakes/{stocktake_id}/cancel", path))))}>لغو</Button>}
        </>} />

      {st.status !== "canceled" && (
        <ol className="mb-6 grid grid-cols-3 gap-2" data-testid="stocktake-steps">
          {STEPS.map(([k, label], i) => (
            <li key={k} className={cn("flex items-center gap-2 rounded-xl border px-3 py-2.5 text-sm",
              i < stepIndex || st.status === "approved" ? "border-brand/30 bg-brand-soft/50 text-brand-strong" : i === stepIndex ? "border-brand bg-surface font-semibold" : "border-border text-muted")}>
              <span className={cn("grid size-6 place-items-center rounded-full text-xs", i < stepIndex || st.status === "approved" ? "bg-brand text-brand-ink" : "bg-surface-2")}>
                {i < stepIndex || st.status === "approved" ? <Check className="size-3.5" strokeWidth={3} /> : faNumber(i + 1)}</span>
              {label}
            </li>
          ))}
        </ol>
      )}
      {st.note && <p className="mb-5 rounded-xl bg-info-soft/60 px-4 py-3 text-sm text-text-2">{st.note}</p>}

      {st.can_count ? <CountView st={st} onChange={set} run={run.mutate} />
        : st.status === "counting" ? <Card className="p-6 text-sm text-muted">شمارش این انبارگردانی با مدیر همان انبار است. پیشرفت: {faNumber(st.lines_counted)} از {faNumber(st.lines_total)}</Card>
          : st.revealed ? <ReviewView st={st} run={run.mutate} busy={run.isPending} />
            : <Card className="p-6 text-sm text-text-2" data-testid="stocktake-waiting">
                شمارش {faNumber(st.lines_total)} قلم ثبت و برای بررسی ادمین ارسال شد{st.submitted_at ? ` (${faDateTime(st.submitted_at)})` : ""}.
                {st.status === "approved" && " موجودی انبار بر اساس این انبارگردانی اصلاح شد."}
              </Card>}
    </>
  );
}

// ---------------------------------------------------------------------------
// شمارش
// ---------------------------------------------------------------------------
function CountView({ st, onChange, run }: { st: Detail; onChange: (d: Detail) => void; run: (fn: () => Promise<Detail>) => void }) {
  const toast = useToast();
  const [filter, setFilter] = useState<"todo" | "done" | "all">("todo");
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const recounts = st.lines.filter(l => l.recount_note && l.counted_qty === null).length;
  const lines = st.lines.filter(l => (filter === "all" || (filter === "todo" ? l.counted_qty === null : l.counted_qty !== null))
    && (!q.trim() || `${l.product_name} ${l.product_sku ?? ""}`.includes(q.trim())));
  const percent = st.lines_total ? Math.round((st.lines_counted / st.lines_total) * 100) : 0;
  const save = async (line: Line, value: string) => {
    const qty = Number(value.replace(/[۰-۹]/g, d => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))));
    if (value.trim() === "" || !Number.isInteger(qty) || qty < 0 || qty === line.counted_qty) return;
    try {
      onChange(await unwrap(api.PUT("/stocktakes/{stocktake_id}/lines/{line_id}", { params: { path: { stocktake_id: st.id, line_id: line.id } }, body: { counted_qty: qty } })));
    } catch (e) { toast.error(errorMessage(e)); }
  };

  return (
    <div className="space-y-4" data-testid="stocktake-count">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-48 flex-1">
            <div className="flex items-baseline justify-between text-sm"><span className="font-semibold">پیشرفت شمارش</span>
              <span className="tnum text-muted">{faNumber(st.lines_counted)} از {faNumber(st.lines_total)}</span></div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2"><div className="h-full rounded-full bg-brand transition-all duration-500" style={{ width: `${percent}%` }} /></div>
          </div>
          <Button icon={<Send className="size-4" />} disabled={!st.can_submit} data-testid="stocktake-submit"
            onClick={() => confirmDialog({ title: "شمارش تمام شد؟", text: "پس از ارسال، ادمین مغایرت‌ها را بررسی و تأیید می‌کند.", confirmLabel: "ارسال برای بررسی" })
              .then(ok => ok && run(() => unwrap(api.POST("/stocktakes/{stocktake_id}/submit", { params: { path: { stocktake_id: st.id } } }))))}>
            ارسال برای بررسی</Button>
        </div>
        <p className="mt-3 text-xs text-muted">عدد واقعی هر قلم را بشمارید و بنویسید؛ موجودی ثبت‌شده در سیستم عمداً نمایش داده نمی‌شود. با Enter ذخیره و به قلم بعدی بروید.</p>
        {recounts > 0 && <p className="mt-2 flex items-center gap-1.5 text-sm font-medium text-warning"><RotateCcw className="size-4" />ادمین شمارش مجدد {faNumber(recounts)} قلم را خواسته است.</p>}
      </Card>

      <div className="flex flex-wrap items-center gap-2">
        <SegmentedControl value={filter} onChange={setFilter} options={[{ value: "todo", label: "شمرده‌نشده" }, { value: "done", label: "شمرده‌شده" }, { value: "all", label: "همه" }]} />
        <label className="relative min-w-48 flex-1">
          <Search className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="نام یا کد کالا" className="h-10 w-full rounded-xl border border-border bg-surface pe-3 ps-9 text-sm outline-none focus:border-brand" data-testid="stocktake-search" />
        </label>
        <Button variant="secondary" size="sm" icon={<Plus className="size-4" />} onClick={() => setAdding(true)} data-testid="stocktake-add">کالای خارج از فهرست</Button>
      </div>
      {adding && <AddFound st={st} onDone={d => { onChange(d); setAdding(false); }} onCancel={() => setAdding(false)} />}

      <Card className="divide-y divide-border overflow-hidden" data-testid="stocktake-lines">
        {lines.length === 0 && <div className="px-5 py-10 text-center text-sm text-muted">{filter === "todo" ? "همه اقلام شمرده شده‌اند ✓" : "قلمی پیدا نشد"}</div>}
        {lines.map((l, i) => (
          <div key={l.id} className="flex flex-wrap items-center gap-3 px-4 py-3" data-testid="stocktake-line" data-product={l.product_name} data-counted={l.counted_qty ?? ""}>
            <div className="min-w-40 flex-1">
              <div className="font-medium">{l.product_name}{l.added_during_count && <Badge tone="info" className="ms-2">اضافه‌شده</Badge>}</div>
              <div className="font-mono text-xs text-muted">{l.product_sku}</div>
              {l.recount_note && l.counted_qty === null && <div className="mt-1 text-xs text-warning">شمارش مجدد: {l.recount_note}</div>}
            </div>
            <div className="flex items-center gap-2">
              {l.counted_qty !== null && <CheckCircle2 className="size-4 text-success" />}
              <Input key={`${l.id}-${l.counted_qty}`} inputMode="numeric" defaultValue={l.counted_qty ?? ""} placeholder="تعداد"
                className="h-11 w-28 text-center text-base font-semibold tnum" aria-label={`تعداد ${l.product_name}`} data-testid="stocktake-qty"
                onBlur={e => save(l, e.target.value)}
                onKeyDown={e => {
                  if (e.key !== "Enter") return;
                  e.preventDefault();
                  save(l, e.currentTarget.value);
                  const inputs = [...document.querySelectorAll<HTMLInputElement>("[data-testid=stocktake-qty]")];
                  inputs[i + 1]?.focus();
                }} />
            </div>
          </div>
        ))}
      </Card>
    </div>
  );
}

function AddFound({ st, onDone, onCancel }: { st: Detail; onDone: (d: Detail) => void; onCancel: () => void }) {
  const toast = useToast();
  const { data: products = [] } = useProducts();
  const [product, setProduct] = useState("");
  const [qty, setQty] = useState("");
  const options = products.filter(p => !st.lines.some(l => l.product_id === p.id));
  const add = useMutation({
    mutationFn: () => unwrap(api.POST("/stocktakes/{stocktake_id}/lines", { params: { path: { stocktake_id: st.id } }, body: { product_id: Number(product), counted_qty: Number(qty) } })),
    onSuccess: onDone, onError: e => toast.error(errorMessage(e)),
  });
  return (
    <Card className="flex flex-wrap items-end gap-2 border-info/40 p-4 animate-fade" data-testid="stocktake-add-form">
      <div className="min-w-56 flex-1">
        <div className="mb-1.5 text-xs text-muted">کالایی که در فهرست نبود ولی در انبار پیدا شد</div>
        <Select value={product} onChange={e => setProduct(e.target.value)} data-testid="stocktake-add-product">
          <option value="">انتخاب کالا</option>{options.map(p => <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>)}
        </Select>
      </div>
      <Input inputMode="numeric" value={qty} onChange={e => setQty(e.target.value)} placeholder="تعداد" className="w-28 text-center" data-testid="stocktake-add-qty" />
      <Button disabled={!product || qty === ""} loading={add.isPending} onClick={() => add.mutate()}>افزودن</Button>
      <Button variant="ghost" onClick={onCancel}>انصراف</Button>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// بررسی ادمین / گزارش نهایی
// ---------------------------------------------------------------------------
function ReviewView({ st, run, busy }: { st: Detail; run: (fn: () => Promise<Detail>) => void; busy: boolean }) {
  const [onlyDiff, setOnlyDiff] = useState(true);
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const review = st.can_review;
  const lines = useMemo(() => st.lines.filter(l => !onlyDiff || (l.variance ?? 0) !== 0), [st.lines, onlyDiff]);
  const path = { params: { path: { stocktake_id: st.id } } };

  return (
    <div className="space-y-5" data-testid="stocktake-review">
      {st.self_review && (
        <p className="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning-soft/50 px-4 py-3 text-sm text-text-2">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />بخشی از این شمارش را خودتان انجام داده‌اید؛ بهتر است شمارش و تأیید با دو نفر باشد.</p>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="دقت موجودی" value={`${faNumber(st.accuracy ?? 0)}٪`} tone={(st.accuracy ?? 0) >= 95 ? "success" : "warning"} hint={`${faNumber(st.variance_lines ?? 0)} قلم مغایرت از ${faNumber(st.lines_total)}`} />
        <StatCard label="کسری" value={faNumber(st.shortage_qty ?? 0)} tone="danger" hint={`${faNumber(st.shortage_value ?? 0)} ریال`} />
        <StatCard label="اضافی" value={faNumber(st.surplus_qty ?? 0)} tone="info" hint={`${faNumber(st.surplus_value ?? 0)} ریال`} />
        <StatCard label="خالص اثر مالی" value={faNumber((st.surplus_value ?? 0) - (st.shortage_value ?? 0))} tone="brand" hint="ریال (اضافی − کسری)" />
      </div>

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
          <SegmentedControl value={onlyDiff ? "diff" : "all"} onChange={v => setOnlyDiff(v === "diff")} options={[{ value: "diff", label: "فقط مغایرت‌ها" }, { value: "all", label: "همه اقلام" }]} />
          {review && <div className="ms-auto flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" icon={<RotateCcw className="size-4" />} disabled={!picked.size || busy} data-testid="stocktake-recount"
              onClick={() => promptDialog({ title: "شمارش مجدد", label: "توضیح برای شمارنده", placeholder: "مثلاً قفسه پشتی را هم بشمارید", required: false, confirmLabel: `شمارش مجدد ${faNumber(picked.size)} قلم` })
                .then(note => note !== null && run(() => unwrap(api.POST("/stocktakes/{stocktake_id}/recount", { ...path, body: { line_ids: [...picked], note: note || null } }))))}>
              شمارش مجدد انتخاب‌شده‌ها</Button>
            <Button size="sm" icon={<CheckCircle2 className="size-4" />} loading={busy} data-testid="stocktake-approve"
              onClick={() => confirmDialog({ title: "تأیید و اصلاح موجودی؟", text: `${faNumber(st.variance_lines ?? 0)} قلم مغایرت در دفتر گردش با نوع «انبارگردانی» ثبت و موجودی اصلاح می‌شود. این کار برگشت ندارد.`, confirmLabel: "تأیید و اصلاح" })
                .then(ok => ok && run(() => unwrap(api.POST("/stocktakes/{stocktake_id}/approve", { ...path, body: { reasons: reasons as never } }))))}>
              تأیید و اصلاح موجودی</Button>
          </div>}
        </div>
        <div className="overflow-x-auto">
          <table className="table-base" data-testid="stocktake-variance-table">
            <thead><tr>{review && <th className="w-10" />}<th>کالا</th><th>سیستم</th><th>شمرده‌شده</th><th>مغایرت</th><th>ارزش</th><th>{review ? "دلیل مغایرت" : "دلیل / اصلاح"}</th><th>شمارنده</th></tr></thead>
            <tbody>
              {lines.length === 0 && <tr><td colSpan={8} className="py-10 text-center text-muted">هیچ مغایرتی نیست ✓</td></tr>}
              {lines.map(l => (
                <tr key={l.id} data-testid="stocktake-variance-row" data-product={l.product_name}>
                  {review && <td><input type="checkbox" checked={picked.has(l.id)} aria-label="شمارش مجدد"
                    onChange={() => setPicked(s => { const n = new Set(s); if (n.has(l.id)) n.delete(l.id); else n.add(l.id); return n; })} /></td>}
                  <td><div className="font-medium">{l.product_name}</div><div className="font-mono text-xs text-muted">{l.product_sku}
                    {l.previous_count !== null && <span className="ms-2 text-warning">شمارش قبلی: {faNumber(l.previous_count)}</span>}</div></td>
                  <td className="tnum">{faNumber(l.expected_qty)}</td>
                  <td className="tnum font-semibold">{faNumber(l.counted_qty)}</td>
                  <td className={cn("tnum font-bold", (l.variance ?? 0) < 0 ? "text-danger" : (l.variance ?? 0) > 0 ? "text-info" : "text-success")} data-testid="stocktake-variance">
                    {(l.variance ?? 0) > 0 ? "+" : ""}{faNumber(l.variance)}</td>
                  <td className="tnum text-xs text-text-2">{faNumber(l.variance_value)}</td>
                  <td>{review && (l.variance ?? 0) !== 0
                    ? <Select value={reasons[l.id] ?? "unknown"} onChange={e => setReasons(r => ({ ...r, [l.id]: e.target.value }))} className="h-8 w-40 text-xs" aria-label="دلیل">
                        {Object.entries(REASONS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>
                    : <span className="text-xs text-text-2">{l.variance_reason ? REASONS[l.variance_reason] : "—"}{l.adjustment ? ` · اصلاح ${l.adjustment > 0 ? "+" : ""}${faNumber(l.adjustment)}` : ""}</span>}</td>
                  <td className="text-xs text-muted">{l.counted_by ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <p className="text-xs text-muted">
        مبنای مغایرت، موجودی سیستم در لحظه شمارش هر قلم است؛ ورود و خروج‌های بعد از شمارش دست نمی‌خورند.
        {st.approved_at && <> تأیید: {faDate(st.approved_at)} توسط {st.approved_by}. <Link to="/app/ledger" className="text-brand hover:underline">دفتر گردش</Link></>}
      </p>
    </div>
  );
}
