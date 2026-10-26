/**
 * ارزش‌گذاری و سلامت موجودی (فصل ۱۷): ارزش هر کالا به سه روش (FIFO، میانگین موزون، استاندارد) کنار هم، بهای کالای
 * فروش رفته، و کالای کم‌گردش/راکد/بی‌فروش و نزدیک به انقضا. روش ارزش‌گذاری مالی مستقل از قاعده برداشت فیزیکی (FEFO) است.
 */
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Gem, Settings2, Timer } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useCan } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { faDate, faNumber } from "@/lib/format";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Field, Input, PageHeader, SegmentedControl, Select, StatCard, Table, TableSkeleton, cn } from "@/ui/primitives";
import { faMoneyShort } from "../reports/period";
import { WarehousePicker, useWarehouseChoice } from "../warehouse/shared";

const HEALTH: Record<string, { label: string; tone: "warning" | "danger" | "muted" | "success" }> = {
  slow: { label: "کم‌گردش", tone: "warning" }, dead: { label: "راکد", tone: "danger" }, no_sales: { label: "بی‌فروش", tone: "muted" },
  active: { label: "فعال", tone: "success" },
};

export default function ValuationPage() {
  const [tab, setTab] = useState<"value" | "health">("value");
  const choice = useWarehouseChoice(null, false);
  const warehouseId = choice.value ? Number(choice.value) : null;
  const manage = useCan("valuation.manage");
  const [settingsOpen, setSettingsOpen] = useState(false);
  return (
    <>
      <PageHeader eyebrow="گزارش‌ها" title="ارزش‌گذاری و کالای راکد"
        subtitle="ارزش مالی موجودی به سه روش و سلامت انبار — روش مالی جدا از قاعده برداشت فیزیکی (اول‌منقضی، اول‌خروج) است"
        actions={manage && <Button variant="secondary" size="sm" icon={<Settings2 className="size-4" />} onClick={() => setSettingsOpen(true)} data-testid="valuation-settings">روش و آستانه‌ها</Button>} />
      <Card className="mb-5 flex flex-wrap items-center gap-3 p-4">
        <SegmentedControl value={tab} onChange={setTab} options={[{ value: "value", label: "ارزش‌گذاری" }, { value: "health", label: "راکد و انقضا" }]} />
        <div className="w-56"><WarehousePicker choice={choice} allowAll testId="valuation-warehouse" /></div>
      </Card>
      {tab === "value" ? <ValueTab warehouseId={warehouseId} /> : <HealthTab warehouseId={warehouseId} />}
      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
    </>
  );
}

function ValueTab({ warehouseId }: { warehouseId: number | null }) {
  const q = useQuery({
    queryKey: ["valuation", warehouseId],
    queryFn: () => unwrap(api.GET("/valuation/", { params: { query: { warehouse_id: warehouseId } } })),
  });
  if (q.isLoading) return <TableSkeleton />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const d = q.data;
  const label = (m: string) => d.methods.find(x => x.code === m)?.label ?? m;
  return (
    <>
      <div className="mb-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="valuation-totals">
        <StatCard label={`ارزش موجودی — ${label(d.method)}`} value={faMoneyShort(d.selected_total)} tone="brand" hint="روش جاری سازمان" icon={<Gem className="size-5" />} />
        {(["fifo", "weighted_average", "standard"] as const).filter(m => m !== d.method).map(m => (
          <StatCard key={m} label={label(m)} value={faMoneyShort(d.totals[m])} tone="muted"
            hint={`اختلاف با روش جاری: ${faMoneyShort(d.totals[m] - d.selected_total)}`} />
        ))}
        <StatCard label="بهای فروش رفته (۳۰ روز)" value={faMoneyShort(d.cogs[d.method as "fifo"] ?? d.cogs.weighted_average)} tone="violet"
          hint={`FIFO ${faMoneyShort(d.cogs.fifo)} · میانگین ${faMoneyShort(d.cogs.weighted_average)}`} />
      </div>
      {d.estimated_items > 0 && <p className="mb-4 rounded-xl bg-warning-soft/60 px-4 py-2.5 text-sm text-text-2">
        {faNumber(d.estimated_items)} کالا بهای تمام‌شده ثبت‌شده ندارد و با قیمت فروش تخمین زده شده (علامت «تخمینی»).</p>}
      <Card>
        {!d.items.length ? <EmptyState icon={<Gem className="size-5" />} title="موجودی‌ای برای ارزش‌گذاری نیست" /> : (
          <Table testId="valuation-table">
            <thead><tr><th>کالا</th><th>ABC</th><th>مقدار</th><th>بهای واحد FIFO</th><th>بهای واحد میانگین</th>
              <th className={cn(d.method === "fifo" && "text-brand")}>ارزش FIFO</th><th className={cn(d.method === "weighted_average" && "text-brand")}>ارزش میانگین</th>
              <th className={cn(d.method === "standard" && "text-brand")}>ارزش استاندارد</th></tr></thead>
            <tbody>{d.items.map(r => (
              <tr key={r.product_id} data-testid="valuation-row">
                <td>{r.product_name}<div className="font-mono text-xs text-muted">{r.sku}{r.estimated && <Badge tone="warning" className="ms-1">تخمینی</Badge>}</div></td>
                <td>{r.abc_class ? <Badge tone={r.abc_class === "A" ? "danger" : r.abc_class === "B" ? "warning" : "muted"}>{r.abc_class}</Badge> : "—"}</td>
                <td className="tnum">{faNumber(r.quantity)}</td>
                <td className="tnum text-xs">{faNumber(r.unit_cost.fifo)}</td><td className="tnum text-xs">{faNumber(r.unit_cost.weighted_average)}</td>
                {(["fifo", "weighted_average", "standard"] as const).map(m => (
                  <td key={m} className={cn("tnum", m === d.method ? "font-bold text-text" : "text-text-2")}>{faNumber(r.value[m])}</td>
                ))}
              </tr>
            ))}</tbody>
          </Table>
        )}
      </Card>
    </>
  );
}

function HealthTab({ warehouseId }: { warehouseId: number | null }) {
  const q = useQuery({
    queryKey: ["valuation-health", warehouseId],
    queryFn: () => unwrap(api.GET("/valuation/health", { params: { query: { warehouse_id: warehouseId } } })),
  });
  if (q.isLoading) return <TableSkeleton />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const d = q.data;
  return (
    <>
      <div className="mb-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="health-buckets">
        {d.buckets.map(b => (
          <StatCard key={b.status} label={HEALTH[b.status].label} value={faNumber(b.count)} tone={HEALTH[b.status].tone}
            hint={`ارزش ${faMoneyShort(b.value)}`} />
        ))}
      </div>
      <p className="mb-4 text-xs text-muted">کم‌گردش: بی‌فروش بیش از {faNumber(d.settings.slow_days)} روز · راکد: بیش از {faNumber(d.settings.dead_days)} روز ·
        هشدار انقضا: {faNumber(d.settings.expiry_warning_days)} روز آینده</p>
      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader title="کم‌گردش، راکد و بی‌فروش" icon={<Timer className="size-4" />} />
          {!d.items.length ? <EmptyState title="همه کالاها گردش دارند ✓" /> : (
            <Table testId="health-table">
              <thead><tr><th>کالا</th><th>وضعیت</th><th>مقدار</th><th>ارزش</th><th>بی‌گردشی</th></tr></thead>
              <tbody>{d.items.map(i => (
                <tr key={i.product_id} data-testid="health-row" data-status={i.status}>
                  <td>{i.product_name}<div className="font-mono text-xs text-muted">{i.sku}</div></td>
                  <td><Badge tone={HEALTH[i.status].tone}>{HEALTH[i.status].label}</Badge></td>
                  <td className="tnum">{faNumber(i.quantity)}</td><td className="tnum text-xs">{faNumber(i.value)}</td>
                  <td className="text-xs">{i.idle_days !== null && i.idle_days !== undefined ? `${faNumber(i.idle_days)} روز` : "—"}
                    <div className="text-muted">{i.last_sale_at ? `آخرین فروش ${faDate(i.last_sale_at)}` : "هرگز فروش نرفته"}</div></td>
                </tr>
              ))}</tbody>
            </Table>
          )}
        </Card>
        <Card>
          <CardHeader title="نزدیک به انقضا و منقضی" subtitle={`منقضی ${faMoneyShort(d.expired_value)} · نزدیک ${faMoneyShort(d.expiring_value)}`} icon={<Timer className="size-4" />} tone="danger" />
          {!d.expiring.length ? <EmptyState title="بچ نزدیک به انقضایی نیست ✓" /> : (
            <Table testId="expiry-table">
              <thead><tr><th>کالا / بچ</th><th>انبار / محل</th><th>انقضا</th><th>مقدار</th><th>ارزش</th></tr></thead>
              <tbody>{d.expiring.map((e, n) => (
                <tr key={`${e.product_id}-${e.lot_number}-${n}`} data-testid="expiry-row">
                  <td>{e.product_name}<div className="font-mono text-xs text-muted">{e.lot_number ?? "—"}</div></td>
                  <td className="text-xs">{e.warehouse_name}<div className="font-mono text-muted">{e.location_code ?? "بدون محل"}</div></td>
                  <td><Badge tone={e.expired ? "danger" : e.days_left <= 7 ? "warning" : "muted"}>
                    {e.expired ? `منقضی (${faNumber(-e.days_left)} روز)` : `${faNumber(e.days_left)} روز مانده`}</Badge>
                    <div className="mt-0.5 text-[11px] text-muted">{faDate(e.expiry_date)}</div></td>
                  <td className="tnum">{faNumber(e.quantity)}</td><td className="tnum text-xs">{faNumber(e.value)}</td>
                </tr>
              ))}</tbody>
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}

function SettingsModal({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["control-settings"], queryFn: () => unwrap(api.GET("/valuation/settings")) });
  const [form, setForm] = useState<Partial<Schemas["ControlSettings"]> & { reason?: string }>({});
  const value = { ...data, ...form };
  const save = useMutation({
    mutationFn: () => unwrap(api.PUT("/valuation/settings", { body: {
      valuation_method: value.valuation_method as "fifo", count_approval_value: Number(value.count_approval_value),
      slow_days: Number(value.slow_days), dead_days: Number(value.dead_days), expiry_warning_days: Number(value.expiry_warning_days),
      reason: form.reason || null } })),
    onSuccess: d => {
      queryClient.setQueryData(["control-settings"], d);
      ["valuation", "valuation-health", "stocktake"].forEach(k => queryClient.invalidateQueries({ queryKey: [k] }));
      toast.success("تنظیمات ذخیره شد و در گزارش فعالیت ثبت شد."); onClose();
    },
    onError: e => toast.error(errorMessage(e)),
  });
  const set = (k: string) => (e: { target: { value: string } }) => setForm(f => ({ ...f, [k]: e.target.value }));
  const methodChanged = !!data && !!form.valuation_method && form.valuation_method !== data.valuation_method;
  return (
    <Modal open onClose={onClose} title="روش ارزش‌گذاری و آستانه‌های کنترل" testId="valuation-settings-modal"
      description="تغییر روش ارزش‌گذاری اثر مالی دارد و با دلیل در گزارش فعالیت ثبت می‌شود."
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="vs-form" loading={save.isPending} data-testid="valuation-settings-save">ذخیره</Button></>}>
      {!data ? <TableSkeleton rows={3} /> : (
        <form id="vs-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
          <Field label="روش ارزش‌گذاری" className="sm:col-span-2">
            <Select value={value.valuation_method} onChange={set("valuation_method")} data-testid="valuation-method">
              {data.valuation_methods.map(m => <option key={m.code} value={m.code}>{m.label}</option>)}</Select>
          </Field>
          {methodChanged && <Field label="دلیل تغییر روش *" className="sm:col-span-2"><Input required minLength={3} value={form.reason ?? ""} onChange={set("reason")} /></Field>}
          <Field label="سقف تأیید انبارگردانی (ریال)" hint="مغایرت زیر این مبلغ با مجوز «زیر سقف» تأیید می‌شود">
            <Input type="number" min={0} value={value.count_approval_value ?? ""} onChange={set("count_approval_value")} /></Field>
          <Field label="هشدار انقضا (روز)"><Input type="number" min={1} max={365} value={value.expiry_warning_days ?? ""} onChange={set("expiry_warning_days")} /></Field>
          <Field label="کم‌گردش پس از (روز)"><Input type="number" min={7} max={720} value={value.slow_days ?? ""} onChange={set("slow_days")} /></Field>
          <Field label="راکد پس از (روز)"><Input type="number" min={14} max={1460} value={value.dead_days ?? ""} onChange={set("dead_days")} /></Field>
        </form>
      )}
    </Modal>
  );
}
