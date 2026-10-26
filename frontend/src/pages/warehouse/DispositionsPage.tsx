/**
 * تعیین تکلیف کالای مرجوعی و معیوب (فصل ۱۵): کالای مردود، معیوب، آسیب‌دیده، قرنطینه یا در تعمیر امحا، تعمیر،
 * به تأمین‌کننده برگشت یا دوباره بازرسی می‌شود — هر تصمیم با سند انبار، دلیل و انجام‌دهنده در سابقه می‌ماند.
 */
import { useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Recycle } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useToast } from "@/components/Toast";
import { usePartners } from "@/hooks/data";
import { DISPOSITION_ACTIONS, STOCK_STATUS, type StockStatus } from "@/lib/labels";
import { faDateTime, faNumber } from "@/lib/format";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, PageHeader, SegmentedControl, Select, Table, TableSkeleton } from "@/ui/primitives";
import { StatusBadge, WarehousePicker, useInvalidateOperations, useWarehouseChoice } from "./shared";

type Balance = Schemas["StockBalanceOut"];
const HELD: StockStatus[] = ["rejected", "defective", "damaged", "quarantine", "repair"];

export default function DispositionsPage() {
  const choice = useWarehouseChoice();
  const warehouseId = choice.value ? Number(choice.value) : null;
  const [status, setStatus] = useState<StockStatus>("rejected");
  const [target, setTarget] = useState<Balance | null>(null);
  const balances = useQuery({
    queryKey: ["balances", "held", warehouseId, status],
    queryFn: () => unwrap(api.GET("/inventory/balances", { params: { query: { warehouse_id: warehouseId, stock_status: status } } })),
    enabled: !!warehouseId,
  });
  const history = useQuery({
    queryKey: ["dispositions", warehouseId],
    queryFn: () => unwrap(api.GET("/dispositions/", { params: { query: { warehouse_id: warehouseId } } })),
    enabled: !!warehouseId,
  });
  return (
    <>
      <PageHeader eyebrow="انبار" title="تعیین تکلیف مرجوعی و معیوب"
        subtitle="امحا، تعمیر، برگشت به تأمین‌کننده یا بازرسی دوباره — هر تصمیم سند انبار دارد و حذف نمی‌شود." />
      <Card className="mb-5">
        <div className="flex flex-wrap items-center gap-3 border-b border-border p-4">
          <div className="w-64"><WarehousePicker choice={choice} /></div>
          <SegmentedControl value={status} onChange={setStatus} options={HELD.map(s => ({ value: s, label: STOCK_STATUS[s].label }))} />
        </div>
        {balances.isLoading ? <TableSkeleton /> : !balances.data?.length ? (
          <EmptyState icon={<Recycle className="size-5" />} title={`کالای «${STOCK_STATUS[status].label}» نیست`} />
        ) : (
          <Table testId="held-table">
            <thead><tr><th>کالا</th><th>وضعیت</th><th>محل</th><th>بچ</th><th>مقدار</th><th className="w-1" /></tr></thead>
            <tbody>{balances.data.map(b => (
              <tr key={b.balance_id} data-testid="held-row" data-sku={b.product_sku}>
                <td>{b.product_name}<div className="font-mono text-xs text-muted">{b.product_sku}</div></td>
                <td><StatusBadge status={b.stock_status} /></td>
                <td className="font-mono text-xs ltr text-start">{b.location_code ?? "بدون محل"}</td>
                <td className="font-mono text-xs ltr text-start">{b.lot_number ?? "—"}</td>
                <td className="tnum font-bold">{faNumber(b.quantity)}</td>
                <td><Button size="sm" variant="soft" onClick={() => setTarget(b)} data-testid="held-dispose">تعیین تکلیف</Button></td>
              </tr>
            ))}</tbody>
          </Table>
        )}
      </Card>
      <Card>
        <CardHeader title="سوابق تعیین تکلیف" icon={<Recycle className="size-4" />} />
        {!history.data?.length ? <EmptyState title="هنوز تصمیمی ثبت نشده" /> : (
          <Table testId="dispositions-table">
            <thead><tr><th>کد / سند</th><th>تصمیم</th><th>کالا</th><th>از وضعیت</th><th>مقدار</th><th>دلیل</th><th>کاربر</th><th>زمان</th></tr></thead>
            <tbody>{history.data.map(d => (
              <tr key={d.id} data-testid="disposition-row" data-action={d.action}>
                <td><div className="font-mono text-xs font-semibold ltr text-start">{d.code}</div><div className="font-mono text-[11px] text-muted ltr text-start">{d.document_code}</div></td>
                <td><Badge tone={DISPOSITION_ACTIONS[d.action]?.tone ?? "muted"}>{d.action_label}</Badge>{d.partner_name && <div className="text-xs text-muted">{d.partner_name}</div>}</td>
                <td>{d.product_name}</td><td><StatusBadge status={d.from_status} /></td>
                <td className="tnum">{faNumber(d.quantity)}</td><td className="max-w-56 text-xs text-text-2">{d.reason}</td>
                <td className="text-xs">{d.created_by_name ?? "—"}</td><td className="whitespace-nowrap text-xs text-text-2">{faDateTime(d.created_at)}</td>
              </tr>
            ))}</tbody>
          </Table>
        )}
      </Card>
      {target && <DisposeModal balance={target} onClose={() => setTarget(null)} />}
    </>
  );
}

function DisposeModal({ balance, onClose }: { balance: Balance; onClose: () => void }) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const { data: suppliers = [] } = usePartners("supplier");
  const { data: receipts = [] } = useQuery({
    queryKey: ["receipts", "purchase", balance.warehouse_id],
    queryFn: () => unwrap(api.GET("/inbound/receipts", { params: { query: { warehouse_id: balance.warehouse_id, receipt_type: "purchase", limit: 100 } } })),
  });
  const [form, setForm] = useState({ action: "scrap", quantity: String(balance.quantity), partner: "", receipt: "", reason: "" });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm(f => ({ ...f, [k]: e.target.value }));
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/dispositions/", { body: {
      product_id: balance.product_id, warehouse_id: balance.warehouse_id, from_status: balance.stock_status as StockStatus,
      action: form.action as Schemas["DispositionCreate"]["action"], quantity: Number(form.quantity),
      location_id: balance.location_id ?? null, lot_number: balance.lot_number ?? null,
      partner_id: form.partner ? Number(form.partner) : null, receipt_id: form.receipt ? Number(form.receipt) : null, reason: form.reason } })),
    onSuccess: d => { toast.success(`${d.action_label} ثبت شد (${d.document_code}).`); invalidate(); onClose(); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <Modal open onClose={onClose} title={`تعیین تکلیف — ${balance.product_name}`} testId="dispose-modal"
      description={`${faNumber(balance.quantity)} عدد «${STOCK_STATUS[balance.stock_status as StockStatus]?.label}»${balance.location_code ? ` در ${balance.location_code}` : ""}`}
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="dispose-form" loading={save.isPending} data-testid="dispose-save">ثبت تصمیم</Button></>}>
      <form id="dispose-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        <Field label="تصمیم" hint={DISPOSITION_ACTIONS[form.action]?.hint} className="sm:col-span-2">
          <Select value={form.action} onChange={set("action")} data-testid="dispose-action">
            {Object.entries(DISPOSITION_ACTIONS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
        </Field>
        <Field label="مقدار"><Input type="number" min={1} max={balance.quantity} required value={form.quantity} onChange={set("quantity")} /></Field>
        {form.action === "return_to_supplier" && <>
          <Field label="تأمین‌کننده *">
            <Select required value={form.partner} onChange={set("partner")}><option value="">انتخاب...</option>{suppliers.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</Select>
          </Field>
          <Field label="رسید خرید مرجع" hint="اختیاری — سقف برگشت از همان رسید" className="sm:col-span-2">
            <Select value={form.receipt} onChange={set("receipt")}><option value="">—</option>
              {receipts.filter(r => !form.partner || String(r.partner_id) === form.partner).map(r => <option key={r.id} value={r.id}>{r.code}{r.external_ref ? ` · ${r.external_ref}` : ""}</option>)}</Select>
          </Field>
        </>}
        <Field label="دلیل *" className="sm:col-span-2"><Input required minLength={3} maxLength={500} value={form.reason} onChange={set("reason")} data-testid="dispose-reason" /></Field>
      </form>
    </Modal>
  );
}
