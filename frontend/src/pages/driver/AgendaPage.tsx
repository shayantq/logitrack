/** برنامه و کارنامه راننده: هفته به هفته، با کلیک روی هر روز سفارش‌های همان روز (آینده یا گذشته) */
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { CalendarOff, ChevronLeft, ChevronRight, Clock, MapPin, Package, Weight } from "lucide-react";
import { api, unwrap } from "@/api/client";
import { OrderStatusBadge } from "@/components/StatusBadges";
import { faDate, faNumber, faShortDateTime } from "@/lib/format";
import { WEEK, isoDate, pyWeekday } from "@/lib/schedule";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton, StatCard, cn } from "@/ui/primitives";

const parse = (iso: string) => new Date(`${iso}T00:00:00`);
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
/** شنبه همان هفته */
const weekStart = (d: Date) => addDays(d, -((pyWeekday(d) - 5 + 7) % 7));

export default function AgendaPage() {
  const [params, setParams] = useSearchParams();
  const today = isoDate(new Date());
  const selected = params.get("day") ?? today;
  const start = weekStart(parse(selected));
  const select = (iso: string) => setParams({ day: iso }, { replace: true });

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["agenda", isoDate(start)],
    queryFn: () => unwrap(api.GET("/driver/agenda", { params: { query: { start: isoDate(start), days: 7 } } })),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  });
  const day = data?.days.find(d => d.date === selected);
  const isPast = selected < today;

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader eyebrow="راننده" title="برنامه و کارنامه" subtitle="روی هر روز بزنید تا سفارش‌های همان روز را ببینید — روزهای گذشته کارنامه شماست." />

      <div className="mb-4 flex items-center justify-between gap-2">
        <Button variant="ghost" size="sm" icon={<ChevronRight className="size-4" />} onClick={() => select(isoDate(addDays(start, -7)))} data-testid="week-prev">هفته قبل</Button>
        <div className="text-center text-sm">
          <div className="font-bold">{faDate(isoDate(start))} تا {faDate(isoDate(addDays(start, 6)))}</div>
          {selected !== today && <button className="text-xs text-brand" onClick={() => select(today)}>برگشت به امروز</button>}
        </div>
        <Button variant="ghost" size="sm" onClick={() => select(isoDate(addDays(start, 7)))} data-testid="week-next">هفته بعد<ChevronLeft className="size-4" /></Button>
      </div>

      {isLoading ? <Skeleton className="h-28 rounded-2xl" /> : error ? <ErrorState error={error} onRetry={refetch} /> : data && (
        <>
          <div className="mb-4 grid grid-cols-7 gap-1.5" data-testid="agenda-days">
            {data.days.map(d => {
              const active = d.date === selected;
              const w = WEEK.find(x => x.weekday === pyWeekday(parse(d.date)));
              return (
                <button key={d.date} type="button" onClick={() => select(d.date)} data-testid="agenda-day" data-day={d.date}
                  className={cn("flex flex-col items-center gap-1 rounded-2xl border px-1 py-2.5 transition",
                    active ? "border-brand bg-brand text-brand-ink shadow-[var(--shadow)]" : "border-border bg-surface hover:border-border-strong",
                    !active && d.date < today && "opacity-70")}>
                  <span className="text-[11px] font-bold sm:text-xs">{d.date === today ? "امروز" : w?.name}</span>
                  <span className={cn("text-[10px]", active ? "opacity-85" : "text-muted")}>{faDate(d.date).split("/").slice(1).join("/")}</span>
                  {d.off ? <CalendarOff className="size-3.5" />
                    : <span className={cn("grid min-w-6 place-items-center rounded-full px-1.5 text-[11px] font-bold",
                      d.orders.length ? (active ? "bg-white/25" : "bg-brand-soft text-brand-strong") : (active ? "bg-white/15" : "bg-surface-2 text-muted"))}>
                      {faNumber(d.orders.length)}</span>}
                </button>
              );
            })}
          </div>

          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="تحویل‌شده این هفته" value={faNumber(data.summary.delivered)} tone="success" />
            <StatCard label="ناموفق" value={faNumber(data.summary.failed)} tone="danger" />
            <StatCard label="در جریان" value={faNumber(data.summary.active)} tone="info" />
            <StatCard label="بار تحویل‌شده" value={`${faNumber(Math.round(data.summary.delivered_kg))} کیلو`} tone="violet" />
          </div>

          {day && (
            <Card data-testid="agenda-selected">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-5 py-4">
                <h2 className="font-bold">{WEEK.find(x => x.weekday === pyWeekday(parse(day.date)))?.name} {faDate(day.date)} {isPast && <span className="text-sm font-normal text-muted">(کارنامه)</span>}</h2>
                <div className="flex gap-1.5">
                  {day.off ? <Badge tone="warning" dot>مرخصی</Badge>
                    : day.shifts.length ? <Badge tone="brand"><Clock className="size-3" /><span className="font-mono ltr">{day.shifts.join("، ")}</span></Badge>
                    : <Badge tone="muted">بدون شیفت</Badge>}
                </div>
              </div>
              {day.off && day.off_reason && <p className="border-b border-border bg-warning-soft px-5 py-2.5 text-sm text-warning">{day.off_reason}</p>}
              {day.orders.length === 0 ? (
                <EmptyState icon={<Package className="size-5" />} title={isPast ? "در این روز سفارشی نداشتید" : "برای این روز سفارشی ندارید"} />
              ) : (
                <ul className="divide-y divide-border">
                  {day.orders.map(o => (
                    <li key={o.id} className="flex flex-wrap items-center gap-3 px-5 py-4" data-testid="agenda-order">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono font-bold ltr">{o.tracking_code}</span>
                          {o.priority && <Badge tone="danger">فوری</Badge>}
                          <OrderStatusBadge status={o.status} />
                        </div>
                        <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm text-text-2">
                          <span className="flex items-center gap-1"><Clock className="size-3.5 text-muted" />{faShortDateTime(o.delivery_window_start)} تا {faShortDateTime(o.delivery_window_end).split(" ").pop()}</span>
                          <span className="flex items-center gap-1"><MapPin className="size-3.5 text-muted" />{o.destination_city}{o.recipient_name && ` — ${o.recipient_name}`}</span>
                          <span className="flex items-center gap-1"><Weight className="size-3.5 text-muted" />{faNumber(o.total_weight_kg)} کیلو</span>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}
        </>
      )}
    </div>
  );
}
