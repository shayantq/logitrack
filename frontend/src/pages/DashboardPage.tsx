import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlertTriangle, ArrowLeft, Boxes, ChevronDown, Package, PackageCheck, PieChart, Truck, Zap } from "lucide-react";
import { api, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { ActionCenter } from "@/components/ActionCenter";
import { OrderStatusBadge } from "@/components/StatusBadges";
import { ACTIVE_ORDER_STATUSES, orderStatusLabel, orderStatusTone, VEHICLE_STATUS, VEHICLE_STATUS_TONE } from "@/lib/labels";
import { faNumber, faShortDateTime } from "@/lib/format";
import { BarChart, DonutChart } from "@/ui/brand";
import { Badge, Card, CardHeader, EmptyState, ErrorState, PageHeader, Skeleton, StatCard, Table, cn, toneColor } from "@/ui/primitives";

interface Stats {
  orders_by_status: Record<string, number>;
  vehicles_by_status: Record<string, number>;
  low_stock_products: { name: string; sku: string; stock: number; reorder_point: number; warehouse: string | null }[];
  total_orders: number;
  total_products: number;
  total_vehicles: number;
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "صبح بخیر" : h < 17 ? "روز بخیر" : "عصر بخیر";
}

/** نمای کلی (نمودارها) زیر مرکز اقدام است و جمع‌شدنش برای هر کاربر در همین مرورگر به یاد می‌ماند */
function useOverviewOpen() {
  const [open, setOpen] = useState(() => { try { return localStorage.getItem("dashboard-overview") !== "closed"; } catch { return true; } });
  useEffect(() => { try { localStorage.setItem("dashboard-overview", open ? "open" : "closed"); } catch { /* */ } }, [open]);
  return [open, setOpen] as const;
}

export default function DashboardPage() {
  const me = useMe();
  const [overviewOpen, setOverviewOpen] = useOverviewOpen();
  const stats = useQuery({ queryKey: ["stats"], queryFn: async () => (await unwrap(api.GET("/reports/stats"))) as Stats, refetchInterval: 15_000 });
  const recent = useQuery({
    queryKey: ["orders", "recent"],
    queryFn: () => unwrap(api.GET("/orders/", { params: { query: { limit: 6 } } })),
    refetchInterval: 15_000,
  });

  const data = stats.data;
  const active = data ? ACTIVE_ORDER_STATUSES.reduce((sum, s) => sum + (data.orders_by_status[s] ?? 0), 0) : 0;

  return (
    <>
      <PageHeader eyebrow="نمای کلی" title={`${greeting()}، ${me.full_name || me.username}`} subtitle="وضعیت لحظه‌ای سفارش‌ها، ناوگان و موجودی — هر ۱۵ ثانیه به‌روز می‌شود." />
      <ActionCenter />

      <button type="button" onClick={() => setOverviewOpen(o => !o)} aria-expanded={overviewOpen} data-testid="overview-toggle"
        className="mb-3 flex w-full items-center justify-between gap-3 text-start">
        <h2 className="text-base font-bold">نمای کلی</h2>
        <ChevronDown className={cn("size-5 text-muted transition-transform duration-200", overviewOpen && "rotate-180")} />
      </button>
      {overviewOpen && <div className="animate-fade">
      {stats.error && <ErrorState error={stats.error} onRetry={stats.refetch} />}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {!data ? Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-32 rounded-2xl" />) : <>
          <StatCard label="کل سفارش‌ها" value={faNumber(data.total_orders)} icon={<PackageCheck className="size-[18px]" />} />
          <StatCard label="سفارش‌های فعال" value={faNumber(active)} tone="orange" icon={<Zap className="size-[18px]" />} hint="در انتظار تا در مسیر" />
          <StatCard label="کالاها" value={faNumber(data.total_products)} tone="info" icon={<Boxes className="size-[18px]" />} />
          <StatCard label="خودروها" value={faNumber(data.total_vehicles)} tone="violet" icon={<Truck className="size-[18px]" />} />
        </>}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="سفارش‌ها بر اساس وضعیت" icon={<PieChart className="size-[18px]" />} />
          <div className="p-5">{data ? <DonutChart data={Object.entries(data.orders_by_status).map(([s, v]) => ({ label: orderStatusLabel(s), value: v, color: toneColor(orderStatusTone(s)) }))} />
            : <Skeleton className="h-44" />}</div>
        </Card>
        <Card>
          <CardHeader title="ناوگان بر اساس وضعیت" icon={<Truck className="size-[18px]" />} tone="violet" />
          <div className="p-5">{data ? <BarChart data={Object.entries(data.vehicles_by_status).map(([s, v]) => ({ label: VEHICLE_STATUS[s] ?? s, value: v, color: toneColor(VEHICLE_STATUS_TONE[s] ?? "muted") }))} />
            : <Skeleton className="h-44" />}</div>
        </Card>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader title="آخرین سفارش‌ها" icon={<Package className="size-[18px]" />} tone="info" actions={<Link to="/app/orders" className="tap-target inline-flex items-center gap-1 text-sm font-medium text-brand">همه سفارش‌ها <ArrowLeft className="size-4" /></Link>} />
          {!recent.data ? <div className="p-5"><Skeleton className="h-40" /></div> : recent.data.length === 0 ? <EmptyState title="هنوز سفارشی ثبت نشده" /> : (
            <ul className="divide-y divide-border">
              {recent.data.map((o: Schemas["OrderResponse"]) => (
                <li key={o.id} className="flex items-center justify-between gap-3 px-5 py-3">
                  <div className="min-w-0">
                    <div className="font-mono text-sm font-semibold ltr">{o.tracking_code}</div>
                    <div className="truncate text-xs text-muted">{o.customer?.name} — {o.destination_city} · {faShortDateTime(o.created_at)}</div>
                  </div>
                  <OrderStatusBadge status={o.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader title="کالاهای رو‌به‌اتمام" subtitle="به تفکیک انبار" icon={<AlertTriangle className="size-[18px]" />} tone="warning"
            actions={<Link to="/app/reorder" className="tap-target text-xs font-medium text-brand hover:underline">نقطه سفارش ←</Link>} />
          {!data ? <div className="p-5"><Skeleton className="h-40" /></div> : data.low_stock_products.length === 0 ? (
            <EmptyState title="همه کالاها بالای حد آستانه‌اند" icon={<PackageCheck className="size-5" />} />
          ) : (
            <Table>
              <thead><tr><th>کالا</th><th>انبار</th><th>موجودی</th></tr></thead>
              <tbody>
                {data.low_stock_products.slice(0, 8).map(p => (
                  <tr key={`${p.sku}-${p.warehouse}`}>
                    <td><div className="font-medium">{p.name}</div><div className="font-mono text-xs text-muted">{p.sku}</div></td>
                    <td className="text-text-2">{p.warehouse ?? "—"}</td>
                    <td><Badge tone={p.stock === 0 ? "danger" : "warning"}>{faNumber(p.stock)} / {faNumber(p.reorder_point)}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>
      </div>}
    </>
  );
}
