/**
 * خط زمانی یکپارچه سفارش: وضعیت، انبار، ناوگان، مالی و پشتیبانی در یک فهرست مرتب، با فیلتر ناحیه.
 * سطر بالا می‌گوید سفارش الان کجاست، آخرین اقدام چه بوده و اگر چیزی جلوی کار را گرفته، چیست.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { api, unwrap } from "@/api/client";
import { faShortDateTime } from "@/lib/format";
import { ErrorState, Skeleton, cn } from "@/ui/primitives";

const AREA_DOT: Record<string, string> = {
  order: "bg-brand", warehouse: "bg-violet", fleet: "bg-info", finance: "bg-success", support: "bg-orange",
};
const AREAS = [["", "همه"], ["order", "سفارش"], ["warehouse", "انبار"], ["fleet", "ناوگان"], ["finance", "مالی"], ["support", "پشتیبانی"]] as const;

export function OrderTimeline({ orderId, version }: { orderId: number; version: string }) {
  const [area, setArea] = useState("");
  const { data, error, refetch, isLoading } = useQuery({
    queryKey: ["order-timeline", orderId, version],
    queryFn: () => unwrap(api.GET("/orders/{order_id}/timeline", { params: { path: { order_id: orderId } } })),
  });
  if (isLoading) return <Skeleton className="h-40" />;
  if (error || !data) return <ErrorState error={error} onRetry={refetch} />;
  const present = new Set(data.events.map(e => e.area));
  const events = data.events.filter(e => !area || e.area === area);

  return (
    <div data-testid="order-timeline">
      <h4 className="mb-3 text-sm font-bold">خط زمانی سفارش</h4>
      <div className="mb-4 rounded-xl border border-border bg-surface-2 px-4 py-3 text-sm" data-testid="timeline-header">
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          <span><span className="text-muted">مرحله فعلی: </span><b>{data.stage}</b></span>
          {data.last_action && <span><span className="text-muted">آخرین اقدام: </span>{data.last_action}
            {data.last_action_at && <span className="text-xs text-muted"> ({faShortDateTime(data.last_action_at)})</span>}</span>}
        </div>
        {data.blocker && (
          <p className="mt-2 flex items-center gap-1.5 font-medium text-warning" data-testid="timeline-blocker">
            <AlertTriangle className="size-4 shrink-0" />{data.blocker}
          </p>
        )}
      </div>
      <div className="mb-4 flex flex-wrap gap-1.5" role="group" aria-label="فیلتر ناحیه">
        {AREAS.filter(([k]) => !k || present.has(k)).map(([k, label]) => (
          <button key={k || "all"} type="button" onClick={() => setArea(k)} aria-pressed={area === k} data-area-chip={k || "all"}
            className={cn("rounded-full border px-3 py-1 text-xs transition", area === k ? "border-brand bg-brand text-brand-ink" : "border-border hover:border-border-strong")}>
            {label}
          </button>
        ))}
      </div>
      <ol className="relative space-y-4 border-r-2 border-border pr-5" data-testid="order-history">
        {events.map((e, i) => (
          <li key={`${e.at}-${i}`} className="relative" data-source={e.source} data-area={e.area}>
            <span className={cn("absolute top-1.5 -right-[27px] size-3 rounded-full ring-4 ring-surface", AREA_DOT[e.area])} />
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="text-sm font-semibold">{e.link ? <Link to={e.link} className="hover:text-brand hover:underline">{e.title}</Link> : e.title}</span>
              <span className="text-xs text-muted">{e.area_label} · {faShortDateTime(e.at)} — {e.actor}</span>
            </div>
            {e.outcome && <p className="mt-1 text-sm text-text-2">{e.outcome}</p>}
          </li>
        ))}
      </ol>
    </div>
  );
}
