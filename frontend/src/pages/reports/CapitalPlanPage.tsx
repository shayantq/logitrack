/**
 * برآورد سرمایه خرید ماه‌های آینده: پیش‌بینی فروش هر کالا (روند ماهانه یا میانگین روزانه) + شبیه‌سازی روزبه‌روز سیاست
 * نقطه سفارش ← مبلغ سفارش‌های خرید هر ماه شمسی با بهای خرید همان روز (قیمت آینده ثبت‌شده یا تورم).
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle, BarChart3, Boxes, CalendarRange, PieChart, ChevronDown, FileSpreadsheet, FileText, Info, Landmark, PiggyBank, TrendingUp, Wallet,
} from "lucide-react";
import { api, unwrap, type Schemas } from "@/api/client";
import { useToast } from "@/components/Toast";
import { useAsyncExport, useWarehouses } from "@/hooks/data";
import { faNumber } from "@/lib/format";
import { DonutChart } from "@/ui/brand";
import {
  Badge, Button, Card, CardHeader, EmptyState, ErrorState, Field, Input, PageHeader, SegmentedControl, Select, Skeleton, StatCard, Table, cn,
} from "@/ui/primitives";
import { faMoneyShort } from "./period";

type Plan = Schemas["CapitalPlan"];
const rial = (v: number) => `${faNumber(Math.round(v))} ریال`;
const num = (s: string) => {
  const t = s.replace(/[۰-۹]/g, d => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))).replace(/٫/g, ".").trim();
  return t === "" ? null : Number(t);
};

/** مقدار ورودی را با کمی تأخیر برمی‌گرداند تا با هر کلید یک محاسبه سنگین اجرا نشود */
function useDebounced<T>(value: T, ms = 500): T {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

export default function CapitalPlanPage() {
  const toast = useToast();
  const warehouses = useWarehouses();
  const [months, setMonths] = useState<"3" | "6" | "12">("6");
  const [warehouseId, setWarehouseId] = useState("");
  const [priceGrowth, setPriceGrowth] = useState("");
  const [demandGrowth, setDemandGrowth] = useState("");
  const [showMethod, setShowMethod] = useState(false);
  const pg = useDebounced(priceGrowth), dg = useDebounced(demandGrowth);
  const pgValue = num(pg), dgValue = num(dg);
  const exporter = useAsyncExport(toast.error, () => toast.success("گزارش آماده و دانلود شد."));

  const plan = useQuery({
    queryKey: ["capital-plan", months, warehouseId, pgValue, dgValue],
    queryFn: () => unwrap(api.GET("/replenishment/capital-plan", { params: { query: {
      months: Number(months), warehouse_id: warehouseId ? Number(warehouseId) : undefined,
      price_growth: pgValue != null && !Number.isNaN(pgValue) ? pgValue / 100 : undefined,
      demand_growth: dgValue != null && !Number.isNaN(dgValue) ? dgValue / 100 : undefined,
    } } })),
    placeholderData: keepPreviousData,
  });
  const data = plan.data;
  const s = data?.summary;
  const download = (format: "excel" | "pdf") => exporter.run("/reports/generate", `Pasineh_Purchase_Capital_Plan.${format === "pdf" ? "pdf" : "xlsx"}`,
    { report: "capital", format, months: Number(months), warehouse_id: warehouseId ? Number(warehouseId) : null }, `capital-${format}`);

  return (
    <>
      <PageHeader eyebrow="گزارش‌ها" title="برآورد سرمایه خرید"
        subtitle="برای خرید کالا در ماه‌های آینده چقدر نقدینگی لازم است؟ — بر اساس روند فروش، نقطه سفارش، زمان تأمین و تورم بها."
        actions={<>
          <Button variant="secondary" size="sm" icon={<FileSpreadsheet className="size-4" />} loading={exporter.running === "capital-excel"}
            disabled={!!exporter.running} onClick={() => download("excel")} data-testid="capital-excel">اکسل</Button>
          <Button variant="secondary" size="sm" icon={<FileText className="size-4" />} loading={exporter.running === "capital-pdf"}
            disabled={!!exporter.running} onClick={() => download("pdf")}>PDF</Button>
        </>} />

      <Card className="mb-6 p-4" data-tour="capital-controls">
        <div className="flex flex-wrap items-end gap-4">
          <Field label="افق برنامه">
            <SegmentedControl value={months} onChange={setMonths} options={[{ value: "3", label: "۳ ماه" }, { value: "6", label: "۶ ماه" }, { value: "12", label: "۱۲ ماه" }]} />
          </Field>
          <Field label="انبار" className="w-48">
            <Select value={warehouseId} onChange={e => setWarehouseId(e.target.value)}>
              <option value="">همه انبارها</option>
              {(warehouses.data ?? []).map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          </Field>
          <Field label="تورم ماهانه بها (٪)" className="w-40" hint={data ? `پیش‌فرض: ${faNumber(Math.round(data.assumptions.price_growth_monthly * 1000) / 10)}٪` : undefined}>
            <Input inputMode="decimal" value={priceGrowth} onChange={e => setPriceGrowth(e.target.value)} placeholder="سیاست سازمان" data-testid="capital-price-growth" />
          </Field>
          <Field label="رشد ماهانه فروش (٪)" className="w-40" hint={data ? `پیش‌فرض: ${faNumber(Math.round(data.assumptions.demand_growth_monthly * 1000) / 10)}٪` : undefined}>
            <Input inputMode="decimal" value={demandGrowth} onChange={e => setDemandGrowth(e.target.value)} placeholder="سیاست سازمان" />
          </Field>
          <Link to="/app/reorder" className="mb-2 text-xs font-medium text-brand hover:underline">تنظیم زمان تأمین و سطح خدمت ←</Link>
        </div>
      </Card>

      {plan.error ? <ErrorState error={plan.error} onRetry={plan.refetch} /> : !data || !s ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-32 rounded-2xl" />)}</div>
      ) : (
        <div className={cn("transition-opacity", plan.isFetching && "opacity-70")} data-testid="capital-plan" data-total={s.total_capital}>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" data-tour="capital-stats">
            <StatCard label={`سرمایه لازم ${faNumber(data.months.length)} ماه آینده`} value={faMoneyShort(s.total_capital)} hint={rial(s.total_capital)} icon={<Wallet className="size-5" />} />
            <StatCard label="پرهزینه‌ترین ماه" value={s.peak_month ?? "—"} hint={s.peak_capital ? rial(s.peak_capital) : "خریدی لازم نیست"} icon={<CalendarRange className="size-5" />} tone="warning" />
            <StatCard label="میانگین هر ماه" value={faMoneyShort(s.average_monthly)} hint="برای بودجه‌بندی نقدینگی" icon={<PiggyBank className="size-5" />} tone="violet" />
            <StatCard label="ارزش موجودی فعلی" value={faMoneyShort(s.current_stock_value)} hint="به بهای خرید امروز" icon={<Boxes className="size-5" />} tone="info" />
          </div>

          {(s.items_cost_estimated > 0 || s.stockout_risk_items > 0) && (
            <div className="mt-4 space-y-2">
              {s.items_cost_estimated > 0 && (
                <div className="flex items-start gap-3 rounded-2xl border border-warning/30 bg-warning-soft px-4 py-3 text-sm" data-testid="capital-estimated">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
                  <div><b>{faNumber(s.items_cost_estimated)} کالا بهای خرید ثبت‌شده ندارند</b> و قیمت فروش مبنا قرار گرفت (برآورد بیشتر از واقع است).
                    {" "}بهای تمام‌شده را در «انبار و کالاها ← قیمت‌ها» ثبت کنید.
                    <div className="mt-1 text-xs text-muted">{s.cost_estimated_names.join("، ")}{s.items_cost_estimated > s.cost_estimated_names.length ? "، …" : ""}</div></div>
                </div>
              )}
              {s.stockout_risk_items > 0 && (
                <div className="flex items-start gap-3 rounded-2xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" />
                  <div><b>{faNumber(s.stockout_risk_items)} کالا حتی با این برنامه در خطر کمبودند</b> — معمولاً چون موجودی فعلی زیر فروش دوره تأمین است. خریدشان را زودتر انجام دهید.</div>
                </div>
              )}
            </div>
          )}

          {s.items_planned === 0 ? (
            <Card className="mt-6"><EmptyState icon={<TrendingUp className="size-5" />} title="فروشی برای پیش‌بینی نیست"
              text="برای برآورد سرمایه، کالاها باید سابقه خروج بابت سفارش در دفتر گردش داشته باشند." /></Card>
          ) : (
            <>
              <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-5">
                <Card className="min-w-0 xl:col-span-3">
                  <CardHeader title="سرمایه لازم هر ماه" subtitle="ستون: خرید همان ماه — نوار کم‌رنگ: جمع تجمعی" icon={<BarChart3 className="size-[18px]" />} />
                  <div className="p-5"><MonthBars months={data.months} /></div>
                </Card>
                <Card className="min-w-0 xl:col-span-2">
                  <CardHeader title="سهم گروه‌های کالا" subtitle="از کل سرمایه (میلیون ریال)" icon={<PieChart className="size-[18px]" />} tone="violet" />
                  <div className="p-5">
                    <DonutChart size={160} data={data.by_category.slice(0, 7).map(c => ({ label: c.label, value: Math.round(c.capital / 1e6) }))} />
                  </div>
                </Card>
              </div>

              <Card className="mt-6">
                <CardHeader title="جدول ماه‌به‌ماه" icon={<CalendarRange className="size-[18px]" />} tone="info" />
                <Table testId="capital-months">
                  <thead><tr><th>ماه</th><th>سرمایه خرید</th><th>تجمعی</th><th>سفارش خرید</th><th>واحد خرید</th><th>فروش پیش‌بینی</th><th>ارزش موجودی پایان ماه</th><th>خطر کمبود</th></tr></thead>
                  <tbody>
                    {data.months.map(m => (
                      <tr key={m.key}>
                        <td className="whitespace-nowrap font-semibold">{m.label}{m.partial && <span className="mr-1 text-xs font-normal text-muted">({faNumber(m.days)} روز باقی‌مانده)</span>}</td>
                        <td className="tnum whitespace-nowrap font-bold">{faNumber(m.capital)}</td>
                        <td className="tnum whitespace-nowrap text-text-2">{faNumber(m.cumulative)}</td>
                        <td className="tnum">{faNumber(m.orders)}</td>
                        <td className="tnum">{faNumber(m.units)}</td>
                        <td className="tnum">{faNumber(m.demand_units)}</td>
                        <td className="tnum whitespace-nowrap">{faNumber(m.stock_value_end)}</td>
                        <td>{m.stockout_items ? <Badge tone="danger">{faNumber(m.stockout_items)} کالا</Badge> : <span className="text-muted">—</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Card>

              <Card className="mt-6">
                <CardHeader title="به تفکیک کالا" subtitle="مرتب بر اساس سرمایه لازم؛ مبالغ ماهانه به ریال" icon={<Boxes className="size-[18px]" />} tone="orange" />
                <ItemsTable plan={data} />
              </Card>
            </>
          )}

          <Card className="mt-6 overflow-hidden">
            <button type="button" onClick={() => setShowMethod(v => !v)} className="flex w-full items-center gap-3 px-5 py-4 text-start transition hover:bg-surface-2">
              <span className="grid size-9 place-items-center rounded-xl bg-brand-soft text-brand"><Info className="size-5" /></span>
              <div className="flex-1 font-bold">این عددها چطور به دست آمده‌اند؟</div>
              <ChevronDown className={cn("size-5 text-muted transition-transform duration-300", showMethod && "rotate-180")} />
            </button>
            <div className={cn("grid transition-all duration-300", showMethod ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0")}>
              <div className="min-h-0 overflow-hidden">
                <ol className="list-inside list-decimal space-y-2 border-t border-border p-5 text-sm leading-7 text-text-2">
                  <li><b className="text-text">پیش‌بینی فروش:</b> اگر کالا دست‌کم ۳ ماه شمسی کامل فروش داشته باشد، روند ماهانه با هموارسازی نمایی دوگانه (Holt) با روند میرا ادامه داده می‌شود؛ وگرنه میانگین فروش روزانه اخیر. رشد ماهانه فروش (سناریو) روی آن اعمال می‌شود.</li>
                  <li><b className="text-text">شبیه‌سازی روزبه‌روز:</b> از موجودی امروز، فروش هر روز کم می‌شود؛ هر وقت «موجودی + خرید در راه» به نقطه سفارش برسد، خرید تا سقف موجودی ثبت و بعد از زمان تأمین وارد انبار می‌شود.</li>
                  <li><b className="text-text">مبلغ:</b> هر خرید با بهای خرید همان روز حساب می‌شود: قیمت آینده‌ای که در کاتالوگ ثبت کرده‌اید، وگرنه آخرین بهای خرید × تورم ماهانه. پول در ماهِ ثبت سفارش خرید لازم است.</li>
                  <li><b className="text-text">فرض‌ها:</b> زمان تأمین و سطح خدمت از «نقطه سفارش هوشمند»؛ فروش ازدست‌رفته در کمبود برنمی‌گردد؛ تخفیف حجمی و شرایط پرداخت اعتباری لحاظ نشده است.</li>
                </ol>
              </div>
            </div>
          </Card>
        </div>
      )}
    </>
  );
}

function MonthBars({ months }: { months: Plan["months"] }) {
  const max = Math.max(1, ...months.map(m => m.capital));
  const total = Math.max(1, months[months.length - 1]?.cumulative ?? 1);
  return (
    <div className="flex h-60 items-end gap-2 overflow-x-auto px-1 pb-1 sm:gap-3" data-testid="capital-bars">
      {months.map(m => (
        <div key={m.key} className="flex min-w-14 flex-1 flex-col items-center gap-2">
          <span className="text-[11px] font-semibold tnum whitespace-nowrap">{m.capital ? faMoneyShort(m.capital) : "—"}</span>
          <div className="relative flex h-40 w-full max-w-16 items-end">
            {/* سهم تجمعی از کل افق (نوار کم‌رنگ پشت) */}
            <div className="absolute inset-x-0 bottom-0 rounded-t-lg bg-brand/12 transition-all duration-700" style={{ height: `${(m.cumulative / total) * 100}%` }} />
            <div className="relative w-full rounded-t-lg bg-linear-to-t from-brand to-violet transition-all duration-700"
              style={{ height: `${Math.max(m.capital ? 4 : 0, (m.capital / max) * 100)}%` }} />
          </div>
          <span className="whitespace-nowrap text-center text-[11px] text-muted">{m.label}</span>
        </div>
      ))}
    </div>
  );
}

function ItemsTable({ plan }: { plan: Plan }) {
  const [all, setAll] = useState(false);
  const rows = all ? plan.items : plan.items.slice(0, 15);
  return (
    <>
      <Table testId="capital-items">
        <thead><tr>
          <th>کالا</th><th>موجودی</th><th>فروش روزانه</th><th>بهای خرید</th>
          {plan.months.map(m => <th key={m.key} className="whitespace-nowrap">{m.label}</th>)}
          <th>جمع</th>
        </tr></thead>
        <tbody>
          {rows.map(i => (
            <tr key={i.inventory_id}>
              <td className="min-w-48">
                <div className="font-semibold">{i.name}</div>
                <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
                  <span>{i.warehouse ?? "—"}</span>
                  <Badge tone={i.forecast_method === "holt" ? "violet" : "muted"}>{i.forecast_method === "holt" ? "روند ماهانه" : "میانگین"}</Badge>
                  {i.stockout_risk && <Badge tone="danger">خطر کمبود</Badge>}
                </div>
              </td>
              <td className="tnum">{faNumber(i.quantity)}</td>
              <td className="tnum">{i.avg_daily_forecast.toLocaleString("fa-IR", { maximumFractionDigits: 2 })}</td>
              <td className="tnum whitespace-nowrap">{faNumber(i.unit_cost_now)}{i.cost_estimated && <span className="mr-1 text-warning" title="بهای خرید ثبت نشده؛ قیمت فروش">*</span>}</td>
              {i.months.map((m, k) => (
                <td key={k} className={cn("tnum whitespace-nowrap", !m.capital && "text-muted")} title={m.units ? `${faNumber(m.units)} واحد در ${faNumber(m.orders)} سفارش` : undefined}>
                  {m.capital ? faMoneyShort(m.capital) : "—"}
                </td>
              ))}
              <td className="tnum whitespace-nowrap font-bold">{faMoneyShort(i.total_capital)}</td>
            </tr>
          ))}
        </tbody>
      </Table>
      {plan.items.length > 15 && (
        <div className="border-t border-border p-3 text-center">
          <Button variant="ghost" size="sm" onClick={() => setAll(v => !v)}>{all ? "نمایش کمتر" : `نمایش همه ${faNumber(plan.items.length)} کالا`}</Button>
        </div>
      )}
      <div className="flex items-center gap-2 border-t border-border px-5 py-3 text-xs text-muted"><Landmark className="size-3.5" />مبالغ به ریال؛ * یعنی بهای خرید ثبت نشده و قیمت فروش مبنا بوده است.</div>
    </>
  );
}
