import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, History, Search } from "lucide-react";
import { api, unwrap } from "@/api/client";
import { useUsers } from "@/hooks/data";
import { faDateTime, faNumber } from "@/lib/format";
import { DateField } from "@/ui/datetime";
import { Badge, Button, Card, EmptyState, ErrorState, Input, PageHeader, Select, Table, TableSkeleton, type Tone } from "@/ui/primitives";
import { deviceLabel } from "./shared";

const PAGE = 50;
const CATEGORY_TONE: Record<string, Tone> = { auth: "info", users: "violet", settings: "pink", catalog: "orange", reports: "brand", drivers: "success" };
const DANGER = new Set(["auth.login_failed", "auth.locked", "user.deactivate", "user.delete"]);

export default function ActivityPage() {
  const [params, setParams] = useSearchParams();
  const { data: users = [] } = useUsers();
  const [q, setQ] = useState(params.get("q") ?? "");
  const page = Number(params.get("page") ?? 0);
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next, { replace: true });
  };
  // جستجوی متنی با کمی مکث
  useEffect(() => {
    const t = setTimeout(() => { if ((params.get("q") ?? "") !== q.trim()) setFilter("q", q.trim()); }, 350);
    return () => clearTimeout(t);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  const filters = {
    actor_id: params.get("actor") ? Number(params.get("actor")) : undefined,
    category: params.get("category") || undefined,
    q: params.get("q") || undefined,
    date_from: params.get("from") || undefined,
    date_to: params.get("to") || undefined,
  };
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["activity-log", filters, page],
    queryFn: () => unwrap(api.GET("/users/activity-log", { params: { query: { ...filters, limit: PAGE, offset: page * PAGE } } })),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
  const categories = data?.categories ?? {};
  const from = page * PAGE + 1, to = Math.min((page + 1) * PAGE, data?.total ?? 0);

  return (
    <>
      <PageHeader eyebrow="تنظیمات" title="گزارش فعالیت"
        subtitle="چه کسی، چه زمانی، از کجا چه کاری کرد — ورودها و تلاش‌های ناموفق، مدیریت کاربران، تنظیمات سازمان، کاتالوگ و گزارش‌گیری." />
      <Card>
        <div className="grid gap-3 border-b border-border p-4 md:grid-cols-2 xl:grid-cols-5">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" />
            <Input className="pr-9" placeholder="جستجو در شرح، نام یا IP" value={q} onChange={e => setQ(e.target.value)} aria-label="جستجو" data-testid="activity-search" />
          </div>
          <Select value={params.get("actor") ?? ""} onChange={e => setFilter("actor", e.target.value)} aria-label="کاربر" data-testid="activity-actor">
            <option value="">همه کاربران</option>
            {users.map(u => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
          </Select>
          <Select value={params.get("category") ?? ""} onChange={e => setFilter("category", e.target.value)} aria-label="دسته" data-testid="activity-category">
            <option value="">همه دسته‌ها</option>
            {Object.entries(categories).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
          <DateField aria-label="از تاریخ" placeholder="از تاریخ" value={params.get("from") ?? ""} onChange={v => setFilter("from", v)} />
          <DateField aria-label="تا تاریخ" placeholder="تا تاریخ" value={params.get("to") ?? ""} onChange={v => setFilter("to", v)} />
        </div>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data?.items.length ? (
          <EmptyState icon={<History className="size-5" />} title="رویدادی با این فیلترها نیست" />
        ) : (
          <>
            <Table testId="activity-table">
              <thead><tr><th>زمان</th><th>انجام‌دهنده</th><th>رویداد</th><th>دسته</th><th>IP / دستگاه</th></tr></thead>
              <tbody className={isFetching ? "opacity-70 transition-opacity" : "transition-opacity"}>
                {data.items.map(item => (
                  <tr key={item.id} data-testid="activity-row" data-action={item.action}>
                    <td className="whitespace-nowrap text-xs text-text-2">{faDateTime(item.at)}</td>
                    <td className="whitespace-nowrap">
                      {item.actor_id ? <Link to={`/app/users/${item.actor_id}`} className="font-medium hover:text-brand">{item.actor_name}</Link>
                        : <span className="text-muted">{item.actor_name ?? "ناشناس"}</span>}
                    </td>
                    <td className={DANGER.has(item.action) ? "text-danger" : undefined}>
                      {item.summary}
                      {item.target_type === "user" && item.target_id && item.target_id !== item.actor_id && (
                        <Link to={`/app/users/${item.target_id}`} className="ms-2 text-xs text-brand hover:underline">مشاهده کاربر</Link>
                      )}
                    </td>
                    <td><Badge tone={CATEGORY_TONE[item.category] ?? "muted"}>{categories[item.category] ?? item.category}</Badge></td>
                    <td className="whitespace-nowrap text-xs text-muted"><span className="font-mono ltr">{item.ip ?? "—"}</span><div>{deviceLabel(item.user_agent)}</div></td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border p-4 text-sm text-muted">
              <span data-testid="activity-total">{faNumber(from)} تا {faNumber(to)} از {faNumber(data.total)} رویداد</span>
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" icon={<ChevronRight className="size-4" />} disabled={page === 0} onClick={() => setFilter("page", String(page - 1))}>جدیدتر</Button>
                <Button variant="secondary" size="sm" disabled={to >= data.total} onClick={() => setFilter("page", String(page + 1))}>قدیمی‌تر<ChevronLeft className="size-4" /></Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
