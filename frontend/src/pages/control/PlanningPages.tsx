/** مقایسه انبارها و تیم‌ها (فقط ادمین) و نمای ظرفیت یک روز. هر دو فقط می‌خوانند. */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { api, unwrap } from "@/api/client";
import { UpdatedAt } from "@/components/UpdatedAt";
import { faNumber } from "@/lib/format";
import { DateField } from "@/ui/datetime";
import { Badge, Card, CardHeader, EmptyState, ErrorState, Field, PageHeader, Skeleton, Table } from "@/ui/primitives";

const STATUS: Record<string, { label: string; tone: "success" | "warning" | "danger" | "muted" }> = {
  good: { label: "در هدف", tone: "success" }, warn: { label: "نزدیک هدف", tone: "warning" }, bad: { label: "زیر هدف", tone: "danger" }, unknown: { label: "بدون داده", tone: "muted" },
};
const iranToday = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tehran" }).format(new Date());

export function ComparisonPage() {
  const q = useQuery({ queryKey: ["planning-comparison"], queryFn: () => unwrap(api.GET("/planning/comparison")) });
  return (
    <div data-testid="comparison-page">
      <PageHeader eyebrow="مدیریت" title="مقایسه انبارها و تیم‌ها" subtitle="با تعریف‌های یکسان شاخص‌ها؛ رتبه‌بندی فردی در این صفحه نیست" actions={q.data && <UpdatedAt at={`${q.data.generated_at}Z`} label="محاسبه" />} />
      {q.isLoading ? <Skeleton className="h-64 rounded-2xl" /> : q.error ? <ErrorState error={q.error} onRetry={q.refetch} /> : q.data && (
        <div className="space-y-6">
          <Card>
            <CardHeader title="انبارها" subtitle={q.data.date_from && q.data.date_to ? `${q.data.date_from} تا ${q.data.date_to}` : undefined} />
            {!q.data.warehouses.length ? <EmptyState title="انباری تعریف نشده است" /> : (
              <Table testId="comparison-warehouses">
                <thead><tr><th>انبار</th>{q.data.metrics.map(m => <th key={m.key} title={m.definition}>{m.label}</th>)}</tr></thead>
                <tbody>
                  {q.data.warehouses.map(w => (
                    <tr key={w.warehouse_id}>
                      <td><Link to={w.link} className="font-medium text-brand hover:underline">{w.name}</Link></td>
                      {q.data!.metrics.map(m => {
                        const v = w.values[m.key];
                        return <td key={m.key} title={v?.detail ?? undefined}>{!v || v.insufficient ? <span className="text-xs text-muted">داده کافی نیست</span> : <>
                          <span className="tnum font-semibold">{faNumber(v.value)}{m.unit === "%" ? "٪" : ` ${m.unit}`}</span> <Badge tone={STATUS[v.status]?.tone ?? "muted"}>{STATUS[v.status]?.label ?? v.status}</Badge></>}</td>;
                      })}
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
            <ul className="space-y-1 border-t border-border p-4 text-xs leading-6 text-muted">{q.data.metrics.map(m => <li key={m.key}><b>{m.label}:</b> {m.definition}</li>)}</ul>
          </Card>
          <Card>
            <CardHeader title="تیم‌ها" subtitle="از استثناهای عملیاتی" />
            <Table testId="comparison-teams">
              <thead><tr><th>تیم</th><th>باز شده</th><th>بسته شده</th><th>باز الان</th><th>از مهلت گذشته</th><th>میانگین زمان بستن</th></tr></thead>
              <tbody>
                {q.data.teams.map(t => (
                  <tr key={t.team}>
                    <td><Link to={t.link} className="font-medium text-brand hover:underline">{t.label}</Link></td>
                    <td className="tnum">{faNumber(t.opened)}</td><td className="tnum">{faNumber(t.closed)}</td><td className="tnum">{faNumber(t.open_now)}</td><td className="tnum">{faNumber(t.overdue_now)}</td>
                    <td className="tnum">{t.avg_close_hours === null || t.avg_close_hours === undefined ? <span className="text-xs text-muted">داده کافی نیست</span> : `${faNumber(t.avg_close_hours)} ساعت`}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
          <ul className="space-y-1 text-xs leading-6 text-muted">{q.data.notes.map(n => <li key={n}>{n}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

export function CapacityPage() {
  const [day, setDay] = useState(iranToday);
  const q = useQuery({ queryKey: ["planning-capacity", day], queryFn: () => unwrap(api.GET("/planning/capacity", { params: { query: { day } } })), enabled: !!day });
  return (
    <div data-testid="capacity-page">
      <PageHeader eyebrow="برنامه‌ریزی" title="نمای ظرفیت" subtitle="از سفارش‌های ثبت‌شده و سقف‌های تعریف‌شده؛ این صفحه چیزی را تغییر نمی‌دهد" actions={q.data && <UpdatedAt at={`${q.data.generated_at}Z`} label="محاسبه" />} />
      <div className="mb-4 max-w-xs"><Field label="روز"><DateField required value={day} onChange={setDay} testId="capacity-day" /></Field></div>
      {q.isLoading ? <Skeleton className="h-64 rounded-2xl" /> : q.error ? <ErrorState error={q.error} onRetry={q.refetch} /> : q.data && (
        <div className="space-y-6">
          <Card data-testid="capacity-warnings">
            <CardHeader title="محدودیت‌ها" subtitle={`${faNumber(q.data.orders)} سفارش در این روز، ${faNumber(q.data.unassigned_orders)} بدون خودرو`} />
            {!q.data.warnings.length ? <EmptyState icon={<CheckCircle2 className="size-5" />} title="محدودیتی پیدا نشد" /> : (
              <ul className="divide-y divide-border">
                {q.data.warnings.map((w, i) => (
                  <li key={i}><Link to={w.link} className="flex items-start gap-3 px-5 py-3 text-sm transition hover:bg-surface-2"><AlertTriangle className={w.severity === "danger" ? "mt-0.5 size-4 shrink-0 text-danger" : "mt-0.5 size-4 shrink-0 text-warning"} /><span>{w.text}</span></Link></li>
                ))}
              </ul>
            )}
          </Card>
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader title="خودروها" />
              {!q.data.vehicles.length ? <EmptyState title="سفارشی به خودرویی نخورده است" /> : (
                <Table testId="capacity-vehicles">
                  <thead><tr><th>پلاک</th><th>سفارش</th><th>وزن</th><th>سقف</th></tr></thead>
                  <tbody>{q.data.vehicles.map(v => <tr key={v.vehicle_id}><td className="font-mono text-xs ltr text-start">{v.plate}</td><td className="tnum">{faNumber(v.orders)}</td><td className="tnum">{faNumber(v.weight_kg)}{v.over && <Badge tone="warning" className="ms-1">بیش از سقف</Badge>}</td><td className="tnum">{v.max_weight_kg ? faNumber(v.max_weight_kg) : "تعریف نشده"}</td></tr>)}</tbody>
                </Table>
              )}
            </Card>
            <Card>
              <CardHeader title="رانندگان" />
              {!q.data.drivers.length ? <EmptyState title="سفارشی به راننده‌ای نخورده است" /> : (
                <Table testId="capacity-drivers">
                  <thead><tr><th>راننده</th><th>سفارش</th><th>سقف روزانه</th></tr></thead>
                  <tbody>{q.data.drivers.map(d => <tr key={d.driver_id}><td>{d.name}{d.time_off && <Badge tone="danger" className="ms-1">مرخصی</Badge>}</td><td className="tnum">{faNumber(d.orders)}{d.over && <Badge tone="warning" className="ms-1">بیش از سقف</Badge>}</td><td className="tnum">{d.max_daily_orders ? faNumber(d.max_daily_orders) : "تعریف نشده"}</td></tr>)}</tbody>
                </Table>
              )}
            </Card>
          </div>
          <Card>
            <CardHeader title="کار انبار" subtitle="فقط شمار کار؛ سقف و نرخ کار تعریف نشده است" />
            <ul className="grid grid-cols-3 gap-3 p-5 text-sm">{q.data.workload.map(w => <li key={w.key}><div className="text-xs text-muted">{w.label}</div><div className="mt-1 text-lg font-black tnum">{faNumber(w.count)}</div></li>)}</ul>
          </Card>
          <ul className="space-y-1 text-xs leading-6 text-muted" data-testid="capacity-assumptions">{q.data.assumptions.map(a => <li key={a}>{a}</li>)}</ul>
        </div>
      )}
    </div>
  );
}
