import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight, Boxes, ClipboardList, History, KeyRound, LogIn, Package, Settings2, ShieldAlert, Truck, UserCog, type LucideIcon,
} from "lucide-react";
import { api, unwrap } from "@/api/client";
import { useWarehouses } from "@/hooks/data";
import { ROLE_LABELS, type Role } from "@/lib/labels";
import { faDateTime, faNumber } from "@/lib/format";
import { Badge, Card, CardHeader, DataList, EmptyState, ErrorState, PageHeader, Skeleton, StatCard, cn } from "@/ui/primitives";
import { OrderDetailModal } from "../orders/OrderDetailModal";
import { AccountBadges, ROLE_TONE, UserActionsMenu, timeAgo, useUserActions } from "./shared";

/** آیکن و رنگ هر نوع رویداد در خط زمانی */
function eventStyle(item: { kind: string; action: string; category: string }): { icon: LucideIcon; tone: string } {
  if (item.action === "auth.login") return { icon: LogIn, tone: "bg-success-soft text-success" };
  if (item.action === "auth.login_failed" || item.action === "auth.locked") return { icon: ShieldAlert, tone: "bg-danger-soft text-danger" };
  if (item.category === "auth") return { icon: KeyRound, tone: "bg-info-soft text-info" };
  if (item.kind === "order") return { icon: Package, tone: "bg-brand-soft text-brand-strong" };
  if (item.kind === "stock") return { icon: Boxes, tone: "bg-accent-soft text-warning" };
  if (item.category === "users") return { icon: UserCog, tone: "bg-violet-soft text-violet" };
  if (item.category === "drivers") return { icon: Truck, tone: "bg-brand-soft text-brand-strong" };
  if (item.category === "reports") return { icon: ClipboardList, tone: "bg-info-soft text-info" };
  return { icon: Settings2, tone: "bg-surface-2 text-muted" };
}

export default function UserDetailPage() {
  const id = Number(useParams().id);
  const actions = useUserActions();
  const [orderId, setOrderId] = useState<number | null>(null);
  const { data: warehouses = [] } = useWarehouses();
  const detail = useQuery({
    queryKey: ["user", id], queryFn: () => unwrap(api.GET("/users/{user_id}", { params: { path: { user_id: id } } })), enabled: id > 0,
  });
  const activity = useQuery({
    queryKey: ["user", id, "activity"], refetchInterval: 30_000,
    queryFn: () => unwrap(api.GET("/users/{user_id}/activity", { params: { path: { user_id: id }, query: { limit: 80 } } })), enabled: id > 0,
  });

  if (detail.error) return <ErrorState error={detail.error} onRetry={detail.refetch} />;
  if (!detail.data) return <div className="space-y-4"><Skeleton className="h-24 rounded-2xl" /><Skeleton className="h-96 rounded-2xl" /></div>;
  const { user: u, stats } = detail.data;
  const warehouse = warehouses.find(w => w.id === u.warehouse_id)?.name;

  return (
    <>
      <Link to="/app/users" className="mb-3 inline-flex items-center gap-1 text-sm text-muted transition hover:text-brand"><ArrowRight className="size-4" />کاربران</Link>
      <PageHeader eyebrow="تیم" title={u.full_name || u.username}
        subtitle={<span className="flex flex-wrap items-center gap-2"><span className="font-mono ltr">{u.username}</span>
          <Badge tone={ROLE_TONE[u.role] ?? "muted"}>{ROLE_LABELS[u.role as Role] ?? u.role}</Badge></span>}
        actions={<>
          {u.role === "driver" && <Link to={`/app/drivers/${u.id}`} className="text-sm font-medium text-brand hover:underline">کارنامه و پورسانت راننده ←</Link>}
          <UserActionsMenu u={u} actions={actions} showDetail={false} />
        </>} />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-6">
          <Card data-testid="user-detail">
            <CardHeader title="حساب" actions={<AccountBadges u={u} />} />
            <div className="p-5">
              <DataList columns={2} items={[
                ["ایمیل", <span className="ltr">{u.email}</span>],
                ["موبایل", u.mobile ? <span className="ltr">{u.mobile}</span> : null],
                [u.role === "warehouse_manager" ? "انبار" : "شهر", u.role === "warehouse_manager" ? warehouse : u.city],
                ["کد راننده", u.driver_code],
                ["عضویت از", faDateTime(u.created_at)],
                ["آخرین ورود", <span data-testid="detail-last-login">{timeAgo(u.last_login_at)}</span>],
              ]} />
            </div>
          </Card>
          <div className="grid grid-cols-2 gap-4">
            <StatCard label="ورود در ۳۰ روز" value={faNumber(stats.logins_30d)} icon={<LogIn className="size-5" />} tone="success" />
            <StatCard label="ورود ناموفق" value={faNumber(stats.failed_logins_30d)} hint="۳۰ روز اخیر" icon={<ShieldAlert className="size-5" />}
              tone={stats.failed_logins_30d ? "danger" : "muted"} />
            <StatCard label="کار روی سفارش‌ها" value={faNumber(stats.order_actions)} hint="ثبت و تغییر وضعیت" icon={<Package className="size-5" />} />
            {u.role === "driver"
              ? <StatCard label="تحویل موفق" value={faNumber(stats.deliveries)} icon={<Truck className="size-5" />} tone="info" />
              : <StatCard label="گردش انبار" value={faNumber(stats.stock_movements)} icon={<Boxes className="size-5" />} tone="orange" />}
          </div>
          <p className="text-xs leading-6 text-muted">
            {stats.history
              ? "این کاربر سابقه کاری دارد؛ اگر دیگر با سازمان کار نمی‌کند حسابش را «غیرفعال» کنید تا سوابق و گزارش‌ها کامل بمانند."
              : "این کاربر هنوز هیچ سابقه کاری ندارد و در صورت نیاز قابل حذف است."}
          </p>
        </div>
        <Card className="min-w-0 lg:col-span-2">
          <CardHeader title="فعالیت‌ها" subtitle="ورودها، کار روی سفارش‌ها، گردش انبار و تغییرات حساب — جدیدترین بالا"
            actions={<Link to={`/app/activity?actor=${u.id}`} className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"><History className="size-3.5" />گزارش کامل</Link>} />
          {activity.isLoading ? <div className="space-y-3 p-5">{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-12 rounded-xl" />)}</div>
            : !activity.data?.length ? <EmptyState icon={<History className="size-5" />} title="هنوز فعالیتی ثبت نشده" /> : (
              <ol className="relative space-y-1 p-5" data-testid="user-timeline">
                {activity.data.map((item, i) => {
                  const { icon: Icon, tone } = eventStyle(item);
                  return (
                    <li key={`${item.kind}-${i}`} className="relative flex gap-3 pb-4" data-kind={item.kind}>
                      {i < activity.data!.length - 1 && <span className="absolute top-9 right-[17px] bottom-0 w-px bg-border" aria-hidden />}
                      <span className={cn("relative grid size-9 shrink-0 place-items-center rounded-xl", tone)}><Icon className="size-4" /></span>
                      <div className="min-w-0 flex-1 pt-1">
                        <div className="text-sm font-medium text-text">
                          {item.order_id ? <button type="button" className="text-start hover:text-brand" onClick={() => setOrderId(item.order_id!)}>{item.title}</button> : item.title}
                        </div>
                        <div className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-muted">
                          <span>{faDateTime(item.at)}</span>
                          {item.detail && <span>{item.detail}</span>}
                          {item.ip && <span className="font-mono ltr">{item.ip}</span>}
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
        </Card>
      </div>
      {actions.modals}
      <OrderDetailModal orderId={orderId} onClose={() => setOrderId(null)} />
    </>
  );
}
