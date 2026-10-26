/**
 * داشبورد شاخص‌های عملکرد (فصل ۲۸): نُه شاخص با هدف و وضعیت (رنگ + نماد + برچسب، نه رنگ تنها)، هشدارها،
 * وضعیت لحظه‌ای و روند روزانه — همه از داده‌های عملیاتی همان لحظه. خروجی اکسل/PDF/CSV در پس‌زمینه.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleDashed, FileSpreadsheet, FileText, Gauge, Info, MinusCircle, Sheet, XCircle } from "lucide-react";
import { api, unwrap, type Schemas } from "@/api/client";
import { useToast } from "@/components/Toast";
import { useAsyncExport } from "@/hooks/data";
import { faDate, faNumber } from "@/lib/format";
import { Badge, Button, Card, CardHeader, ErrorState, Field, PageHeader, Skeleton, cn, toneColor, type Tone } from "@/ui/primitives";
import { PeriodPicker, presetRange, type Period } from "../reports/period";
import { WarehousePicker, useWarehouseChoice } from "../warehouse/shared";

type Kpi = Schemas["KpiOut"];
type Point = Schemas["TrendPoint"];
const STATUS: Record<Kpi["status"], { label: string; tone: Tone; icon: typeof CheckCircle2 }> = {
  good: { label: "در هدف", tone: "success", icon: CheckCircle2 },
  warn: { label: "نزدیک هدف", tone: "warning", icon: MinusCircle },
  bad: { label: "دور از هدف", tone: "danger", icon: XCircle },
  none: { label: "بدون داده", tone: "muted", icon: CircleDashed },
};
const SNAPSHOT: [string, string][] = [["open_orders", "سفارش باز"], ["backorder_units", "واحد معوق"], ["open_putaway", "جانمایی باز"],
  ["pending_inspection", "در انتظار بازرسی"], ["active_stocktakes", "انبارگردانی فعال"], ["low_stock", "زیر نقطه سفارش"], ["on_hand_units", "موجودی (واحد)"]];

export default function AnalyticsPage() {
  const toast = useToast();
  const choice = useWarehouseChoice(null, false);
  const [period, setPeriod] = useState<Period>(() => ({ preset: "quarter", ...presetRange("quarter") }));
  const warehouseId = choice.value ? Number(choice.value) : null;
  const query = useQuery({
    queryKey: ["analytics", period.from, period.to, warehouseId],
    queryFn: () => unwrap(api.GET("/analytics/kpis", { params: { query: { date_from: period.from, date_to: period.to, warehouse_id: warehouseId } } })),
  });
  const exporter = useAsyncExport(toast.error, () => toast.success("گزارش شاخص‌ها آماده و دانلود شد."));
  const exportAs = (format: "excel" | "pdf" | "csv") => exporter.run("/reports/generate", `Pasineh_KPI.${format === "excel" ? "xlsx" : format}`,
    { report: "kpi", format, date_from: period.from, date_to: period.to, ...(warehouseId ? { warehouse_id: warehouseId } : {}) }, `kpi-${format}`);
  const data = query.data;

  return (
    <>
      <PageHeader eyebrow="نمای کلی" title="شاخص‌های عملکرد"
        subtitle="دقت موجودی، تحقق سفارش، دقت برداشت، رسید تا قفسه، گردش موجودی، ضایعات و بهره‌وری ظرفیت — با هدف هر شاخص"
        actions={<div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" icon={<FileSpreadsheet className="size-4" />} loading={exporter.running === "kpi-excel"} onClick={() => exportAs("excel")} data-testid="kpi-export-excel">اکسل</Button>
          <Button size="sm" variant="secondary" icon={<FileText className="size-4" />} loading={exporter.running === "kpi-pdf"} onClick={() => exportAs("pdf")}>PDF</Button>
          <Button size="sm" variant="ghost" icon={<Sheet className="size-4" />} loading={exporter.running === "kpi-csv"} onClick={() => exportAs("csv")}>CSV</Button>
        </div>} />
      <Card className="mb-5 p-4">
        <div className="flex flex-wrap items-end gap-4">
          <Field label="بازه"><PeriodPicker value={period} onChange={setPeriod} /></Field>
          <Field label="انبار" className="w-56"><WarehousePicker choice={choice} allowAll testId="kpi-warehouse" /></Field>
        </div>
      </Card>

      {query.isLoading ? <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{Array.from({ length: 9 }, (_, i) => <Skeleton key={i} className="h-36" />)}</div>
        : query.error ? <ErrorState error={query.error} onRetry={query.refetch} /> : data && (
          <>
            {data.alerts.length > 0 && (
              <div className="mb-5 space-y-2" data-testid="kpi-alerts">
                {data.alerts.map((a, i) => (
                  <p key={i} className={cn("flex items-start gap-2 rounded-xl px-4 py-2.5 text-sm",
                    a.level === "danger" ? "bg-danger-soft text-text" : a.level === "warning" ? "bg-warning-soft text-text" : "bg-info-soft text-text")}>
                    {a.level === "info" ? <Info className="mt-0.5 size-4 shrink-0 text-info" /> : <AlertTriangle className={cn("mt-0.5 size-4 shrink-0", a.level === "danger" ? "text-danger" : "text-warning")} />}
                    {a.text}</p>
                ))}
              </div>
            )}
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="kpi-grid">
              {data.kpis.map(k => <KpiTile key={k.key} kpi={k} />)}
            </div>
            <Card className="mt-5 p-4">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7" data-testid="kpi-snapshot">
                {SNAPSHOT.map(([key, label]) => (
                  <div key={key} className="rounded-xl bg-surface-2 px-3 py-2.5">
                    <div className="text-xs text-muted">{label}</div>
                    <div className="mt-0.5 text-lg font-bold tnum">{faNumber(data.snapshot[key] ?? 0)}</div>
                  </div>
                ))}
              </div>
            </Card>
            <div className="mt-5 grid gap-5 lg:grid-cols-2">
              <TrendChart title="سفارش‌ها در روز" points={data.trend} series={[["orders", "ثبت‌شده"], ["delivered", "تحویل‌شده"]]} unit="سفارش" />
              <TrendChart title="گردش کالا در روز" points={data.trend} series={[["received_units", "واردشده"], ["shipped_units", "خارج‌شده"]]} unit="واحد" />
            </div>
          </>
        )}
    </>
  );
}

function KpiTile({ kpi }: { kpi: Kpi }) {
  const s = STATUS[kpi.status];
  const Icon = s.icon;
  const unit = kpi.unit === "%" ? "٪" : ` ${kpi.unit}`;
  return (
    <Card className="flex flex-col p-5" data-testid="kpi-tile" data-key={kpi.key} data-status={kpi.status}>
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm font-semibold text-text-2">{kpi.label}</div>
        <Badge tone={s.tone}><Icon className="size-3.5" />{s.label}</Badge>
      </div>
      <div className="mt-3 flex items-baseline gap-1">
        <span className="text-3xl font-extrabold tnum text-text">{kpi.value === null || kpi.value === undefined ? "—" : faNumber(kpi.value)}</span>
        {kpi.value !== null && kpi.value !== undefined && <span className="text-sm text-muted">{unit}</span>}
      </div>
      <div className="mt-1 text-xs text-muted">هدف {kpi.higher_better ? "حداقل" : "حداکثر"} {faNumber(kpi.target)}{unit}</div>
      {kpi.value !== null && kpi.value !== undefined && kpi.unit === "%" && (
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden>
          <div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.min(100, kpi.value)}%`, background: toneColor(s.tone) }} />
        </div>
      )}
      <p className="mt-auto pt-3 text-xs leading-5 text-text-2">{kpi.detail}</p>
      <p className="mt-1 text-[11px] leading-5 text-muted">{kpi.hint}</p>
    </Card>
  );
}

/** دو سری میله‌ای کنار هم در هر روز؛ رنگ‌ها --chart-1/--chart-2 (بررسی‌شده برای کوررنگی در هر دو تم) + راهنما و جدول */
function TrendChart({ title, points, series, unit }: { title: string; points: Point[]; series: [keyof Point, string][]; unit: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const max = useMemo(() => Math.max(1, ...points.flatMap(p => series.map(([k]) => Number(p[k]) || 0))), [points, series]);
  const W = 640, H = 200, pad = 26;
  const slot = (W - pad) / Math.max(points.length, 1);
  const bar = Math.max(2, Math.min(10, (slot - 4) / series.length - 1));
  const colors = ["var(--chart-1)", "var(--chart-2)"];
  const ticks = [0, 0.5, 1].map(t => Math.round(max * t));
  const active = hover !== null ? points[hover] : null;
  return (
    <Card data-testid="kpi-trend">
      <CardHeader title={title} icon={<Gauge className="size-4" />} actions={
        <button type="button" className="text-xs text-brand hover:underline" onClick={() => setTable(t => !t)}>{table ? "نمودار" : "جدول"}</button>} />
      <div className="flex flex-wrap items-center gap-4 px-5 pt-1 text-xs text-text-2">
        {series.map(([k, label], i) => <span key={String(k)} className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm" style={{ background: colors[i] }} />{label}</span>)}
        {active && <span className="ms-auto font-medium text-text">{faDate(active.day)}: {series.map(([k, l]) => `${l} ${faNumber(Number(active[k]))}`).join(" · ")} {unit}</span>}
      </div>
      {table ? (
        <div className="max-h-64 overflow-y-auto p-3"><table className="table-base">
          <thead><tr><th>روز</th>{series.map(([k, l]) => <th key={String(k)}>{l}</th>)}</tr></thead>
          <tbody>{points.map(p => <tr key={p.day}><td className="text-xs">{faDate(p.day)}</td>{series.map(([k]) => <td key={String(k)} className="tnum">{faNumber(Number(p[k]))}</td>)}</tr>)}</tbody>
        </table></div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H + 18}`} className="w-full" role="img" aria-label={title} onMouseLeave={() => setHover(null)}>
          {ticks.map(t => {
            const y = H - (t / max) * (H - 10);
            return <g key={t}><line x1={pad} x2={W} y1={y} y2={y} stroke="var(--border)" strokeDasharray={t ? "3 4" : undefined} />
              <text x={pad - 4} y={y + 3} textAnchor="end" fontSize="9" fill="var(--muted)">{faNumber(t)}</text></g>;
          })}
          {points.map((p, i) => {
            const x0 = W - (i + 1) * slot;                                   // راست‌به‌چپ: قدیمی‌ترین روز سمت راست
            return (
              <g key={p.day} onMouseEnter={() => setHover(i)}>
                <rect x={x0} y={0} width={slot} height={H} fill={hover === i ? "var(--surface-2)" : "transparent"} />
                {series.map(([k], si) => {
                  const v = Number(p[k]) || 0;
                  const h = (v / max) * (H - 10);
                  return <rect key={String(k)} x={x0 + slot / 2 - (series.length * (bar + 2)) / 2 + si * (bar + 2)} y={H - h}
                    width={bar} height={Math.max(h, v ? 1 : 0)} rx={Math.min(4, bar / 2)} fill={colors[si]} />;
                })}
                {(i % Math.ceil(points.length / 6) === 0) && <text x={x0 + slot / 2} y={H + 13} textAnchor="middle" fontSize="9" fill="var(--muted)">{faDate(p.day).slice(5)}</text>}
              </g>
            );
          })}
        </svg>
      )}
    </Card>
  );
}
