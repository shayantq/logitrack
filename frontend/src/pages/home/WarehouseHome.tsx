/** خانه مدیر انبار: کار امروز انبار. هر کارت به صفحه همان کار می‌رود. */
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ClipboardCheck, ScanLine } from "lucide-react";
import { api, unwrap } from "@/api/client";
import { UpdatedAt } from "@/components/UpdatedAt";
import { faNumber } from "@/lib/format";
import { Badge, ErrorState, Skeleton, buttonClass } from "@/ui/primitives";

export function WarehouseHome() {
  const q = useQuery({ queryKey: ["home-warehouse"], queryFn: () => unwrap(api.GET("/home/warehouse")), refetchInterval: 30_000 });
  if (q.error) return <ErrorState error={q.error} onRetry={q.refetch} />;
  if (!q.data) return <Skeleton className="mb-6 h-44 rounded-2xl" />;
  return (
    <section className="mb-6" data-testid="warehouse-home" aria-label="کار امروز انبار">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-base font-bold"><ClipboardCheck className="size-5 text-brand" />کار امروز انبار</h2>
        <div className="flex flex-wrap items-center gap-3">
          <UpdatedAt at={`${q.data.generated_at}Z`} />
          <Link to="/app/my-tasks" className={buttonClass("primary")} data-testid="open-my-tasks"><ScanLine className="size-4" />صف کار من</Link>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        {q.data.items.map(item => (
          <Link key={item.key} to={item.link} data-testid={`wh-today-${item.key}`} className="card flex min-h-24 flex-col justify-between gap-2 p-4 transition hover:border-brand">
            <span className="text-sm font-medium">{item.label}</span>
            <span className="flex items-center justify-between">
              <Badge tone={item.count ? "warning" : "muted"} className="text-base"><span data-testid="wh-today-count">{faNumber(item.count)}</span></Badge>
              <ArrowLeft className="size-4 text-muted" aria-hidden />
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}
