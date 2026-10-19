/** برترین رانندگان — رتبه‌بندی بر اساس تحویل، امتیاز، درآمد یا نرخ موفقیت (این ماه / همه زمان‌ها) */
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Crown, Medal, Trophy } from "lucide-react";
import { api, unwrap } from "@/api/client";
import { LevelBadge, Rial, Stars } from "@/components/performance/PerformanceUI";
import { faNumber } from "@/lib/format";
import { Card, EmptyState, ErrorState, PageHeader, SegmentedControl, Table, TableSkeleton, cn } from "@/ui/primitives";

type Sort = "deliveries" | "rating" | "earnings" | "success";
const LEVEL_INDEX: Record<string, number> = { D: 0, C: 1, B: 2, A: 3 };

export default function TopDriversPage() {
  const navigate = useNavigate();
  const [period, setPeriod] = useState<"month" | "all">("month");
  const [sort, setSort] = useState<Sort>("deliveries");
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["leaderboard", period, sort],
    queryFn: () => unwrap(api.GET("/drivers/leaderboard", { params: { query: { period, sort } } })),
    placeholderData: keepPreviousData,
  });
  const rows = data ?? [];
  const podium = rows.slice(0, 3);

  return (
    <>
      <PageHeader eyebrow="تیم" title="برترین رانندگان" subtitle="روی هر راننده بزنید تا پروفایل کامل، امتیازها و پورسانتش را ببینید." />
      <div className="mb-6 flex flex-wrap gap-3">
        <SegmentedControl value={period} onChange={setPeriod} options={[{ value: "month", label: "این ماه" }, { value: "all", label: "همه زمان‌ها" }]} />
        <SegmentedControl value={sort} onChange={setSort} options={[
          { value: "deliveries", label: "بیشترین تحویل" }, { value: "rating", label: "بهترین امتیاز" },
          { value: "earnings", label: "بیشترین درآمد" }, { value: "success", label: "نرخ موفقیت" }]} />
      </div>

      {podium.length > 0 && (
        <div className="mb-6 grid gap-4 sm:grid-cols-3" data-testid="podium">
          {podium.map((r, i) => {
            const Icon = [Crown, Trophy, Medal][i];
            return (
              <Link key={r.driver_id} to={`/app/drivers/${r.driver_id}`}
                className={cn("card relative overflow-hidden p-5 transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-lg)]", i === 0 && "sm:-translate-y-2 ring-2 ring-accent/50")}>
                <Icon className={cn("absolute left-4 top-4 size-7", ["text-accent", "text-slate-400", "text-amber-700"][i])} />
                <div className="text-xs font-bold text-muted">رتبه {faNumber(i + 1)}</div>
                <div className="mt-2 flex items-center gap-3">
                  <LevelBadge code={r.level_code} index={LEVEL_INDEX[r.level_code] ?? 0} />
                  <div><div className="font-bold">{r.driver_name}</div><div className="text-xs text-muted">{r.city} · سطح {r.level_name}</div></div>
                </div>
                <div className="mt-4 grid grid-cols-3 gap-2 text-center text-xs">
                  <div><div className="text-lg font-black tnum">{faNumber(r.deliveries)}</div><div className="text-muted">تحویل</div></div>
                  <div><div className="text-lg font-black tnum">{r.rating != null ? faNumber(r.rating) : "—"}</div><div className="text-muted">امتیاز</div></div>
                  <div><div className="text-lg font-black tnum">{r.success_rate != null ? `${faNumber(r.success_rate)}٪` : "—"}</div><div className="text-muted">موفقیت</div></div>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      <Card>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : rows.length === 0 ? (
          <EmptyState icon={<Trophy className="size-5" />} title="هنوز راننده تأییدشده‌ای ندارید" />
        ) : (
          <Table testId="leaderboard-table">
            <thead><tr><th>#</th><th>راننده</th><th>سطح</th><th>تحویل</th><th>ناموفق</th><th>موفقیت</th><th>امتیاز</th><th>درآمد راننده</th><th>پورسانت سازمان</th></tr></thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.driver_id} className="clickable" onClick={() => navigate(`/app/drivers/${r.driver_id}`)}>
                  <td className="font-black tnum">{faNumber(r.rank)}</td>
                  <td><Link to={`/app/drivers/${r.driver_id}`} className="font-medium hover:text-brand" onClick={e => e.stopPropagation()}>{r.driver_name}</Link>
                    <div className="font-mono text-xs text-muted">{r.driver_code}</div></td>
                  <td><LevelBadge code={r.level_code} name={r.level_name} index={LEVEL_INDEX[r.level_code] ?? 0} size="sm" /></td>
                  <td className="font-bold tnum">{faNumber(r.deliveries)}</td>
                  <td className="tnum text-text-2">{faNumber(r.failed)}</td>
                  <td className="tnum">{r.success_rate != null ? `${faNumber(r.success_rate)}٪` : "—"}</td>
                  <td><Stars value={r.rating} count={r.ratings_count} /></td>
                  <td><Rial value={r.earnings} /></td>
                  <td><Rial value={r.commission} className="text-text-2" /></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}
