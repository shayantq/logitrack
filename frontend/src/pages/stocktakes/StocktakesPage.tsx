/** انبارگردانی (مرحله ۱۲): وضعیت هر انبار و سررسید دوره بعد، شروع انبارگردانی و سابقه */
import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, ClipboardCheck, ClipboardList, History, Play, Search, Warehouse } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { useProducts, useWarehouses } from "@/hooks/data";
import { faDate, faNumber } from "@/lib/format";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Field, Input, PageHeader, SegmentedControl, Select, Skeleton, Table, TableSkeleton, cn, type Tone } from "@/ui/primitives";

export const STOCKTAKE_STATUS: Record<string, { label: string; tone: Tone }> = {
  counting: { label: "در حال شمارش", tone: "info" },
  review: { label: "منتظر بررسی", tone: "warning" },
  approved: { label: "تأیید و اعمال‌شده", tone: "success" },
  canceled: { label: "لغوشده", tone: "muted" },
};
const INTERVALS: [string, string][] = [["", "بدون برنامه"], ["30", "ماهانه"], ["60", "هر ۲ ماه"], ["90", "فصلی"], ["180", "شش‌ماهه"], ["365", "سالانه"]];

export default function StocktakesPage() {
  const me = useMe();
  const isAdmin = me.role === "org_admin";
  const toast = useToast();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [startFor, setStartFor] = useState<number | null | "pick">(null);
  const overview = useQuery({ queryKey: ["stocktakes", "overview"], queryFn: () => unwrap(api.GET("/stocktakes/overview")) });
  const history = useQuery({ queryKey: ["stocktakes", "list"], queryFn: () => unwrap(api.GET("/stocktakes/")) });
  const interval = useMutation({
    mutationFn: ({ id, days }: { id: number; days: number | null }) =>
      unwrap(api.PUT("/stocktakes/warehouses/{warehouse_id}/interval", { params: { path: { warehouse_id: id } }, body: { days } })),
    onSuccess: data => { queryClient.setQueryData(["stocktakes", "overview"], data); queryClient.invalidateQueries({ queryKey: ["stocktakes-summary"] }); toast.success("برنامه انبارگردانی ذخیره شد."); },
    onError: e => toast.error(errorMessage(e)),
  });

  return (
    <>
      <PageHeader eyebrow="انبار" title="انبارگردانی" subtitle="شمارش کور موجودی واقعی، بررسی مغایرت‌ها و اصلاح موجودی با ثبت در دفتر گردش"
        actions={<Button icon={<Play className="size-4" />} onClick={() => setStartFor("pick")} data-testid="stocktake-new">شروع انبارگردانی</Button>} />

      {overview.isLoading ? <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map(i => <Skeleton key={i} className="h-48" />)}</div>
        : overview.error ? <ErrorState error={overview.error} onRetry={overview.refetch} /> : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="stocktake-overview">
            {overview.data!.map(w => (
              <Card key={w.warehouse_id} className="flex flex-col p-5" data-testid="stocktake-warehouse" data-warehouse={w.warehouse_id}>
                <div className="flex items-start gap-3">
                  <span className="grid size-11 shrink-0 place-items-center rounded-2xl bg-brand-soft text-brand"><Warehouse className="size-5" /></span>
                  <div className="min-w-0 flex-1">
                    <h3 className="truncate font-bold">{w.warehouse_name}</h3>
                    <div className="text-xs text-muted">{w.city ?? "—"} · {faNumber(w.items)} کالا</div>
                  </div>
                  {w.overdue && <Badge tone="danger" dot>سررسید گذشته</Badge>}
                </div>
                <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div><dt className="text-xs text-muted">آخرین انبارگردانی</dt><dd className="mt-0.5 font-semibold">{w.last_approved_at ? faDate(w.last_approved_at) : "هرگز"}</dd></div>
                  <div><dt className="text-xs text-muted">نوبت بعدی</dt>
                    <dd className={cn("mt-0.5 font-semibold", w.overdue && "text-danger")}>{w.next_due_at ? faDate(w.next_due_at) : "—"}</dd></div>
                </dl>
                {isAdmin && (
                  <div className="mt-3 flex items-center gap-2 text-xs text-muted">
                    <CalendarClock className="size-4 shrink-0" />
                    <Select value={w.interval_days ? String(w.interval_days) : ""} className="h-8 text-xs" aria-label="دوره انبارگردانی" data-testid="stocktake-interval"
                      onChange={e => interval.mutate({ id: w.warehouse_id, days: e.target.value ? Number(e.target.value) : null })}>
                      {INTERVALS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </Select>
                  </div>
                )}
                <div className="mt-auto pt-4">
                  {w.active ? (
                    <Link to={`/app/stocktakes/${w.active.id}`} className="flex items-center justify-between gap-2 rounded-xl border border-border p-3 text-sm transition hover:border-brand" data-testid="stocktake-active">
                      <span><span className="font-mono text-xs ltr">{w.active.code}</span> · <Badge tone={STOCKTAKE_STATUS[w.active.status].tone}>{STOCKTAKE_STATUS[w.active.status].label}</Badge></span>
                      <span className="text-xs text-muted tnum">{faNumber(w.active.lines_counted)} / {faNumber(w.active.lines_total)}</span>
                    </Link>
                  ) : (
                    <Button variant="secondary" className="w-full" icon={<ClipboardList className="size-4" />} onClick={() => setStartFor(w.warehouse_id)} disabled={!w.items}>
                      شروع انبارگردانی</Button>
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}

      <Card className="mt-6">
        <CardHeader title={<span className="flex items-center gap-2"><History className="size-4 text-brand" />سابقه انبارگردانی‌ها</span>} />
        {history.isLoading ? <TableSkeleton /> : !history.data?.length
          ? <EmptyState icon={<ClipboardCheck className="size-5" />} title="هنوز انبارگردانی ثبت نشده" text="با «شروع انبارگردانی» اولین شمارش را آغاز کنید." />
          : (
            <Table testId="stocktakes-table">
              <thead><tr><th>کد</th><th>انبار</th><th>نوع</th><th>پیشرفت</th><th>شروع</th><th>تأیید</th><th>وضعیت</th></tr></thead>
              <tbody>
                {history.data.map(s => (
                  <tr key={s.id} className="clickable" onClick={() => navigate(`/app/stocktakes/${s.id}`)}>
                    <td><Link to={`/app/stocktakes/${s.id}`} className="font-mono font-semibold ltr" onClick={e => e.stopPropagation()}>{s.code}</Link></td>
                    <td>{s.warehouse_name}</td>
                    <td className="text-text-2">{s.scope === "full" ? "کامل" : "بخشی"}</td>
                    <td className="tnum">{faNumber(s.lines_counted)} / {faNumber(s.lines_total)}</td>
                    <td className="text-xs text-text-2">{faDate(s.created_at)}</td>
                    <td className="text-xs text-text-2">{s.approved_at ? faDate(s.approved_at) : "—"}</td>
                    <td><Badge tone={STOCKTAKE_STATUS[s.status].tone} dot>{STOCKTAKE_STATUS[s.status].label}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
      </Card>

      {startFor !== null && <StartModal warehouseId={startFor === "pick" ? null : startFor} onClose={() => setStartFor(null)} />}
    </>
  );
}

function StartModal({ warehouseId, onClose }: { warehouseId: number | null; onClose: () => void }) {
  const me = useMe();
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: warehouses = [] } = useWarehouses();
  const { data: products = [] } = useProducts();
  const own = me.role === "warehouse_manager" ? me.warehouse_id ?? null : null;
  const [form, setForm] = useState({ warehouse: String(warehouseId ?? own ?? ""), scope: "full" as "full" | "partial", title: "", note: "" });
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [q, setQ] = useState("");
  const wid = Number(form.warehouse);
  const inWarehouse = useMemo(() => products.filter(p => p.stock_by_warehouse.some(s => s.warehouse_id === wid)), [products, wid]);
  const pool = form.scope === "partial" ? (q ? products.filter(p => `${p.name} ${p.sku}`.includes(q.trim())) : products) : inWarehouse;
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/stocktakes/", { body: {
      warehouse_id: wid, scope: form.scope, product_ids: form.scope === "partial" ? [...picked] : null,
      title: form.title || null, note: form.note || null,
    } })),
    onSuccess: st => {
      toast.success(`انبارگردانی ${st.code} شروع شد.`);
      queryClient.invalidateQueries({ queryKey: ["stocktakes"] });
      queryClient.invalidateQueries({ queryKey: ["stocktakes-summary"] });
      navigate(`/app/stocktakes/${st.id}`);
    },
    onError: e => toast.error(errorMessage(e)),
  });

  return (
    <Modal open onClose={onClose} title="شروع انبارگردانی" size="lg" testId="stocktake-start"
      description="شمارش کور است: شمارنده عدد موجودی سیستم را نمی‌بیند. مغایرت‌ها بعد از ارسال، برای ادمین نمایش داده می‌شود."
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button>
        <Button type="submit" form="stocktake-form" loading={create.isPending} data-testid="stocktake-create">شروع</Button></>}>
      <form id="stocktake-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
        <Field label="انبار *">
          <Select required value={form.warehouse} disabled={!!own} onChange={e => setForm(f => ({ ...f, warehouse: e.target.value }))} data-testid="stocktake-warehouse-pick">
            <option value="">انتخاب کنید</option>{warehouses.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
          </Select>
        </Field>
        <Field label="محدوده">
          <SegmentedControl value={form.scope} onChange={v => setForm(f => ({ ...f, scope: v }))}
            options={[{ value: "full", label: "همه کالاهای انبار" }, { value: "partial", label: "کالاهای انتخابی" }]} />
        </Field>
        <Field label="عنوان" hint="اختیاری"><Input maxLength={200} value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} placeholder="مثلاً انبارگردانی پایان مهر" /></Field>
        <Field label="توضیح برای شمارنده" hint="اختیاری"><Input maxLength={1000} value={form.note} onChange={e => setForm(f => ({ ...f, note: e.target.value }))} placeholder="مثلاً قفسه‌های طبقه دوم را هم بشمارید" /></Field>
        {form.scope === "full" ? (
          <p className="rounded-xl bg-surface-2 px-4 py-3 text-sm text-text-2 sm:col-span-2" data-testid="stocktake-full-count">
            {form.warehouse ? `${faNumber(inWarehouse.length)} کالای این انبار در فهرست شمارش قرار می‌گیرد.` : "انبار را انتخاب کنید."}</p>
        ) : (
          <div className="sm:col-span-2">
            <div className="mb-2 flex items-center gap-2">
              <label className="relative flex-1">
                <Search className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
                <input value={q} onChange={e => setQ(e.target.value)} placeholder="جست‌وجوی کالا" className="h-9 w-full rounded-lg border border-border bg-surface pe-3 ps-9 text-sm outline-none focus:border-brand" />
              </label>
              <span className="text-xs text-muted">{faNumber(picked.size)} کالا انتخاب شده</span>
            </div>
            <div className="max-h-64 divide-y divide-border overflow-y-auto rounded-xl border border-border" data-testid="stocktake-products">
              {pool.map(p => (
                <label key={p.id} className="flex cursor-pointer items-center gap-3 px-3 py-2.5 text-sm hover:bg-surface-2">
                  <input type="checkbox" checked={picked.has(p.id)} onChange={() => setPicked(s => { const n = new Set(s); if (n.has(p.id)) n.delete(p.id); else n.add(p.id); return n; })} />
                  <span className="flex-1">{p.name}</span><span className="font-mono text-xs text-muted">{p.sku}</span>
                </label>
              ))}
            </div>
          </div>
        )}
      </form>
    </Modal>
  );
}

export type StocktakeDetail = Schemas["StocktakeDetail"];
