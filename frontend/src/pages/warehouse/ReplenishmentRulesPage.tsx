/**
 * تأمین مجدد محل برداشت و ABC (فصل ۱۳): حداقل/حداکثر هر کالا در هر محل برداشت — زیر حداقل، وظیفه «تأمین مجدد»
 * از قفسه نگهداری (اجرا در صفحه جانمایی با اسکن). طبقه‌بندی ABC از ارزش مصرف و سررسید شمارش دوره‌ای هر کالا.
 */
import { useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { BarChart3, Plus, RefreshCw, Repeat, Trash2 } from "lucide-react";
import { api, errorMessage, unwrap } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { useProducts } from "@/hooks/data";
import { faDate, faNumber } from "@/lib/format";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, PageHeader, Select, Table, TableSkeleton, type Tone } from "@/ui/primitives";
import { LocationSelect, WarehousePicker, useInvalidateOperations, useWarehouseChoice } from "./shared";

const ABC_TONE: Record<string, Tone> = { A: "danger", B: "warning", C: "muted" };

export default function ReplenishmentRulesPage() {
  const me = useMe();
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const choice = useWarehouseChoice();
  const warehouseId = choice.value ? Number(choice.value) : null;
  const [creating, setCreating] = useState(false);
  const rules = useQuery({
    queryKey: ["replenishment-rules", warehouseId],
    queryFn: () => unwrap(api.GET("/replenishment-rules/", { params: { query: { warehouse_id: warehouseId } } })),
    enabled: !!warehouseId,
  });
  const abc = useQuery({
    queryKey: ["abc", warehouseId],
    queryFn: () => unwrap(api.GET("/replenishment-rules/abc", { params: { query: { warehouse_id: warehouseId } } })),
    enabled: !!warehouseId,
  });
  const generate = useMutation({
    mutationFn: () => unwrap(api.POST("/replenishment-rules/generate", { params: { query: { warehouse_id: warehouseId } } })),
    onSuccess: r => { toast.success(r.quantity ? `وظیفه تأمین مجدد برای ${faNumber(r.quantity)} عدد ساخته شد.` : "هیچ محلی زیر حداقل نیست."); invalidate(); rules.refetch(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE("/replenishment-rules/{rule_id}", { params: { path: { rule_id: id } } })),
    onSuccess: () => rules.refetch(),
    onError: e => toast.error(errorMessage(e)),
  });
  const classify = useMutation({
    mutationFn: () => unwrap(api.POST("/replenishment-rules/abc", { body: { days: 365 } })),
    onSuccess: r => { toast.success(`ABC: ${faNumber(r.A)} کالای A، ${faNumber(r.B)} کالای B، ${faNumber(r.C)} کالای C`); abc.refetch(); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <>
      <PageHeader eyebrow="انبار" title="تأمین مجدد و ABC"
        subtitle="محل‌های برداشت زیر حداقل خودکار از قفسه نگهداری پر می‌شوند؛ کلاس ABC دوره شمارش هر کالا را تعیین می‌کند." />
      <div className="mb-4 w-64"><WarehousePicker choice={choice} /></div>
      <Card className="mb-5">
        <CardHeader title="حداقل/حداکثر محل‌های برداشت" icon={<Repeat className="size-4" />}
          actions={<div className="flex gap-2">
            <Button size="sm" variant="secondary" icon={<RefreshCw className="size-4" />} loading={generate.isPending} onClick={() => generate.mutate()} data-testid="replenish-generate">بررسی و ساخت وظایف</Button>
            <Button size="sm" icon={<Plus className="size-4" />} onClick={() => setCreating(true)} data-testid="rule-new">قاعده جدید</Button>
          </div>} />
        {rules.isLoading ? <TableSkeleton /> : !rules.data?.length ? <EmptyState title="قاعده‌ای تعریف نشده" text="برای هر کالا در هر محل برداشت حداقل و حداکثر تعیین کنید." /> : (
          <Table testId="rules-table">
            <thead><tr><th>محل</th><th>کالا</th><th>حداقل / حداکثر</th><th>موجود</th><th>در راه (وظیفه)</th><th>وضعیت</th><th className="w-1" /></tr></thead>
            <tbody>{rules.data.map(r => (
              <tr key={r.id} data-testid="rule-row" data-needs={r.needs_replenishment}>
                <td className="font-mono text-xs font-semibold ltr text-start">{r.location_code}</td>
                <td>{r.product_name}<div className="font-mono text-xs text-muted">{r.product_sku}</div></td>
                <td className="tnum">{faNumber(r.min_quantity)} / {faNumber(r.max_quantity)}</td>
                <td className="tnum">{faNumber(r.current_quantity)}</td><td className="tnum">{faNumber(r.pending_quantity)}</td>
                <td>{!r.is_active ? <Badge>غیرفعال</Badge> : r.needs_replenishment ? <Badge tone="warning">زیر حداقل</Badge> : <Badge tone="success">کافی</Badge>}</td>
                <td><Button size="icon" variant="ghost" aria-label="حذف" onClick={() => remove.mutate(r.id)}><Trash2 className="size-4" /></Button></td>
              </tr>
            ))}</tbody>
          </Table>
        )}
      </Card>
      <Card>
        <CardHeader title="طبقه‌بندی ABC و شمارش دوره‌ای" icon={<BarChart3 className="size-4" />}
          subtitle="A: ۸۰٪ ارزش مصرف (شمارش هر ۳۰ روز)، B: ۱۵٪ بعدی (۹۰ روز)، C: بقیه (۱۸۰ روز)."
          actions={me.role === "org_admin" && <Button size="sm" variant="secondary" loading={classify.isPending} onClick={() => classify.mutate()} data-testid="abc-run">محاسبه دوباره</Button>} />
        {abc.isLoading ? <TableSkeleton /> : !abc.data?.length ? <EmptyState title="کالایی نیست" /> : (
          <Table testId="abc-table">
            <thead><tr><th>کلاس</th><th>کالا</th><th>ارزش مصرف (ریال)</th><th>سهم</th><th>آخرین شمارش</th><th>شمارش بعدی</th></tr></thead>
            <tbody>{abc.data.map(r => (
              <tr key={r.product_id} data-testid="abc-row" data-class={r.abc_class ?? ""}>
                <td>{r.abc_class ? <Badge tone={ABC_TONE[r.abc_class]}>{r.abc_class}</Badge> : <span className="text-xs text-muted">—</span>}</td>
                <td>{r.product_name}<div className="font-mono text-xs text-muted">{r.product_sku}</div></td>
                <td className="tnum">{faNumber(r.consumption_value)}</td><td className="tnum">{faNumber(r.share)}٪</td>
                <td className="text-xs">{r.last_counted_at ? faDate(r.last_counted_at) : "هرگز"}</td>
                <td className="text-xs">{r.count_due ? <Badge tone="warning">سررسید شمارش</Badge> : faDate(r.next_count_due)}</td>
              </tr>
            ))}</tbody>
          </Table>
        )}
      </Card>
      {creating && warehouseId && <RuleModal warehouseId={warehouseId} onClose={() => { setCreating(false); rules.refetch(); }} />}
    </>
  );
}

function RuleModal({ warehouseId, onClose }: { warehouseId: number; onClose: () => void }) {
  const toast = useToast();
  const { data: products = [] } = useProducts();
  const [form, setForm] = useState({ location: "", product: "", min: "2", max: "10" });
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/replenishment-rules/", { body: {
      location_id: Number(form.location), product_id: Number(form.product), min_quantity: Number(form.min), max_quantity: Number(form.max), is_active: true } })),
    onSuccess: () => { toast.success("قاعده ثبت شد."); onClose(); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <Modal open onClose={onClose} title="قاعده تأمین مجدد" testId="rule-modal"
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="rule-form" loading={save.isPending} data-testid="rule-save">ثبت</Button></>}>
      <form id="rule-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        <Field label="محل برداشت"><LocationSelect warehouseId={warehouseId} value={form.location} onChange={v => setForm(f => ({ ...f, location: v }))} types={["picking"]} empty="انتخاب کنید..." required testId="rule-location" /></Field>
        <Field label="کالا">
          <Select required value={form.product} onChange={e => setForm(f => ({ ...f, product: e.target.value }))} searchable data-testid="rule-product">
            <option value="">انتخاب کالا...</option>{products.map(p => <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>)}
          </Select>
        </Field>
        <Field label="حداقل"><Input type="number" min={0} required value={form.min} onChange={e => setForm(f => ({ ...f, min: e.target.value }))} /></Field>
        <Field label="حداکثر"><Input type="number" min={1} required value={form.max} onChange={e => setForm(f => ({ ...f, max: e.target.value }))} /></Field>
      </form>
    </Modal>
  );
}
