/** خانه مدیرعامل: سلامت کسب‌وکار. هر عدد به فهرستی می‌رود که همان عدد را می‌سازد. */
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowLeft, ArrowUp, CheckCircle2, Circle, Coins, Gauge, Rocket, TimerOff } from "lucide-react";
import { api, unwrap, type Schemas } from "@/api/client";
import { UpdatedAt } from "@/components/UpdatedAt";
import { faNumber } from "@/lib/format";
import { faMoneyShort } from "@/pages/reports/period";
import { Badge, Card, CardHeader, EmptyState, ErrorState, Skeleton, cn } from "@/ui/primitives";

const KPI_STATUS: Record<string, { label: string; tone: "success" | "warning" | "danger" | "muted" }> = {
  good: { label: "در هدف", tone: "success" }, warn: { label: "نزدیک هدف", tone: "warning" },
  bad: { label: "زیر هدف", tone: "danger" }, unknown: { label: "بدون داده", tone: "muted" },
};
const unitText = (v: number | null | undefined, unit: string) => v === null || v === undefined ? "—" : `${faNumber(v)}${unit === "%" ? "٪" : ` ${unit}`}`;

export function SetupChecklist({ steps }: { steps: Schemas["SetupStep"][] }) {
  const done = steps.filter(s => s.done).length;
  if (done === steps.length) return null;
  return (
    <Card className="mb-6" data-testid="setup-checklist">
      <CardHeader title="شروع کار" subtitle={`${faNumber(done)} از ${faNumber(steps.length)} قدم انجام شده`} icon={<Rocket className="size-[18px]" />}
        actions={<Link to="/app/readiness" className="tap-target text-xs font-medium text-brand hover:underline">جزئیات راه‌اندازی</Link>} />
      <ul className="divide-y divide-border">
        {steps.map(step => (
          <li key={step.key}>
            <Link to={step.link} data-testid={`setup-${step.key}`} data-done={step.done ? "1" : "0"}
              className="flex items-center gap-3 px-5 py-3 text-sm transition hover:bg-surface-2">
              {step.done ? <CheckCircle2 className="size-5 shrink-0 text-success" /> : <Circle className="size-5 shrink-0 text-muted" />}
              <span className={cn("flex-1", step.done && "text-muted line-through")}>{step.label}</span>
              {step.done ? <Badge tone="success">انجام شد</Badge> : <ArrowLeft className="size-4 text-muted" />}
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Trend({ kpi }: { kpi: Schemas["HomeKpi"] }) {
  if (kpi.value === null || kpi.value === undefined || kpi.previous === null || kpi.previous === undefined) {
    return <span className="text-xs text-muted">دوره قبل: {unitText(kpi.previous, kpi.unit)}</span>;
  }
  const up = kpi.value > kpi.previous;
  const same = kpi.value === kpi.previous;
  const Icon = up ? ArrowUp : ArrowDown;
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted">
      {!same && <Icon className="size-3.5" aria-hidden />}
      {same ? "بدون تغییر نسبت به" : up ? "بیشتر از" : "کمتر از"} دوره قبل ({unitText(kpi.previous, kpi.unit)})
    </span>
  );
}

export function BusinessHome() {
  const q = useQuery({ queryKey: ["home-business"], queryFn: () => unwrap(api.GET("/home/business")), refetchInterval: 60_000 });
  if (q.error) return <ErrorState error={q.error} onRetry={q.refetch} />;
  if (!q.data) return <Skeleton className="mb-6 h-64 rounded-2xl" />;
  const { kpis, delays, exceptions, stock, money, setup, generated_at: at } = q.data;
  const urgent = exceptions.critical + exceptions.high;
  const problems = delays.late + delays.at_risk;
  return (
    <div data-testid="business-home">
      <SetupChecklist steps={setup} />
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-bold">سلامت کسب‌وکار</h2>
        <UpdatedAt at={`${at}Z`} label="محاسبه" />
      </div>
      <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3" data-testid="business-summary">
        <SummaryLink to="/app/orders?view=late" testId="biz-late" label="سفارش دیرکرده یا در خطر" value={problems} tone={problems ? "danger" : "success"}
          text={`${faNumber(delays.late)} دیرکرده، ${faNumber(delays.at_risk)} در خطر`} />
        <SummaryLink to={stock.link} testId="biz-stock" label="کالای رو به اتمام" value={stock.low + stock.out} tone={stock.out ? "danger" : stock.low ? "warning" : "success"}
          text={`${faNumber(stock.out)} تمام‌شده، ${faNumber(stock.low)} زیر نقطه سفارش`} />
        <SummaryLink to={exceptions.link} testId="biz-exceptions" label="استثنای مهم باز" value={urgent} tone={exceptions.critical ? "danger" : urgent ? "warning" : "success"}
          text={`${faNumber(exceptions.critical)} بحرانی، ${faNumber(exceptions.high)} زیاد`} />
      </div>

      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="عملکرد ۳۰ روز اخیر" subtitle="در برابر ۳۰ روز پیش از آن" icon={<Gauge className="size-[18px]" />} />
          <ul className="divide-y divide-border">
            {kpis.map(k => (
              <li key={k.key}>
                <Link to={k.link} data-testid={`biz-kpi-${k.key}`} title={k.hint} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 py-3 transition hover:bg-surface-2">
                  <span className="flex-1 text-sm font-medium">{k.label}</span>
                  <span className="font-bold tnum">{unitText(k.value, k.unit)}</span>
                  <Badge tone={KPI_STATUS[k.status]?.tone ?? "muted"} dot>{KPI_STATUS[k.status]?.label ?? k.status}</Badge>
                  <span className="basis-full"><Trend kpi={k} /></span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <CardHeader title="چرا سفارش‌ها دیر می‌شوند" subtitle="سفارش‌های دیرکرده و در خطر، هر کدام با یک علت" icon={<TimerOff className="size-[18px]" />} tone="orange" />
          {delays.causes.length === 0 ? <EmptyState icon={<CheckCircle2 className="size-5" />} title="سفارش دیرکرده‌ای نیست" /> : (
            <ul className="divide-y divide-border" data-testid="biz-delay-causes">
              {delays.causes.map(c => (
                <li key={c.key}>
                  <Link to={c.link} className="flex items-center gap-3 px-5 py-3 text-sm transition hover:bg-surface-2">
                    <span className="flex-1">{c.label}</span><span className="font-bold tnum">{faNumber(c.count)}</span><ArrowLeft className="size-4 text-muted" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card className="mb-6" data-testid="biz-money">
        <CardHeader title="درآمد و حاشیه سود" subtitle={`${faNumber(money.window_days)} روز اخیر، از کرایه، قیمت فروش و بهای ثبت‌شده`} icon={<Coins className="size-[18px]" />} tone="violet"
          actions={<span data-testid="biz-money-estimate"><Badge tone="warning">برآورد</Badge></span>} />
        <dl className="grid grid-cols-2 gap-4 p-5 lg:grid-cols-4">
          <Money label="کرایه سفرهای تحویل‌شده" value={money.fare} />
          <Money label="سهم راننده" value={money.driver_share} />
          <Money label="سهم سازمان از کرایه" value={money.company_share} />
          <Money label="حاشیه کالا" value={money.goods_margin} />
        </dl>
        <p className="border-t border-border px-5 py-3 text-xs leading-6 text-muted">
          هزینه‌های واقعی مثل حقوق، سوخت و اجاره در این عدد نیست، پس این سود حسابداری نیست.
          حاشیه کالا برای {faNumber(money.cost_coverage_lines)} از {faNumber(money.total_lines)} ردیف سفارش که بهای تمام‌شده دارند حساب شده است.
          <Link to="/app/finance" className="ms-1 font-medium text-brand hover:underline">گزارش مالی حمل</Link>
        </p>
        {money.top_products.length > 0 && (
          <ul className="border-t border-border px-5 py-3 text-sm" data-testid="biz-top-margin">
            {money.top_products.map(p => (
              <li key={p.product_id} className="flex justify-between gap-3 py-1"><span className="truncate">{p.name}</span><span className="tnum">{faMoneyShort(p.margin)}</span></li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Money({ label, value }: { label: string; value: number }) {
  return <div><dt className="text-xs text-muted">{label}</dt><dd className="mt-1 text-lg font-black tnum" title={`${faNumber(value)} ریال`}>{faMoneyShort(value)}</dd></div>;
}

function SummaryLink({ to, label, value, text, tone, testId }: {
  to: string; label: string; value: number; text: string; tone: "danger" | "warning" | "success"; testId: string;
}) {
  return (
    <Link to={to} data-testid={testId} className="card flex items-center gap-4 p-5 transition hover:border-brand">
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">{label}</div>
        <div className="mt-1 text-xs text-muted">{text}</div>
      </div>
      <Badge tone={tone} className="text-base">{faNumber(value)}</Badge>
    </Link>
  );
}
