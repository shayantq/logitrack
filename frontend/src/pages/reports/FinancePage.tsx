import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { BarChart3, Building2, FileSpreadsheet, FileText, Gauge, MapPinned, Route, Truck, UserRound, Wallet, XCircle } from "lucide-react";
import { api, unwrap, type Schemas } from "@/api/client";
import { useToast } from "@/components/Toast";
import { useAsyncExport } from "@/hooks/data";
import { faNumber } from "@/lib/format";
import { Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, Skeleton, StatCard, Table } from "@/ui/primitives";
import { PeriodPicker, faMoneyShort, usePeriod } from "./period";

type Finance = Schemas["FinanceSummary"];
const rial = (v: number) => `${faNumber(Math.round(v))} ریال`;
/** کیلومتر صفر یعنی مسیر سفر ثبت نشده — «۰» گمراه‌کننده است */
const km = (v: number) => (v ? faNumber(v) : "—");

/** ستون‌های ماهانه: کل ارتفاع = کرایه، بخش پررنگ = سهم سازمان */
function MonthlyBars({ data }: { data: Finance["by_month"] }) {
  const max = Math.max(1, ...data.map(m => m.fare));
  return (
    <div className="flex h-56 items-end gap-3 overflow-x-auto px-1 pb-1" data-testid="finance-months">
      {data.map(m => (
        <div key={m.month} className="flex min-w-16 flex-1 flex-col items-center gap-2">
          <span className="text-xs font-semibold tnum">{faMoneyShort(m.fare)}</span>
          <div className="flex w-full max-w-20 flex-col justify-end overflow-hidden rounded-t-lg bg-brand/25 transition-all duration-700"
            style={{ height: `${Math.max(4, (m.fare / max) * 150)}px` }}>
            <div className="w-full bg-brand transition-all duration-700" style={{ height: `${m.fare ? (m.company / m.fare) * 100 : 0}%` }} />
          </div>
          <span className="whitespace-nowrap text-center text-xs text-muted">{m.month}</span>
        </div>
      ))}
    </div>
  );
}

/** نوار سهم: سازمان (پررنگ) / راننده */
function ShareBar({ company, fare }: { company: number; fare: number }) {
  const pct = fare ? Math.round((company / fare) * 100) : 0;
  return (
    <div className="flex min-w-28 items-center gap-2">
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-brand/20"><div className="h-full rounded-full bg-brand" style={{ width: `${pct}%` }} /></div>
      <span className="w-9 text-xs tnum text-muted">{faNumber(pct)}٪</span>
    </div>
  );
}

export default function FinancePage() {
  const toast = useToast();
  const [period, setPeriod] = usePeriod();
  const exporter = useAsyncExport(toast.error, () => toast.success("گزارش آماده و دانلود شد."));
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["finance", period.from, period.to],
    queryFn: () => unwrap(api.GET("/reports/finance", { params: { query: { date_from: period.from, date_to: period.to } } })),
    placeholderData: keepPreviousData,
  });
  const download = (format: "excel" | "pdf") => exporter.run("/reports/generate", `LogiTrack_Transport_Finance.${format === "pdf" ? "pdf" : "xlsx"}`,
    { report: "finance", format, date_from: period.from, date_to: period.to }, `finance-${format}`);
  const k = data?.kpis;

  return (
    <>
      <PageHeader eyebrow="گزارش‌ها" title="مالی حمل‌ونقل"
        subtitle="کرایه سفرهای تحویل‌شده و تقسیم آن بین سازمان (پورسانت) و رانندگان — بر اساس روز تحویل."
        actions={<>
          <Button variant="secondary" size="sm" icon={<FileSpreadsheet className="size-4" />} loading={exporter.running === "finance-excel"}
            disabled={!!exporter.running} onClick={() => download("excel")} data-testid="finance-excel">اکسل</Button>
          <Button variant="secondary" size="sm" icon={<FileText className="size-4" />} loading={exporter.running === "finance-pdf"}
            disabled={!!exporter.running} onClick={() => download("pdf")} data-testid="finance-pdf">PDF</Button>
        </>} />
      <Card className="mb-6 p-4"><PeriodPicker value={period} onChange={setPeriod} /></Card>

      {error ? <ErrorState error={error} onRetry={refetch} /> : isLoading || !data || !k ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-32 rounded-2xl" />)}</div>
      ) : (
        <div className={isFetching ? "opacity-70 transition-opacity" : "transition-opacity"} data-testid="finance-dashboard" data-trips={k.trips}>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="مجموع کرایه" value={faMoneyShort(k.fare)} hint={rial(k.fare)} icon={<Wallet className="size-5" />} />
            <StatCard label="سهم سازمان (پورسانت)" value={faMoneyShort(k.company)} hint={`${faNumber(k.take_rate)}٪ از کرایه`} icon={<Building2 className="size-5" />} tone="violet" />
            <StatCard label="پرداختی رانندگان" value={faMoneyShort(k.driver)} hint={rial(k.driver)} icon={<UserRound className="size-5" />} tone="info" />
            <StatCard label="سفرهای تحویل‌شده" value={faNumber(k.trips)} hint={`میانگین هر سفر ${faMoneyShort(k.avg_fare)} ریال`} icon={<Truck className="size-5" />} tone="success" />
            <StatCard label="کیلومتر پیمایش" value={km(k.km)} hint={k.km ? undefined : "مسیر سفرها ثبت نشده است"} icon={<Route className="size-5" />} tone="orange" />
            <StatCard label="کرایه هر کیلومتر" value={km(k.fare_per_km)} hint={k.fare_per_km ? "ریال" : "بدون مسیر محاسبه نمی‌شود"} icon={<Gauge className="size-5" />} tone="pink" />
            <StatCard label="ناموفق / لغو / منقضی" value={faNumber(k.failed)} hint="در همین بازه (روز تحویل)" icon={<XCircle className="size-5" />} tone="danger" />
            <StatCard label="استان‌های مقصد" value={faNumber(data.by_province.length)} icon={<MapPinned className="size-5" />} tone="muted" />
          </div>

          {k.trips === 0 ? (
            <Card className="mt-6"><EmptyState icon={<Wallet className="size-5" />} title="در این بازه سفر تحویل‌شده‌ای نیست" text="بازه دیگری انتخاب کنید." /></Card>
          ) : (
            <>
              <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-5">
                <Card className="min-w-0 xl:col-span-2">
                  <CardHeader title="روند ماهانه" subtitle="ارتفاع: کل کرایه — بخش پررنگ: سهم سازمان (ریال)" icon={<BarChart3 className="size-[18px]" />} />
                  <div className="p-5"><MonthlyBars data={data.by_month} /></div>
                </Card>
                <Card className="min-w-0 xl:col-span-3">
                  <CardHeader title="به تفکیک راننده" icon={<UserRound className="size-[18px]" />} tone="info" />
                  <Table testId="finance-drivers">
                    <thead><tr><th>راننده</th><th>سفر</th><th>کیلومتر</th><th>کرایه</th><th>سهم سازمان</th><th>سهم راننده</th></tr></thead>
                    <tbody>
                      {data.by_driver.map(d => (
                        <tr key={d.driver}>
                          <td className="font-medium">{d.driver}</td>
                          <td className="tnum">{faNumber(d.trips)}</td>
                          <td className="tnum">{km(d.km)}</td>
                          <td className="tnum whitespace-nowrap">{faNumber(d.fare)}</td>
                          <td><ShareBar company={d.company} fare={d.fare} /></td>
                          <td className="tnum whitespace-nowrap font-semibold">{faNumber(d.driver_share)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </Card>
              </div>
              <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-5">
                <Card className="min-w-0 xl:col-span-2">
                  <CardHeader title="به تفکیک استان مقصد" icon={<MapPinned className="size-[18px]" />} tone="pink" />
                  <Table testId="finance-provinces">
                    <thead><tr><th>استان</th><th>سفر</th><th>کیلومتر</th><th>کرایه</th></tr></thead>
                    <tbody>
                      {data.by_province.map(p => (
                        <tr key={p.province}><td className="font-medium">{p.province}</td><td className="tnum">{faNumber(p.trips)}</td>
                          <td className="tnum">{km(p.km)}</td><td className="tnum whitespace-nowrap">{faNumber(p.fare)}</td></tr>
                      ))}
                    </tbody>
                  </Table>
                </Card>
                <Card className="min-w-0 xl:col-span-3">
                  <CardHeader title="آخرین سفرها" icon={<Route className="size-[18px]" />} tone="orange" subtitle={data.details.length >= 200 ? "۲۰۰ سفر آخر بازه — همه سفرها در فایل اکسل/PDF" : undefined} />
                  <div className="max-h-[28rem] overflow-y-auto">
                    <Table testId="finance-trips">
                      <thead><tr><th>روز</th><th>کد</th><th>راننده</th><th>مقصد</th><th>درصد</th><th>کرایه</th><th>سهم سازمان</th></tr></thead>
                      <tbody>
                        {[...data.details].reverse().map(d => (
                          <tr key={d.code}>
                            <td className="whitespace-nowrap text-xs text-text-2">{d.day.replace(/\d/g, x => "۰۱۲۳۴۵۶۷۸۹"[Number(x)])}</td>
                            <td className="whitespace-nowrap font-mono text-xs">{d.code}</td>
                            <td className="whitespace-nowrap">{d.driver}</td>
                            <td className="text-xs text-text-2">{d.dest}</td>
                            <td className="tnum text-xs">{d.percent != null ? `${faNumber(d.percent)}٪` : "—"}</td>
                            <td className="tnum whitespace-nowrap">{faNumber(d.fare)}</td>
                            <td className="tnum whitespace-nowrap">{faNumber(d.company)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  </div>
                </Card>
              </div>
            </>
          )}
        </div>
      )}
    </>
  );
}
