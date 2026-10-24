/**
 * رسید و دریافت کالا (فصل ۷): خرید، انتقال از انبار در راه، مرجوعی و ورود پیش‌بینی‌نشده.
 * هر سطر: مورد انتظار، دریافت‌شده، پذیرفته، مردود، در انتظار بازرسی و باقی‌مانده؛ مغایرت هنگام بستن ثبت می‌شود.
 */
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { CheckCheck, ClipboardCheck, PackageOpen, Plus, Search, Trash2, X } from "lucide-react";
import { api, errorMessage, isServerError, newIdempotencyKey, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { usePartners, useProducts, useWarehouses } from "@/hooks/data";
import { DISCREPANCY, PUTAWAY_STATUS, RECEIPT_STATUS, RECEIPT_TYPES } from "@/lib/labels";
import { faDate, faDateTime, faNumber } from "@/lib/format";
import { DateField } from "@/ui/datetime";
import { promptDialog } from "@/ui/dialogs";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, Select, Table, TableSkeleton, Textarea } from "@/ui/primitives";
import { InspectModal, LocationSelect, WarehousePicker, useInvalidateOperations, useWarehouseChoice } from "./shared";

type Receipt = Schemas["ReceiptOut"];
type Line = Schemas["ReceiptLineOut"];
type ReceiptType = Schemas["ReceiptCreate"]["receipt_type"];

export function ReceiptStatusBadge({ status }: { status: string }) {
  const s = RECEIPT_STATUS[status];
  return <Badge tone={s?.tone ?? "muted"} dot>{s?.label ?? status}</Badge>;
}

export default function ReceiptsPage() {
  const me = useMe();
  const [params, setParams] = useSearchParams();
  const { data: warehouses = [] } = useWarehouses();
  const filters = {
    status: params.get("status") || undefined, receipt_type: params.get("type") || undefined,
    warehouse_id: params.get("warehouse") ? Number(params.get("warehouse")) : undefined, q: params.get("q") || undefined,
  };
  const openId = params.get("receipt") ? Number(params.get("receipt")) : null;
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  };
  const [creating, setCreating] = useState(false);
  const { data: receipts, isLoading, error, refetch } = useQuery({
    queryKey: ["receipts", filters],
    queryFn: () => unwrap(api.GET("/inbound/receipts", { params: { query: { ...filters, status: filters.status as never, receipt_type: filters.receipt_type as never, limit: 200 } } })),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader eyebrow="انبار" title="رسید و دریافت کالا"
        subtitle="ورود برنامه‌ریزی‌شده یا پیش‌بینی‌نشده با شمارش، بچ، انقضا و سریال؛ کسری و اضافه تحویل هنگام بستن رسید ثبت می‌شود."
        actions={<Button icon={<Plus className="size-4" />} onClick={() => setCreating(true)} data-testid="receipt-new">رسید جدید</Button>} />
      <Card>
        <div className="grid gap-3 border-b border-border p-4 md:grid-cols-4">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" />
            <Input className="pr-10" placeholder="کد رسید، بارنامه یا سفارش خرید" value={params.get("q") ?? ""} onChange={e => setFilter("q", e.target.value)} data-testid="receipts-search" />
          </div>
          <Select value={params.get("status") ?? ""} onChange={e => setFilter("status", e.target.value)} aria-label="وضعیت رسید" data-testid="receipts-status">
            <option value="">همه وضعیت‌ها</option>{Object.entries(RECEIPT_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
          <Select value={params.get("type") ?? ""} onChange={e => setFilter("type", e.target.value)} aria-label="نوع رسید">
            <option value="">همه انواع</option>{Object.entries(RECEIPT_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
          {me.role === "org_admin" ? (
            <Select value={params.get("warehouse") ?? ""} onChange={e => setFilter("warehouse", e.target.value)} aria-label="انبار">
              <option value="">همه انبارها</option>{warehouses.filter(w => w.holds_stock).map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          ) : <div className="hidden md:block" />}
        </div>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : !receipts?.length ? (
          <EmptyState icon={<PackageOpen className="size-5" />} title="رسیدی با این فیلترها نیست"
            action={<Button size="sm" onClick={() => setCreating(true)}>ثبت اولین رسید</Button>} />
        ) : (
          <Table testId="receipts-table">
            <thead><tr><th>کد رسید</th><th>نوع</th><th>وضعیت</th><th>انبار</th><th>طرف / بارنامه</th><th>مورد انتظار</th><th>دریافت‌شده</th><th>زمان</th></tr></thead>
            <tbody>
              {receipts.map(r => (
                <tr key={r.id} className="cursor-pointer hover:bg-surface-2" onClick={() => setFilter("receipt", String(r.id))}
                  data-testid="receipt-row" data-code={r.code} data-status={r.status}>
                  <td className="font-mono text-xs font-semibold ltr text-start">{r.code}</td>
                  <td className="text-xs">{r.receipt_type_label}</td>
                  <td><div className="flex flex-wrap gap-1"><ReceiptStatusBadge status={r.status} />{r.has_discrepancy && <Badge tone="danger">مغایرت</Badge>}</div></td>
                  <td className="text-text-2">{r.warehouse_name}</td>
                  <td className="max-w-56 text-xs text-text-2">{r.partner_name ?? r.source_warehouse_name ?? "—"}{r.external_ref ? ` · ${r.external_ref}` : ""}</td>
                  <td className="tnum">{faNumber(r.total_expected)}</td>
                  <td className="tnum">{faNumber(r.total_received)}{r.total_pending_inspection > 0 && <Badge tone="info" className="ms-1">بازرسی {faNumber(r.total_pending_inspection)}</Badge>}</td>
                  <td className="whitespace-nowrap text-xs text-text-2">{faDateTime(r.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {creating && <NewReceiptModal onClose={() => setCreating(false)} onCreated={id => { setCreating(false); setFilter("receipt", String(id)); }} />}
      <ReceiptModal id={openId} onClose={() => setFilter("receipt", "")} />
    </>
  );
}

function NewReceiptModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: number) => void }) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const choice = useWarehouseChoice();
  const { data: warehouses = [] } = useWarehouses();
  const { data: products = [] } = useProducts();
  const [type, setType] = useState<ReceiptType>("purchase");
  const { data: partners = [] } = usePartners(type === "return" ? "customer" : "supplier");
  const { data: owners = [] } = usePartners("owner");
  const [form, setForm] = useState({ partner: "", owner: "", source: "", externalRef: "", reference: "", expected: "", tolerance: "0", location: "", note: "" });
  const [lines, setLines] = useState([{ product: "", quantity: "1", lot: "" }]);
  const [key] = useState(newIdempotencyKey);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm(f => ({ ...f, [k]: e.target.value }));
  const transits = warehouses.filter(w => w.type === "transit" && String(w.id) !== choice.value);
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/inbound/receipts", {
      params: { header: { "Idempotency-Key": key } },
      body: {
        receipt_type: type, warehouse_id: Number(choice.value), partner_id: form.partner ? Number(form.partner) : null,
        owner_id: form.owner ? Number(form.owner) : null, source_warehouse_id: type === "transfer" && form.source ? Number(form.source) : null,
        external_ref: form.externalRef || null, reference_number: form.reference || null, expected_date: form.expected || null,
        over_tolerance_pct: Number(form.tolerance) || 0, receiving_location_id: form.location ? Number(form.location) : null,
        note: form.note || null,
        lines: type === "unexpected" ? [] : lines.filter(l => l.product).map(l => ({
          product_id: Number(l.product), expected_quantity: Number(l.quantity), lot_number: l.lot || null })),
      },
    })),
    onSuccess: r => { toast.success(`رسید ${r.code} ثبت شد.`); invalidate(); onCreated(r.id); },
    onError: e => toast.error(errorMessage(e)),
  });

  return (
    <Modal open onClose={onClose} size="lg" title="رسید جدید" testId="receipt-form"
      description="مقادیر مورد انتظار (از سفارش خرید، اعلام ارسال یا حواله انتقال)؛ شمارش واقعی هنگام «دریافت» ثبت می‌شود."
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="receipt-form-el" loading={save.isPending} data-testid="receipt-save">ثبت رسید</Button></>}>
      <form id="receipt-form-el" className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="نوع رسید">
            <Select value={type} onChange={e => { setType(e.target.value as ReceiptType); setForm(f => ({ ...f, partner: "" })); }} data-testid="receipt-type">
              {Object.entries(RECEIPT_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </Field>
          <Field label="انبار مقصد"><WarehousePicker choice={choice} testId="receipt-warehouse" /></Field>
          {type === "transfer" ? (
            <Field label="از انبار در راه *">
              <Select required value={form.source} onChange={set("source")} data-testid="receipt-source">
                <option value="">انتخاب کنید...</option>{transits.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
              </Select>
            </Field>
          ) : (
            <Field label={type === "return" ? "مشتری" : type === "purchase" ? "تأمین‌کننده *" : "تأمین‌کننده"}>
              <Select required={type === "purchase"} value={form.partner} onChange={set("partner")} data-testid="receipt-partner">
                <option value="">—</option>{partners.map(p => <option key={p.id} value={p.id}>{p.name} ({p.code})</option>)}
              </Select>
            </Field>
          )}
          <Field label="شماره بارنامه / حواله" hint="برای هر طرف یکتاست"><Input className="ltr" maxLength={64} value={form.externalRef} onChange={set("externalRef")} data-testid="receipt-ref" /></Field>
          <Field label="شماره سفارش خرید / اعلام ارسال"><Input className="ltr" maxLength={64} value={form.reference} onChange={set("reference")} /></Field>
          <Field label="تاریخ ورود مورد انتظار"><DateField value={form.expected} onChange={v => setForm(f => ({ ...f, expected: v }))} /></Field>
          <Field label="محل تخلیه" hint="خالی = اولین محل تخلیه انبار">
            <LocationSelect warehouseId={choice.value ? Number(choice.value) : null} value={form.location} onChange={v => setForm(f => ({ ...f, location: v }))}
              types={["receiving", "staging", "quarantine"]} empty="پیش‌فرض" />
          </Field>
          <Field label="تلورانس اضافه تحویل (٪)" hint="بیشتر از آن فقط با ذکر دلیل"><Input type="number" min={0} max={100} step="0.5" value={form.tolerance} onChange={set("tolerance")} /></Field>
          <Field label="مالک کالا (امانی)" hint="خالی = خود سازمان">
            <Select value={form.owner} onChange={set("owner")}><option value="">خود سازمان</option>{owners.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>
          </Field>
        </div>
        {type !== "unexpected" ? (
          <div className="space-y-2">
            <div className="text-sm font-semibold">کالاهای مورد انتظار</div>
            {lines.map((l, i) => (
              <div key={i} className="grid items-end gap-2 sm:grid-cols-[1fr_7rem_9rem_auto]" data-testid="receipt-line-input">
                <Select required value={l.product} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, product: e.target.value } : x))} data-testid="receipt-line-product" searchable>
                  <option value="">انتخاب کالا...</option>
                  {products.filter(p => p.is_active).map(p => <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>)}
                </Select>
                <Input type="number" min={1} required value={l.quantity} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, quantity: e.target.value } : x))} aria-label="مقدار" data-testid="receipt-line-qty" />
                <Input className="ltr uppercase" placeholder="بچ (اختیاری)" value={l.lot} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, lot: e.target.value } : x))} />
                <Button type="button" variant="ghost" size="icon" disabled={lines.length === 1} onClick={() => setLines(lines.filter((_, j) => j !== i))} aria-label="حذف سطر"><Trash2 className="size-4" /></Button>
              </div>
            ))}
            <Button type="button" size="sm" variant="soft" icon={<Plus className="size-4" />} onClick={() => setLines([...lines, { product: "", quantity: "1", lot: "" }])}>سطر دیگر</Button>
          </div>
        ) : <p className="rounded-xl bg-surface-2 p-3 text-sm text-text-2">ورود پیش‌بینی‌نشده سطر مورد انتظار ندارد؛ کالاها هنگام دریافت اضافه می‌شوند.</p>}
        <Field label="توضیح"><Input maxLength={500} value={form.note} onChange={set("note")} /></Field>
      </form>
    </Modal>
  );
}

function ReceiptModal({ id, onClose }: { id: number | null; onClose: () => void }) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const [receiving, setReceiving] = useState(false);
  const [closing, setClosing] = useState(false);
  const [inspecting, setInspecting] = useState<Line | null>(null);
  const { data: r, isLoading } = useQuery({
    queryKey: ["receipt", id],
    queryFn: () => unwrap(api.GET("/inbound/receipts/{receipt_id}", { params: { path: { receipt_id: id! } } })),
    enabled: id != null,
  });
  const cancel = useMutation({
    mutationFn: (reason: string) => unwrap(api.POST("/inbound/receipts/{receipt_id}/cancel", { params: { path: { receipt_id: id! } }, body: { reason } })),
    onSuccess: () => { toast.success("رسید لغو شد."); invalidate(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const active = r && (r.status === "open" || r.status === "receiving");

  return (
    <>
      <Modal open={id != null} onClose={onClose} size="xl" testId="receipt-detail"
        title={r ? <span className="flex flex-wrap items-center gap-2"><span className="font-mono ltr">{r.code}</span><ReceiptStatusBadge status={r.status} /><Badge>{r.receipt_type_label}</Badge></span> : "رسید"}
        description={r && `${r.warehouse_name} · ${r.partner_name ?? r.source_warehouse_name ?? "بدون طرف"}${r.external_ref ? ` · بارنامه ${r.external_ref}` : ""}${r.reference_number ? ` · سفارش خرید ${r.reference_number}` : ""}`}
        footer={r && active && <>
          {r.status === "open" && <Button variant="outline-danger" className="me-auto" icon={<X className="size-4" />} loading={cancel.isPending}
            onClick={() => promptDialog({ title: `لغو رسید ${r.code}`, label: "دلیل لغو", required: true, minLength: 3, maxLength: 300, danger: true, confirmLabel: "لغو رسید" }).then(v => v && cancel.mutate(v))}>لغو</Button>}
          <Button variant="secondary" icon={<CheckCheck className="size-4" />} onClick={() => setClosing(true)} data-testid="receipt-close">بستن رسید</Button>
          <Button icon={<PackageOpen className="size-4" />} onClick={() => setReceiving(true)} data-testid="receipt-receive">ثبت دریافت</Button>
        </>}>
        {isLoading || !r ? <div className="h-48 animate-pulse rounded-xl bg-surface-2" /> : (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-6" data-testid="receipt-totals">
              {([["مورد انتظار", r.total_expected], ["دریافت‌شده", r.total_received], ["پذیرفته", r.total_accepted],
                ["مردود", r.total_rejected], ["در انتظار بازرسی", r.total_pending_inspection], ["باقی‌مانده", r.total_outstanding]] as const).map(([label, value]) => (
                <div key={label} className="rounded-xl bg-surface-2 p-3"><div className="text-[11px] text-muted">{label}</div><div className="tnum text-lg font-bold">{faNumber(value)}</div></div>
              ))}
            </div>
            <div className="overflow-x-auto">
              <table className="table-base" data-testid="receipt-lines">
                <thead><tr><th>کالا</th><th>انتظار</th><th>دریافت</th><th>پذیرفته</th><th>مردود</th><th>بازرسی</th><th>باقی‌مانده</th><th>مغایرت</th><th className="w-1" /></tr></thead>
                <tbody>
                  {r.lines.map(l => (
                    <tr key={l.id} data-testid="receipt-line" data-received={l.received_quantity} data-discrepancy={l.discrepancy_type ?? ""}>
                      <td><div className="font-medium">{l.product_name}</div><div className="font-mono text-xs text-muted">{l.product_sku}{l.lot_number ? ` · بچ ${l.lot_number}` : ""}</div></td>
                      <td className="tnum">{faNumber(l.expected_quantity)}</td>
                      <td className="tnum font-semibold">{faNumber(l.received_quantity)}</td>
                      <td className="tnum text-success">{faNumber(l.accepted_quantity)}</td>
                      <td className="tnum text-danger">{faNumber(l.rejected_quantity)}</td>
                      <td className="tnum">{l.pending_inspection ? <Badge tone="info">{faNumber(l.pending_inspection)}</Badge> : "—"}</td>
                      <td className="tnum">{faNumber(l.outstanding)}</td>
                      <td className="text-xs">{l.discrepancy_type ? <><Badge tone={DISCREPANCY[l.discrepancy_type]?.tone ?? "muted"}>{DISCREPANCY[l.discrepancy_type]?.label} {faNumber(l.discrepancy_quantity)}</Badge>{l.discrepancy_reason && <div className="mt-1 text-muted">{l.discrepancy_reason}</div>}</> : l.over_reason ? <span className="text-muted">{l.over_reason}</span> : "—"}</td>
                      <td>{l.pending_inspection > 0 && <Button size="sm" variant="soft" icon={<ClipboardCheck className="size-3.5" />} onClick={() => setInspecting(l)} data-testid="receipt-inspect">بازرسی</Button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {(r.documents.length > 0 || r.putaway_tasks.length > 0) && (
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <div className="mb-2 text-xs font-semibold text-text-2">اسناد دریافت</div>
                  <ul className="space-y-1 text-sm">{r.documents.map(d => <li key={d.id} className="flex justify-between gap-2"><span className="font-mono ltr">{d.code}</span><span className="text-xs text-muted">{faNumber(d.total)} عدد · {faDateTime(d.created_at)}</span></li>)}</ul>
                </div>
                <div>
                  <div className="mb-2 text-xs font-semibold text-text-2">وظایف جانمایی</div>
                  {!r.putaway_tasks.length && <p className="text-xs text-muted">هنوز وظیفه‌ای نیست (کالای در انتظار بازرسی پس از بازرسی جانمایی می‌شود).</p>}
                  <ul className="space-y-1 text-sm" data-testid="receipt-tasks">{r.putaway_tasks.map(t => (
                    <li key={t.id} className="flex flex-wrap items-center justify-between gap-2"><span className="font-mono ltr">{t.code}</span>
                      <span className="flex items-center gap-1 text-xs"><Badge tone={PUTAWAY_STATUS[t.status]?.tone ?? "muted"}>{PUTAWAY_STATUS[t.status]?.label}</Badge>{faNumber(t.quantity_done)}/{faNumber(t.quantity)} · {t.stock_status_label}</span></li>
                  ))}</ul>
                </div>
              </div>
            )}
            <div className="text-xs text-muted">ثبت: {faDateTime(r.created_at)} · {r.created_by_name ?? "—"}{r.expected_date ? ` · انتظار ورود ${faDate(r.expected_date)}` : ""}
              {r.closed_at ? ` · بسته‌شده ${faDateTime(r.closed_at)}` : ""}{r.close_note ? ` — ${r.close_note}` : ""}</div>
          </div>
        )}
      </Modal>
      {r && receiving && <ReceiveModal receipt={r} onClose={() => setReceiving(false)} />}
      {r && closing && <CloseModal receipt={r} onClose={() => setClosing(false)} />}
      <InspectModal onClose={() => setInspecting(null)} target={inspecting && r ? {
        product_id: inspecting.product_id, product_name: inspecting.product_name, warehouse_id: r.warehouse_id, from_status: "pending",
        quantity: inspecting.pending_inspection, receipt_id: r.id,
      } : null} />
    </>
  );
}

type ReceiveRow = { line: string; product: string; quantity: string; lot: string; expiry: string; serials: string; condition: "good" | "damaged"; over: string };

function ReceiveModal({ receipt, onClose }: { receipt: Receipt; onClose: () => void }) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const { data: products = [] } = useProducts();
  const [location, setLocation] = useState(receipt.receiving_location_id ? String(receipt.receiving_location_id) : "");
  const [rows, setRows] = useState<ReceiveRow[]>(receipt.lines.filter(l => l.outstanding > 0 || receipt.receipt_type === "unexpected").map(l => ({
    line: String(l.id), product: String(l.product_id), quantity: String(l.outstanding || 1), lot: l.lot_number ?? "", expiry: "", serials: "", condition: "good", over: "",
  })));
  const [note, setNote] = useState("");
  const [key, setKey] = useState(newIdempotencyKey);
  const update = (i: number, patch: Partial<ReceiveRow>) => setRows(rs => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const lineOf = (row: ReceiveRow) => receipt.lines.find(l => String(l.id) === row.line);
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/inbound/receipts/{receipt_id}/receive", {
      params: { path: { receipt_id: receipt.id }, header: { "Idempotency-Key": key } },
      body: {
        location_id: location ? Number(location) : null, note: note || null,
        lines: rows.filter(r => Number(r.quantity) > 0).map(r => ({
          line_id: r.line ? Number(r.line) : null, product_id: r.line ? null : Number(r.product), quantity: Number(r.quantity),
          lot_number: r.lot || null, expiry_date: r.expiry || null, condition: r.condition, over_reason: r.over || null,
          serial_numbers: r.serials.split(/[\s,،]+/).map(s => s.trim()).filter(Boolean),
        })),
      },
    })),
    onSuccess: () => { toast.success("دریافت کالا ثبت شد."); invalidate(); onClose(); },
    onError: e => { toast.error(errorMessage(e)); if (isServerError(e)) setKey(newIdempotencyKey()); },
  });

  return (
    <Modal open onClose={onClose} size="xl" title={`دریافت کالا — ${receipt.code}`} testId="receive-modal"
      description="مقدار شمارش‌شده هر کالا؛ کالای آسیب‌دیده را جدا با وضعیت «آسیب‌دیده» ثبت کنید. کالای نیازمند بازرسی «در انتظار بازرسی» می‌ماند."
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="receive-form" loading={save.isPending} data-testid="receive-save">ثبت دریافت</Button></>}>
      <form id="receive-form" className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="محل تخلیه" hint="انبار بدون محل تخلیه: بدون محل">
            <LocationSelect warehouseId={receipt.warehouse_id} value={location} onChange={setLocation} types={["receiving", "staging", "quarantine"]} empty="پیش‌فرض انبار" testId="receive-location" />
          </Field>
          <Field label="توضیح"><Input maxLength={500} value={note} onChange={e => setNote(e.target.value)} /></Field>
        </div>
        {rows.map((row, i) => {
          const line = lineOf(row);
          const product = products.find(p => String(p.id) === row.product);
          return (
            <div key={i} className="space-y-3 rounded-xl border border-border p-3" data-testid="receive-row">
              <div className="flex flex-wrap items-center justify-between gap-2">
                {line ? <div className="font-medium">{line.product_name} <span className="font-mono text-xs text-muted">{line.product_sku}</span>
                  <span className="ms-2 text-xs text-muted">انتظار {faNumber(line.expected_quantity)} · دریافت‌شده {faNumber(line.received_quantity)}</span></div> : (
                  <Select required value={row.product} onChange={e => update(i, { product: e.target.value })} data-testid="receive-product" searchable>
                    <option value="">کالای خارج از برنامه...</option>
                    {products.filter(p => p.is_active).map(p => <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>)}
                  </Select>
                )}
                <Button type="button" variant="ghost" size="icon" onClick={() => setRows(rows.filter((_, j) => j !== i))} aria-label="حذف"><Trash2 className="size-4" /></Button>
              </div>
              <div className="grid gap-3 sm:grid-cols-4">
                <Field label="تعداد شمارش‌شده"><Input type="number" min={1} required value={row.quantity} onChange={e => update(i, { quantity: e.target.value })} data-testid="receive-qty" /></Field>
                <Field label="وضعیت ظاهری">
                  <Select value={row.condition} onChange={e => update(i, { condition: e.target.value as ReceiveRow["condition"] })} data-testid="receive-condition">
                    <option value="good">سالم</option><option value="damaged">آسیب‌دیده هنگام تخلیه</option>
                  </Select>
                </Field>
                {(line?.lot_tracked ?? false) && <Field label="شماره بچ *"><Input required className="ltr uppercase" maxLength={64} value={row.lot} onChange={e => update(i, { lot: e.target.value })} data-testid="receive-lot" /></Field>}
                {(line?.expiry_tracked ?? false) && <Field label="تاریخ انقضا *"><DateField required value={row.expiry} onChange={v => update(i, { expiry: v })} testId="receive-expiry" /></Field>}
              </div>
              {(line?.serial_tracked ?? false) && (
                <Field label="شماره سریال‌ها *" hint="هر سریال در یک خط یا با فاصله؛ تعداد باید برابر مقدار باشد">
                  <Textarea required className="ltr font-mono" rows={2} value={row.serials} onChange={e => update(i, { serials: e.target.value })} />
                </Field>
              )}
              {(!line || (line.expected_quantity > 0 && line.received_quantity + Number(row.quantity) > line.expected_quantity)) && (
                <Field label={line ? "دلیل اضافه تحویل" : "دلیل پذیرش کالای خارج از برنامه *"} hint={line ? "بیش از تلورانس رسید فقط با دلیل پذیرفته می‌شود" : undefined}>
                  <Input required={!line && receipt.receipt_type !== "unexpected"} minLength={3} maxLength={300} value={row.over} onChange={e => update(i, { over: e.target.value })} data-testid="receive-over" />
                </Field>
              )}
              {product && !line && <p className="text-xs text-muted">واحد پایه: {product.unit}</p>}
            </div>
          );
        })}
        {receipt.receipt_type !== "transfer" && (
          <Button type="button" size="sm" variant="soft" icon={<Plus className="size-4" />} data-testid="receive-add"
            onClick={() => setRows([...rows, { line: "", product: "", quantity: "1", lot: "", expiry: "", serials: "", condition: "good", over: "" }])}>
            {receipt.receipt_type === "unexpected" ? "کالای دریافتی" : "کالای خارج از برنامه"}
          </Button>
        )}
      </form>
    </Modal>
  );
}

function CloseModal({ receipt, onClose }: { receipt: Receipt; onClose: () => void }) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const short = receipt.lines.filter(l => l.received_quantity < l.expected_quantity);
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/inbound/receipts/{receipt_id}/close", {
      params: { path: { receipt_id: receipt.id } },
      body: { note: note || null, reasons: Object.fromEntries(Object.entries(reasons).filter(([, v]) => v.trim().length >= 3)) },
    })),
    onSuccess: r => { toast.success(r.has_discrepancy ? "رسید با ثبت مغایرت بسته شد." : "رسید بسته شد."); invalidate(); onClose(); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <Modal open onClose={onClose} title={`بستن رسید ${receipt.code}`} testId="receipt-close-modal"
      description="بعد از بستن، دریافت جدید ثبت نمی‌شود؛ کسری، اضافه تحویل و کالای خارج از برنامه هر سطر ثبت می‌شود."
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="close-form" loading={save.isPending} data-testid="receipt-close-save">بستن رسید</Button></>}>
      <form id="close-form" className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        {short.map(l => (
          <Field key={l.id} label={`کسری «${l.product_name}»: ${faNumber(l.expected_quantity - l.received_quantity)} عدد`}>
            <Input minLength={3} maxLength={300} placeholder="مثلاً تأمین‌کننده کمتر فرستاد" value={reasons[l.id] ?? ""} onChange={e => setReasons(r => ({ ...r, [l.id]: e.target.value }))} data-testid="close-reason" />
          </Field>
        ))}
        <Field label={short.length ? "توضیح کلی (برای همه کسری‌های بدون دلیل)" : "توضیح"}><Input maxLength={500} value={note} onChange={e => setNote(e.target.value)} data-testid="close-note" /></Field>
      </form>
    </Modal>
  );
}
