/**
 * نقطه سفارش هوشمند: برای هر کالا در هر انبار، نقطه سفارش از تقاضای واقعی دفتر گردش با فرمول استاندارد
 * (تقاضای دوره تأمین + موجودی اطمینان) محاسبه می‌شود؛ حالت دستی/خودکار، پارامترهای هر قلم و سیاست سازمان.
 */
import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertOctagon, AlertTriangle, Calculator, ChevronDown, FileSpreadsheet, FileText, PackageX, Search, Settings2, ShoppingCart, Sparkles, Zap,
} from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { useAsyncExport, useWarehouses } from "@/hooks/data";
import { faDate, faNumber } from "@/lib/format";
import { confirmDialog } from "@/ui/dialogs";
import { Modal } from "@/ui/overlays";
import {
  Badge, Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, SegmentedControl, Select, StatCard, Table, TableSkeleton,
  cn, type Tone,
} from "@/ui/primitives";

type Item = Schemas["RopItem"];
type Policy = Schemas["InventoryPolicy"];
type Status = Item["status"];

export const ROP_STATUS: Record<Status, { label: string; tone: Tone }> = {
  out: { label: "ناموجود", tone: "danger" },
  critical: { label: "زیر موجودی اطمینان", tone: "danger" },
  reorder: { label: "زمان سفارش", tone: "warning" },
  ok: { label: "عادی", tone: "success" },
};
const SERVICE_LEVELS = [0.9, 0.95, 0.975, 0.99, 0.995];
const fa = (v: number, digits = 1) => v.toLocaleString("fa-IR", { maximumFractionDigits: digits });
const pct = (v: number) => `${fa(v * 100, 1)}٪`;
/** ورودی عددی کاربر (ارقام فارسی هم) ← عدد یا null */
const num = (s: string) => {
  const t = s.replace(/[۰-۹]/g, d => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))).replace(/٫/g, ".").trim();
  return t === "" ? null : Number(t);
};

export default function ReorderPage() {
  const me = useMe();
  const isAdmin = me.role === "org_admin";
  const toast = useToast();
  const queryClient = useQueryClient();
  const warehouses = useWarehouses();
  const [q, setQ] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [status, setStatus] = useState<"" | Status>("");
  const [editing, setEditing] = useState<Item | null>(null);
  const [policyOpen, setPolicyOpen] = useState(false);
  const [showFormula, setShowFormula] = useState(false);
  const exporter = useAsyncExport(toast.error, () => toast.success("گزارش آماده و دانلود شد."));

  const list = useQuery({
    queryKey: ["replenishment", warehouseId],
    queryFn: () => unwrap(api.GET("/replenishment/items", { params: { query: { warehouse_id: warehouseId ? Number(warehouseId) : undefined } } })),
    placeholderData: keepPreviousData,
  });
  const autoAll = useMutation({
    mutationFn: () => unwrap(api.POST("/replenishment/items/apply-auto", { body: { warehouse_id: warehouseId ? Number(warehouseId) : null } })),
    onSuccess: r => {
      queryClient.invalidateQueries({ queryKey: ["replenishment"] });
      toast.success(`نقطه سفارش ${faNumber(r.switched)} قلم خودکار شد${r.skipped ? `؛ ${faNumber(r.skipped)} قلم سابقه کافی ندارند و دستی ماندند` : ""}.`);
    },
    onError: e => toast.error(errorMessage(e)),
  });

  const items = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (list.data?.items ?? []).filter(i => (!status || i.status === status)
      && (!needle || i.name.toLowerCase().includes(needle) || i.sku.toLowerCase().includes(needle) || (i.category ?? "").toLowerCase().includes(needle)));
  }, [list.data, q, status]);
  const s = list.data?.summary;
  const download = (format: "excel" | "pdf") => exporter.run("/reports/generate", `Pasineh_Reorder_Points.${format === "pdf" ? "pdf" : "xlsx"}`,
    { report: "reorder", format, warehouse_id: warehouseId ? Number(warehouseId) : null }, `reorder-${format}`);

  return (
    <>
      <PageHeader eyebrow="انبار" title="نقطه سفارش هوشمند"
        subtitle="کِی و چقدر خرید کنیم؟ — نقطه سفارش هر کالا از فروش واقعی دفتر گردش، زمان تأمین و سطح خدمت دلخواه محاسبه می‌شود."
        actions={<>
          {isAdmin && <Button variant="secondary" size="sm" icon={<Settings2 className="size-4" />} onClick={() => setPolicyOpen(true)} data-testid="rop-policy">سیاست انبار</Button>}
          <Button variant="secondary" size="sm" icon={<FileSpreadsheet className="size-4" />} loading={exporter.running === "reorder-excel"}
            disabled={!!exporter.running} onClick={() => download("excel")}>اکسل</Button>
          <Button variant="secondary" size="sm" icon={<FileText className="size-4" />} loading={exporter.running === "reorder-pdf"}
            disabled={!!exporter.running} onClick={() => download("pdf")}>PDF</Button>
          <Button size="sm" icon={<Zap className="size-4" />} loading={autoAll.isPending} data-testid="rop-auto-all" data-tour="rop-auto"
            onClick={async () => {
              if (await confirmDialog({ title: "خودکار کردن نقطه سفارش", text: "نقطه سفارش همه اقلامی که دست‌کم چند هفته سابقه فروش دارند از این پس هر شب با فرمول محاسبه می‌شود. اقلام کم‌سابقه دستی می‌مانند.", confirmLabel: "خودکار شود" }))
                autoAll.mutate();
            }}>خودکار کردن همه</Button>
        </>} />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" data-tour="rop-stats">
        <StatCard label="ناموجود" value={s ? faNumber(s.out) : "—"} icon={<PackageX className="size-5" />} tone="danger" hint="همین حالا فروش از دست می‌رود" />
        <StatCard label="زیر موجودی اطمینان" value={s ? faNumber(s.critical) : "—"} icon={<AlertOctagon className="size-5" />} tone="danger" hint="خطر کمبود پیش از رسیدن خرید" />
        <StatCard label="زمان سفارش" value={s ? faNumber(s.reorder) : "—"} icon={<ShoppingCart className="size-5" />} tone="warning" hint="به نقطه سفارش رسیده‌اند" />
        <StatCard label="محاسبه خودکار" value={s ? `${faNumber(s.auto)} از ${faNumber(s.total)}` : "—"} icon={<Sparkles className="size-5" />}
          hint={s?.insufficient ? `${faNumber(s.insufficient)} قلم سابقه فروش کافی ندارند` : "همه اقلام سابقه کافی دارند"} />
      </div>

      <Card className="mt-6 overflow-hidden" data-tour="rop-formula">
        <button type="button" onClick={() => setShowFormula(v => !v)} className="flex w-full items-center gap-3 px-5 py-4 text-start transition hover:bg-surface-2">
          <span className="grid size-9 place-items-center rounded-xl bg-brand-soft text-brand"><Calculator className="size-5" /></span>
          <div className="min-w-0 flex-1">
            <div className="font-bold">نقطه سفارش چطور محاسبه می‌شود؟</div>
            <div className="text-xs text-muted">فرمول استاندارد کنترل موجودی، با پارامترهای سازمان شما</div>
          </div>
          <ChevronDown className={cn("size-5 text-muted transition-transform duration-300", showFormula && "rotate-180")} />
        </button>
        <div className={cn("grid transition-all duration-300", showFormula ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0")}>
          <div className="min-h-0 overflow-hidden">
            <FormulaExplainer policy={list.data?.policy} />
          </div>
        </div>
      </Card>

      <Card className="mt-6">
        <div className="flex flex-wrap items-center gap-3 border-b border-border p-4">
          <div className="relative min-w-52 flex-1">
            <Search className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <Input value={q} onChange={e => setQ(e.target.value)} placeholder="جستجوی نام، کد یا گروه کالا" className="pr-9" data-testid="rop-search" />
          </div>
          {isAdmin && (
            <Select value={warehouseId} onChange={e => setWarehouseId(e.target.value)} className="w-48" aria-label="انبار">
              <option value="">همه انبارها</option>
              {(warehouses.data ?? []).map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          )}
          <SegmentedControl value={status} onChange={setStatus} options={[
            { value: "", label: "همه" }, { value: "out", label: "ناموجود" }, { value: "critical", label: "بحرانی" },
            { value: "reorder", label: "زمان سفارش" }, { value: "ok", label: "عادی" },
          ]} />
        </div>
        {list.error ? <ErrorState error={list.error} onRetry={list.refetch} /> : list.isLoading ? <TableSkeleton /> : items.length === 0 ? (
          <EmptyState icon={<ShoppingCart className="size-5" />} title="کالایی با این فیلتر نیست" text="فیلتر یا جستجو را تغییر دهید." />
        ) : (
          <Table testId="rop-table">
            <thead><tr>
              <th>کالا</th><th>انبار</th><th>موجودی / نقطه سفارش</th><th>موجودی اطمینان</th><th>تقاضای روزانه</th><th>پوشش</th>
              <th>وضعیت</th><th>پیشنهاد خرید</th><th>حالت</th><th />
            </tr></thead>
            <tbody>
              {items.map(i => <Row key={i.inventory_id} item={i} onEdit={() => setEditing(i)} />)}
            </tbody>
          </Table>
        )}
      </Card>

      {editing && <ItemModal item={editing} policy={list.data!.policy} onClose={() => setEditing(null)} />}
      {policyOpen && list.data && <PolicyModal policy={list.data.policy} onClose={() => setPolicyOpen(false)} />}
    </>
  );
}

function Row({ item: i, onEdit }: { item: Item; onEdit: () => void }) {
  const c = i.calc;
  const st = ROP_STATUS[i.status];
  const max = Math.max(1, i.reorder_point + c.order_qty, i.quantity);
  const differs = c.sufficient && c.rop !== i.reorder_point;
  return (
    <tr className="clickable" onClick={onEdit} data-testid="rop-row" data-status={i.status} data-sku={i.sku}>
      <td className="min-w-52"><div className="font-semibold">{i.name}</div><div className="font-mono text-xs text-muted ltr text-end">{i.sku}</div></td>
      <td className="whitespace-nowrap text-text-2">{i.warehouse ?? "—"}</td>
      <td className="min-w-44">
        <div className="flex items-baseline gap-1.5 text-sm"><b className="tnum">{faNumber(i.quantity)}</b><span className="text-muted">/</span>
          <span className="tnum">{faNumber(i.reorder_point)}</span><span className="text-xs text-muted">{i.unit}</span>
          {differs && <span className="text-[11px] text-brand" title="نقطه سفارش پیشنهادی فرمول">(فرمول: {faNumber(c.rop)})</span>}</div>
        {/* نوار موجودی: خط عمودی = نقطه سفارش */}
        <div className="relative mt-1.5 h-1.5 rounded-full bg-surface-2">
          <div className={cn("h-full rounded-full transition-all duration-500", i.status === "ok" ? "bg-success" : i.status === "reorder" ? "bg-warning" : "bg-danger")}
            style={{ width: `${Math.min(100, (i.quantity / max) * 100)}%` }} />
          <span className="absolute -top-0.5 h-2.5 w-0.5 rounded bg-text" style={{ right: `${Math.min(100, (i.reorder_point / max) * 100)}%` }} />
        </div>
      </td>
      <td className="tnum">{c.sufficient ? faNumber(c.safety_stock) : "—"}</td>
      <td className="tnum whitespace-nowrap">{c.data_days ? fa(c.avg_daily_demand, 2) : "—"}</td>
      <td className="whitespace-nowrap text-xs">
        {i.days_of_cover != null ? <><b className="tnum text-sm">{fa(i.days_of_cover, 0)}</b> روز<div className="text-muted">تا {faDate(i.stockout_date)}</div></> : <span className="text-muted">بدون فروش</span>}
      </td>
      <td><Badge tone={st.tone} dot>{st.label}</Badge>{!c.sufficient && <div className="mt-1 text-[11px] text-muted">سابقه {faNumber(c.data_days)} روزه</div>}</td>
      <td className="tnum font-semibold">{i.suggested_purchase ? `${faNumber(i.suggested_purchase)} ${i.unit}` : "—"}</td>
      <td><Badge tone={i.rop_mode === "auto" ? "brand" : "muted"}>{i.rop_mode === "auto" ? "خودکار" : "دستی"}</Badge></td>
      <td><Button variant="ghost" size="sm" onClick={e => { e.stopPropagation(); onEdit(); }} data-testid="rop-edit">جزئیات</Button></td>
    </tr>
  );
}

function FormulaExplainer({ policy }: { policy?: Policy }) {
  const rows: [string, string, string][] = [
    ["d̄ و σd", "میانگین و انحراف معیار فروش روزانه", `از دفتر گردش، ${policy ? faNumber(policy.history_days) : "۹۰"} روز اخیر (خروج سفارش منهای برگشت؛ روز بی‌فروش = صفر)`],
    ["L و σL", "زمان تأمین و نوسان آن (روز)", `از ثبت سفارش خرید تا رسیدن کالا — پیش‌فرض ${policy ? fa(policy.lead_time_days) : "۷"} ± ${policy ? fa(policy.lead_time_std_days) : "۲"} روز`],
    ["z", "ضریب سطح خدمت", `احتمال این‌که در دوره تأمین کمبود پیش نیاید — پیش‌فرض ${policy ? pct(policy.service_level) : "۹۵٪"} (z ≈ ۱٫۶۴۵)`],
  ];
  return (
    <div className="grid gap-5 border-t border-border p-5 lg:grid-cols-2" data-testid="rop-formula">
      <div className="space-y-3">
        {[["موجودی اطمینان", "SS = z × √( L·σd² + d̄²·σL² )"], ["نقطه سفارش", "ROP = d̄ × L + SS"],
          ["مقدار سفارش اقتصادی", "EOQ = √( 2 · D · S ÷ H )"], ["حداکثر موجودی", "Max = ROP + مقدار سفارش"]].map(([t, f]) => (
          <div key={t} className="rounded-xl border border-border bg-surface-2 px-4 py-3">
            <div className="text-xs text-muted">{t}</div>
            <div className="mt-1 font-mono text-sm font-bold ltr text-start" dir="ltr">{f}</div>
          </div>
        ))}
      </div>
      <div className="space-y-3 text-sm leading-7 text-text-2">
        <ul className="space-y-2">
          {rows.map(([sym, name, text]) => (
            <li key={sym} className="flex gap-3"><span className="w-14 shrink-0 font-mono font-bold text-brand ltr">{sym}</span>
              <span><b className="text-text">{name}:</b> {text}</span></li>
          ))}
        </ul>
        <p>EOQ وقتی محاسبه می‌شود که «هزینه هر بار سفارش» (S) در سیاست انبار و بهای خرید کالا ثبت شده باشد؛ وگرنه مقدار سفارش برابر فروش
          {" "}{policy ? faNumber(policy.cover_days) : "۳۰"} روز است. D فروش سالانه و H هزینه نگهداری سالانه هر واحد است.</p>
        <p>در حالت <b className="text-text">خودکار</b> نقطه سفارش هر شب با فروش تازه دوباره محاسبه می‌شود و هشدار کمبود، داشبورد و گزارش‌ها از همان استفاده می‌کنند.
          کالایی که کمتر از {policy ? faNumber(policy.min_history_days) : "۱۴"} روز سابقه دارد دستی می‌ماند.</p>
      </div>
    </div>
  );
}

function ItemModal({ item, policy, onClose }: { item: Item; policy: Policy; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const c = item.calc;
  const [mode, setMode] = useState(item.rop_mode);
  const [manual, setManual] = useState(String(item.reorder_point));
  const [lead, setLead] = useState(item.lead_time_days != null ? String(item.lead_time_days) : "");
  const [leadStd, setLeadStd] = useState(item.lead_time_std_days != null ? String(item.lead_time_std_days) : "");
  const [service, setService] = useState(item.service_level != null ? String(item.service_level) : "");
  useEffect(() => { setMode(item.rop_mode); }, [item.rop_mode]);
  const save = useMutation({
    mutationFn: () => unwrap(api.PUT("/replenishment/items/{inventory_id}", {
      params: { path: { inventory_id: item.inventory_id } },
      body: {
        rop_mode: mode, lead_time_days: num(lead), lead_time_std_days: num(leadStd), service_level: service ? Number(service) : null,
        ...(mode === "manual" ? { reorder_point: num(manual) ?? 0 } : {}),
      },
    })),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["replenishment"] }); toast.success("نقطه سفارش ذخیره شد."); onClose(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const e = item.effective;
  const src = (k: keyof typeof e.source) => e.source[k] === "item" ? "اختصاصی این کالا" : "پیش‌فرض سازمان";

  return (
    <Modal open onClose={onClose} size="lg" testId="rop-modal" title={item.name}
      description={`${item.warehouse ?? "—"} · موجودی ${faNumber(item.quantity)} ${item.unit}`}
      footer={<>
        <Button variant="secondary" onClick={onClose}>انصراف</Button>
        <Button loading={save.isPending} onClick={() => save.mutate()} data-testid="rop-save">ذخیره</Button>
      </>}>
      {/* محاسبه با عددهای واقعی همین کالا */}
      <div className="rounded-2xl border border-border bg-surface-2 p-4" data-testid="rop-breakdown">
        <div className="mb-3 flex items-center gap-2 text-sm font-bold"><Calculator className="size-4 text-brand" />محاسبه برای این کالا</div>
        {c.data_days === 0 ? <p className="text-sm text-muted">این کالا هنوز فروشی در دفتر گردش ندارد.</p> : (
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            <Term label="فروش روزانه (d̄)" value={`${fa(c.avg_daily_demand, 2)} ${item.unit}`} hint={`از ${faNumber(c.data_days)} روز سابقه`} />
            <Term label="نوسان فروش (σd)" value={fa(c.demand_std, 2)} />
            <Term label="زمان تأمین (L ± σL)" value={`${fa(e.lead_time_days)} ± ${fa(e.lead_time_std_days)} روز`} hint={src("lead_time_days")} />
            <Term label="سطح خدمت (z)" value={`${pct(e.service_level)} — z = ${fa(c.z, 3)}`} hint={src("service_level")} />
            <Term label="فروش دوره تأمین (d̄×L)" value={fa(c.lead_time_demand, 1)} />
            <Term label="موجودی اطمینان (SS)" value={faNumber(c.safety_stock)} strong />
            <Term label="نقطه سفارش فرمول (ROP)" value={faNumber(c.rop)} strong />
            <Term label={c.order_qty_method === "eoq" ? "مقدار سفارش اقتصادی (EOQ)" : `مقدار سفارش (${faNumber(policy.cover_days)} روز فروش)`} value={faNumber(c.order_qty)} strong />
          </dl>
        )}
        {!c.sufficient && c.data_days > 0 && (
          <p className="mt-3 flex items-start gap-2 rounded-xl bg-warning-soft px-3 py-2 text-xs text-warning">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />فقط {faNumber(c.data_days)} روز سابقه دارد (حداقل {faNumber(policy.min_history_days)} روز)؛ عدد فرمول هنوز قابل اتکا نیست و حالت خودکار فعال نمی‌شود.
          </p>
        )}
      </div>

      <div className="mt-5 space-y-4">
        <Field label="روش تعیین نقطه سفارش">
          <SegmentedControl value={mode} onChange={setMode} options={[{ value: "auto", label: "خودکار با فرمول" }, { value: "manual", label: "عدد دستی" }]} />
        </Field>
        {mode === "manual" ? (
          <Field label="نقطه سفارش دستی" hint="وقتی موجودی به این عدد برسد هشدار کمبود داده می‌شود">
            <Input inputMode="numeric" value={manual} onChange={ev => setManual(ev.target.value)} data-testid="rop-manual" />
          </Field>
        ) : (
          <p className="rounded-xl bg-brand-soft px-3 py-2 text-xs leading-6 text-brand-strong">نقطه سفارش با ذخیره روی {faNumber(c.rop)} تنظیم و از این پس هر شب با فروش تازه به‌روز می‌شود.</p>
        )}
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="زمان تأمین (روز)" hint={`خالی = پیش‌فرض (${fa(policy.lead_time_days)})`}>
            <Input inputMode="decimal" value={lead} onChange={ev => setLead(ev.target.value)} placeholder={fa(policy.lead_time_days)} data-testid="rop-lead" />
          </Field>
          <Field label="نوسان زمان تأمین (روز)" hint={`خالی = پیش‌فرض (${fa(policy.lead_time_std_days)})`}>
            <Input inputMode="decimal" value={leadStd} onChange={ev => setLeadStd(ev.target.value)} placeholder={fa(policy.lead_time_std_days)} />
          </Field>
          <Field label="سطح خدمت">
            <Select value={service} onChange={ev => setService(ev.target.value)}>
              <option value="">پیش‌فرض ({pct(policy.service_level)})</option>
              {SERVICE_LEVELS.map(l => <option key={l} value={l}>{pct(l)}</option>)}
            </Select>
          </Field>
        </div>
      </div>
    </Modal>
  );
}

function Term({ label, value, hint, strong }: { label: string; value: string; hint?: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-dashed border-border py-1.5">
      <dt className="text-text-2">{label}{hint && <span className="block text-[11px] text-muted">{hint}</span>}</dt>
      <dd className={cn("tnum whitespace-nowrap", strong ? "text-base font-extrabold text-brand" : "font-semibold")}>{value}</dd>
    </div>
  );
}

const POLICY_FIELDS: { key: keyof Policy; label: string; hint: string; percent?: boolean }[] = [
  { key: "lead_time_days", label: "زمان تأمین (روز)", hint: "از ثبت خرید تا رسیدن کالا به انبار" },
  { key: "lead_time_std_days", label: "نوسان زمان تأمین (روز)", hint: "چقدر دیر/زود رسیدن خرید معمول است" },
  { key: "service_level", label: "سطح خدمت (٪)", hint: "مثلاً ۹۵ یعنی ۹۵٪ دوره‌ها بدون کمبود", percent: true },
  { key: "history_days", label: "تاریخچه فروش (روز)", hint: "بازه محاسبه میانگین و نوسان" },
  { key: "min_history_days", label: "حداقل سابقه (روز)", hint: "کمتر از این، نقطه سفارش دستی می‌ماند" },
  { key: "cover_days", label: "روزهای پوشش هر خرید", hint: "مقدار سفارش وقتی EOQ ممکن نیست" },
  { key: "ordering_cost", label: "هزینه هر بار سفارش (ریال)", hint: "حمل، ثبت، بازرسی… — برای EOQ؛ صفر = غیرفعال" },
  { key: "holding_rate", label: "هزینه نگهداری سالانه (٪ بها)", hint: "انبارداری، سرمایه خوابیده، فساد", percent: true },
  { key: "price_growth_monthly", label: "تورم ماهانه بهای خرید (٪)", hint: "برای برآورد سرمایه ماه‌های آینده", percent: true },
  { key: "demand_growth_monthly", label: "رشد ماهانه فروش (٪)", hint: "سناریوی برآورد سرمایه", percent: true },
];

function PolicyModal({ policy, onClose }: { policy: Policy; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(POLICY_FIELDS.map(f => [f.key, String(f.percent ? Math.round(policy[f.key] * 1000) / 10 : policy[f.key])])));
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, number> = {};
      for (const f of POLICY_FIELDS) {
        const v = num(values[f.key]);
        if (v === null || Number.isNaN(v)) throw new Error(`«${f.label}» را درست وارد کنید.`);
        body[f.key] = f.percent ? v / 100 : v;
      }
      return unwrap(api.PUT("/replenishment/policy", { body }));
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["replenishment"] }); queryClient.invalidateQueries({ queryKey: ["capital-plan"] }); toast.success("سیاست انبار ذخیره شد و نقطه سفارش اقلام خودکار دوباره محاسبه شد."); onClose(); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <Modal open onClose={onClose} size="lg" testId="rop-policy-modal" title="سیاست انبار سازمان"
      description="پیش‌فرض‌های فرمول برای همه کالاها؛ هر کالا می‌تواند مقدار اختصاصی خودش را داشته باشد."
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button loading={save.isPending} onClick={() => save.mutate()} data-testid="rop-policy-save">ذخیره</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        {POLICY_FIELDS.map(f => (
          <Field key={f.key} label={f.label} hint={f.hint}>
            <Input inputMode="decimal" value={values[f.key]} onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))} data-testid={`policy-${f.key}`} />
          </Field>
        ))}
      </div>
    </Modal>
  );
}
