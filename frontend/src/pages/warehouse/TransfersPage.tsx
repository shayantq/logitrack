/**
 * سفارش انتقال (فصل ۱۲): بین دو انبار یا دو محل یک انبار، دومرحله‌ای. «ارسال» کالا را از مبدأ کم و با وضعیت
 * «در راه» در مقصد ثبت می‌کند؛ «دریافت» آن را سالم یا آسیب‌دیده در محل مقصد می‌گذارد؛ کسری هنگام بستن تعیین تکلیف می‌شود.
 */
import { useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeftRight, Plus, Trash2 } from "lucide-react";
import { api, errorMessage, newIdempotencyKey, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { useProducts, useWarehouses } from "@/hooks/data";
import { TRANSFER_STATUS } from "@/lib/labels";
import { faDateTime, faNumber } from "@/lib/format";
import { confirmDialog } from "@/ui/dialogs";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, Select, Table, TableSkeleton } from "@/ui/primitives";
import { LocationSelect, useInvalidateOperations } from "./shared";

type Transfer = Schemas["TransferOut"];

export default function TransfersPage() {
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const { data: transfers, isLoading, error, refetch } = useQuery({
    queryKey: ["transfer-orders"], queryFn: () => unwrap(api.GET("/transfer-orders/")),
  });
  return (
    <>
      <PageHeader eyebrow="انبار" title="سفارش انتقال"
        subtitle="انتقال دومرحله‌ای بین انبارها یا محل‌ها: کالای ارسال‌شده تا دریافت «در راه» و قابل ردیابی است."
        actions={<Button icon={<Plus className="size-4" />} onClick={() => setCreating(true)} data-testid="transfer-new">سفارش انتقال</Button>} />
      <Card>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : !transfers?.length ? (
          <EmptyState icon={<ArrowLeftRight className="size-5" />} title="هنوز سفارش انتقالی نیست" />
        ) : (
          <Table testId="transfers-table">
            <thead><tr><th>کد</th><th>وضعیت</th><th>از</th><th>به</th><th>اقلام</th><th>در راه</th><th>زمان</th></tr></thead>
            <tbody>
              {transfers.map(t => (
                <tr key={t.id} className="cursor-pointer hover:bg-surface-2" onClick={() => setOpenId(t.id)} data-testid="transfer-row" data-code={t.code} data-status={t.status}>
                  <td className="whitespace-nowrap font-mono text-xs font-semibold ltr text-start">{t.code}</td>
                  <td><Badge tone={TRANSFER_STATUS[t.status]?.tone ?? "muted"} dot>{t.status_label}</Badge>{t.internal && <Badge className="ms-1">داخلی</Badge>}</td>
                  <td className="text-xs">{t.from_warehouse_name}{t.from_location_code ? ` · ${t.from_location_code}` : ""}</td>
                  <td className="text-xs">{t.to_warehouse_name}{t.to_location_code ? ` · ${t.to_location_code}` : ""}</td>
                  <td className="text-xs">{t.lines.map(l => `${l.product_name} × ${faNumber(l.quantity)}`).join("، ")}</td>
                  <td className="tnum">{faNumber(t.lines.reduce((s, l) => s + l.in_transit, 0))}</td>
                  <td className="whitespace-nowrap text-xs text-text-2">{faDateTime(t.shipped_at ?? t.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {creating && <NewTransferModal onClose={() => setCreating(false)} onCreated={setOpenId} />}
      <TransferModal id={openId} onClose={() => setOpenId(null)} />
    </>
  );
}

function NewTransferModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: number) => void }) {
  const me = useMe();
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const { data: warehouses = [] } = useWarehouses();
  const { data: products = [] } = useProducts();
  const stock = warehouses.filter(w => w.holds_stock && w.type !== "transit");
  const [form, setForm] = useState({ from: me.role === "warehouse_manager" ? String(me.warehouse_id ?? "") : "", to: "", fromLoc: "", toLoc: "", note: "" });
  const [lines, setLines] = useState([{ product: "", quantity: "1" }]);
  const [key] = useState(newIdempotencyKey);
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/transfer-orders/", { params: { header: { "Idempotency-Key": key } }, body: {
      from_warehouse_id: Number(form.from), to_warehouse_id: Number(form.to), from_location_id: form.fromLoc ? Number(form.fromLoc) : null,
      to_location_id: form.toLoc ? Number(form.toLoc) : null, note: form.note || null,
      lines: lines.filter(l => l.product).map(l => ({ product_id: Number(l.product), quantity: Number(l.quantity) })) } })),
    onSuccess: t => { toast.success(`سفارش انتقال ${t.code} ثبت شد.`); invalidate(); onClose(); onCreated(t.id); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <Modal open onClose={onClose} size="lg" title="سفارش انتقال جدید" testId="transfer-form"
      description="مبدأ و مقصد یکسان = انتقال داخلی دومرحله‌ای بین دو محل."
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="transfer-form-el" loading={save.isPending} data-testid="transfer-save">ثبت</Button></>}>
      <form id="transfer-form-el" className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="انبار مبدأ">
            <Select required value={form.from} disabled={me.role === "warehouse_manager"} onChange={e => setForm(f => ({ ...f, from: e.target.value, fromLoc: "" }))} data-testid="transfer-from">
              <option value="">انتخاب...</option>{stock.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          </Field>
          <Field label="انبار مقصد">
            <Select required value={form.to} onChange={e => setForm(f => ({ ...f, to: e.target.value, toLoc: "" }))} data-testid="transfer-to">
              <option value="">انتخاب...</option>{stock.filter(w => w.is_active).map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          </Field>
          <Field label="محل مبدأ" hint="خالی = برداشت خودکار FEFO">
            <LocationSelect warehouseId={form.from ? Number(form.from) : null} value={form.fromLoc} onChange={v => setForm(f => ({ ...f, fromLoc: v }))} empty="خودکار" testId="transfer-from-loc" />
          </Field>
          <Field label="محل دریافت در مقصد">
            <LocationSelect warehouseId={form.to ? Number(form.to) : null} value={form.toLoc} onChange={v => setForm(f => ({ ...f, toLoc: v }))} testId="transfer-to-loc" />
          </Field>
        </div>
        {lines.map((l, i) => (
          <div key={i} className="grid items-end gap-2 sm:grid-cols-[1fr_8rem_auto]">
            <Select required value={l.product} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, product: e.target.value } : x))} searchable data-testid="transfer-product">
              <option value="">انتخاب کالا...</option>{products.map(p => <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>)}
            </Select>
            <Input type="number" min={1} required value={l.quantity} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, quantity: e.target.value } : x))} aria-label="تعداد" data-testid="transfer-qty" />
            <Button type="button" variant="ghost" size="icon" disabled={lines.length === 1} onClick={() => setLines(lines.filter((_, j) => j !== i))} aria-label="حذف"><Trash2 className="size-4" /></Button>
          </div>
        ))}
        <Button type="button" size="sm" variant="soft" icon={<Plus className="size-4" />} onClick={() => setLines([...lines, { product: "", quantity: "1" }])}>کالای دیگر</Button>
        <Field label="توضیح"><Input maxLength={500} value={form.note} onChange={e => setForm(f => ({ ...f, note: e.target.value }))} /></Field>
      </form>
    </Modal>
  );
}

function TransferModal({ id, onClose }: { id: number | null; onClose: () => void }) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const [receiving, setReceiving] = useState(false);
  const [closing, setClosing] = useState(false);
  const { data: t } = useQuery({
    queryKey: ["transfer-order", id],
    queryFn: () => unwrap(api.GET("/transfer-orders/{transfer_id}", { params: { path: { transfer_id: id! } } })),
    enabled: id != null,
  });
  const action = useMutation({
    mutationFn: (kind: "ship" | "cancel") => kind === "ship"
      ? unwrap(api.POST("/transfer-orders/{transfer_id}/ship", { params: { path: { transfer_id: id! }, header: { "Idempotency-Key": newIdempotencyKey() } } }))
      : unwrap(api.POST("/transfer-orders/{transfer_id}/cancel", { params: { path: { transfer_id: id! } } })),
    onSuccess: r => { toast.success(r.status === "in_transit" ? `${r.code} ارسال شد؛ کالا «در راه» است.` : "سفارش انتقال لغو شد."); invalidate(); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <>
      <Modal open={id != null} onClose={onClose} size="lg" testId="transfer-detail"
        title={t ? <span className="flex items-center gap-2"><span className="font-mono ltr">{t.code}</span><Badge tone={TRANSFER_STATUS[t.status]?.tone ?? "muted"} dot>{t.status_label}</Badge></span> : "سفارش انتقال"}
        description={t && `${t.from_warehouse_name} ← ${t.to_warehouse_name}${t.to_location_code ? ` (${t.to_location_code})` : ""}`}
        footer={t && <>
          {t.status === "open" && <><Button variant="ghost" onClick={() => action.mutate("cancel")}>لغو</Button>
            <Button loading={action.isPending} onClick={() => confirmDialog({ title: `ارسال ${t.code}؟`, text: "کالا از مبدأ کم و تا دریافت «در راه» می‌شود.", confirmLabel: "ارسال" }).then(ok => ok && action.mutate("ship"))} data-testid="transfer-ship">ارسال</Button></>}
          {t.status === "in_transit" && <Button onClick={() => setReceiving(true)} data-testid="transfer-receive">دریافت در مقصد</Button>}
          {(t.status === "in_transit" || t.status === "received") && <Button variant="secondary" onClick={() => setClosing(true)} data-testid="transfer-close">بستن</Button>}
        </>}>
        {!t ? <div className="h-32 animate-pulse rounded-xl bg-surface-2" /> : (
          <div className="overflow-x-auto">
            <table className="table-base" data-testid="transfer-lines">
              <thead><tr><th>کالا</th><th>مقدار</th><th>ارسال</th><th>دریافت سالم</th><th>آسیب‌دیده</th><th>کسری بسته‌شده</th><th>در راه</th></tr></thead>
              <tbody>{t.lines.map(l => (
                <tr key={l.id} data-testid="transfer-line" data-in-transit={l.in_transit}>
                  <td><div className="font-medium">{l.product_name}</div>{l.discrepancy_reason && <div className="text-xs text-muted">{l.discrepancy_reason}</div>}</td>
                  <td className="tnum">{faNumber(l.quantity)}</td><td className="tnum">{faNumber(l.shipped_quantity)}</td>
                  <td className="tnum text-success">{faNumber(l.received_quantity)}</td><td className="tnum text-danger">{faNumber(l.damaged_quantity)}</td>
                  <td className="tnum">{faNumber(l.resolved_quantity)}</td><td className="tnum font-bold">{faNumber(l.in_transit)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </Modal>
      {t && receiving && <ReceiveModal transfer={t} onClose={() => setReceiving(false)} />}
      {t && closing && <CloseModal transfer={t} onClose={() => setClosing(false)} />}
    </>
  );
}

function ReceiveModal({ transfer, onClose }: { transfer: Transfer; onClose: () => void }) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const [location, setLocation] = useState(transfer.to_location_id ? String(transfer.to_location_id) : "");
  const [rows, setRows] = useState(transfer.lines.map(l => ({ id: l.id, good: String(l.in_transit), damaged: "0", reason: "" })));
  const [key] = useState(newIdempotencyKey);
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/transfer-orders/{transfer_id}/receive", {
      params: { path: { transfer_id: transfer.id }, header: { "Idempotency-Key": key } },
      body: { location_id: location ? Number(location) : null, lines: rows.map(r => ({
        line_id: r.id, received_quantity: Number(r.good) || 0, damaged_quantity: Number(r.damaged) || 0, reason: r.reason || null })) } })),
    onSuccess: () => { toast.success("دریافت ثبت شد."); invalidate(); onClose(); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <Modal open onClose={onClose} size="lg" title={`دریافت ${transfer.code}`} testId="transfer-receive-modal"
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="transfer-receive-form" loading={save.isPending} data-testid="transfer-receive-save">ثبت دریافت</Button></>}>
      <form id="transfer-receive-form" className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        <Field label="محل دریافت"><LocationSelect warehouseId={transfer.to_warehouse_id} value={location} onChange={setLocation} /></Field>
        {transfer.lines.map((l, i) => (
          <div key={l.id} className="grid items-end gap-2 rounded-xl border border-border p-3 sm:grid-cols-[1fr_6rem_6rem_1fr]">
            <div className="text-sm font-medium">{l.product_name}<div className="text-xs text-muted">در راه: {faNumber(l.in_transit)}</div></div>
            <Field label="سالم"><Input type="number" min={0} max={l.in_transit} value={rows[i].good} onChange={e => setRows(rows.map((r, j) => j === i ? { ...r, good: e.target.value } : r))} data-testid="transfer-good" /></Field>
            <Field label="آسیب‌دیده"><Input type="number" min={0} max={l.in_transit} value={rows[i].damaged} onChange={e => setRows(rows.map((r, j) => j === i ? { ...r, damaged: e.target.value } : r))} data-testid="transfer-damaged" /></Field>
            <Field label="شرح آسیب"><Input maxLength={300} value={rows[i].reason} onChange={e => setRows(rows.map((r, j) => j === i ? { ...r, reason: e.target.value } : r))} /></Field>
          </div>
        ))}
      </form>
    </Modal>
  );
}

function CloseModal({ transfer, onClose }: { transfer: Transfer; onClose: () => void }) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const missing = transfer.lines.reduce((s, l) => s + l.in_transit, 0);
  const [resolution, setResolution] = useState<"write_off" | "return">("write_off");
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/transfer-orders/{transfer_id}/close", { params: { path: { transfer_id: transfer.id } },
      body: { resolution, reason: reason || null } })),
    onSuccess: () => { toast.success("سفارش انتقال بسته شد."); invalidate(); onClose(); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <Modal open onClose={onClose} title={`بستن ${transfer.code}`} testId="transfer-close-modal"
      description={missing ? `${faNumber(missing)} عدد هنوز «در راه» است و باید تعیین تکلیف شود.` : "همه اقلام دریافت شده است."}
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="transfer-close-form" loading={save.isPending} data-testid="transfer-close-save">بستن</Button></>}>
      <form id="transfer-close-form" className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        {missing > 0 && <>
          <Field label="تکلیف کسری">
            <Select value={resolution} onChange={e => setResolution(e.target.value as "write_off" | "return")}>
              <option value="write_off">ضایعات (کسری حمل)</option><option value="return">برگشت به انبار مبدأ</option>
            </Select>
          </Field>
          <Field label="دلیل *"><Input required minLength={3} maxLength={500} value={reason} onChange={e => setReason(e.target.value)} data-testid="transfer-close-reason" /></Field>
        </>}
      </form>
    </Modal>
  );
}
