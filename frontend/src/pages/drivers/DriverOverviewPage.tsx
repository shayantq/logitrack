/** پروفایل کامل راننده برای ادمین/مدیر انبار: مدارک، تعداد بار، رضایت مشتری، پورسانت، سطح، خودروها و سفارش‌ها */
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CalendarClock, Car, FileText, MessageSquareQuote, Package, UserRound } from "lucide-react";
import { api, unwrap, type Schemas } from "@/api/client";
import { DocumentSlot, useDocumentUrl } from "@/components/driver/DocumentSlot";
import { PlateView } from "@/components/driver/DriverInputs";
import { LevelProgressCard, RatingTags, Rial, SOURCE_LABELS, Stars } from "@/components/performance/PerformanceUI";
import { OrderStatusBadge, VehicleStatusBadge } from "@/components/StatusBadges";
import { DRIVER_STATUS, type DocumentKind, type DriverStatus } from "@/lib/driver";
import { VEHICLE_TYPES } from "@/lib/labels";
import { faDate, faNumber, faShortDateTime } from "@/lib/format";
import { WEEKDAY_NAME } from "@/lib/schedule";
import { Badge, Card, CardHeader, DataList, EmptyState, ErrorState, Skeleton, StatCard, Table, buttonClass, cn } from "@/ui/primitives";


export default function DriverOverviewPage() {
  const { id = "" } = useParams();
  const { data: d, error, refetch } = useQuery({
    queryKey: ["driver-overview", id],
    queryFn: () => unwrap(api.GET("/drivers/{driver_id}/overview", { params: { path: { driver_id: Number(id) } } })),
  });
  const p = d?.profile as Record<string, unknown> | undefined;
  const docs = (p?.documents ?? []) as Schemas["DriverDocumentInfo"][];
  const avatar = useDocumentUrl(`/drivers/${id}/documents/selfie`, docs.find(x => x.kind === "selfie"));

  if (error) return <ErrorState error={error} onRetry={refetch} />;
  if (!d || !p) return <div className="space-y-4"><Skeleton className="h-36 rounded-2xl" /><Skeleton className="h-96 rounded-2xl" /></div>;
  const status = DRIVER_STATUS[p.driver_status as DriverStatus];
  const bySource = d.progress.ratings_by_source as Record<string, { average: number; count: number }>;

  return (
    <div data-testid="driver-overview">
      <Link to="/app/drivers/top" className={buttonClass("ghost", "sm", "mb-3")}><ArrowRight className="size-4" />برترین رانندگان</Link>

      <Card className="mb-6 overflow-hidden">
        <div className="flex flex-wrap items-center gap-5 bg-linear-to-l from-brand-soft to-transparent p-6">
          <div className="grid size-20 place-items-center overflow-hidden rounded-2xl bg-surface-2 ring-4 ring-surface">
            {avatar ? <img src={avatar} alt="" className="size-full object-cover" /> : <UserRound className="size-9 text-muted" />}
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-black">{(p.full_name as string) ?? (p.username as string)}</h1>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-text-2">
              {([p.driver_code, p.mobile, p.city] as (string | null | undefined)[]).filter(Boolean).map((part, i) => (
                <span key={i} className="flex items-center gap-2">{i > 0 && <span>·</span>}<span className={i < 2 ? "font-mono ltr" : ""}>{part}</span></span>
              ))}
              <Badge tone={status?.tone ?? "muted"} dot>{status?.label}</Badge>
            </div>
          </div>
          <div className="text-center">
            <Stars value={d.progress.rating} size="lg" />
            <div className="mt-1 text-xs text-muted">{faNumber(Object.values(bySource).reduce((s, x) => s + x.count, 0))} امتیاز</div>
          </div>
        </div>
      </Card>

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="تعداد بار تحویل‌شده" value={faNumber(d.all_time.deliveries)} icon={<Package className="size-[18px]" />} hint={`این ماه: ${faNumber(d.month.deliveries)}`} />
        <StatCard label="نرخ موفقیت" value={d.all_time.success_rate != null ? `${faNumber(d.all_time.success_rate)}٪` : "—"} tone="success" hint={`${faNumber(d.all_time.failed)} ناموفق`} />
        <StatCard label="پورسانت گرفته‌شده" value={<Rial value={d.all_time.commission} />} tone="pink" hint={<>این ماه: <Rial value={d.month.commission} /></>} />
        <StatCard label="درآمد راننده" value={<Rial value={d.all_time.earnings} />} tone="violet" hint={<>این ماه: <Rial value={d.month.earnings} /></>} />
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div className="space-y-6">
          <Card><CardHeader title="سطح و پورسانت" /><div className="p-5"><LevelProgressCard p={d.progress} /></div></Card>

          <Card>
            <CardHeader title="رضایت" subtitle="میانگین وزنی: سازمان ۵۰٪، مشتری ۳۵٪، پلتفرم ۱۵٪" />
            <div className="grid grid-cols-3 gap-2 p-5 text-center" data-testid="ratings-by-source">
              {["organization", "customer", "platform"].map(s => (
                <div key={s} className="rounded-xl bg-surface-2 p-3">
                  <div className="text-xs text-muted">{SOURCE_LABELS[s]}</div>
                  <div className="mt-1 text-xl font-black tnum">{bySource[s] ? faNumber(bySource[s].average) : "—"}</div>
                  <div className="text-[11px] text-muted">{faNumber(bySource[s]?.count ?? 0)} نظر</div>
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader title={<span className="flex items-center gap-2"><Car className="size-4 text-brand" />خودروها</span>} />
            <ul className="divide-y divide-border">
              {d.vehicles.length === 0 && <li className="px-5 py-4 text-sm text-muted">خودرویی ندارد.</li>}
              {d.vehicles.map((v, i) => (
                <li key={v.id as number} className={cn("flex flex-wrap items-center gap-3 px-5 py-3", i > 0 && "opacity-70")}>
                  <span className="font-medium">{v.model as string}</span><span className="text-xs text-muted">{VEHICLE_TYPES[v.type as string]} · {faNumber(v.capacity_kg as number)} کیلو</span>
                  <PlateView plate={v.license_plate as string} className="h-7 origin-right scale-90" />
                  <span className="ms-auto">{i === 0 ? <VehicleStatusBadge status={v.status as string} /> : <Badge tone="muted">خودروی قبلی</Badge>}</span>
                </li>
              ))}
            </ul>
          </Card>

          <Card>
            <CardHeader title={<span className="flex items-center gap-2"><CalendarClock className="size-4 text-brand" />شیفت‌ها</span>} />
            <div className="flex flex-wrap gap-2 p-5 text-sm">
              {d.shifts.length === 0 ? <span className="text-muted">برنامه کاری ثبت نشده (همیشه در دسترس)</span> : d.shifts.map((s, i) => (
                <span key={i} className="rounded-lg bg-surface-2 px-2.5 py-1">{WEEKDAY_NAME[s.weekday as number]} <span className="font-mono ltr">{s.start_time as string}–{s.end_time as string}</span></span>
              ))}
            </div>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader title={<span className="flex items-center gap-2"><MessageSquareQuote className="size-4 text-brand" />نظرها و امتیازها</span>} />
            {d.recent_ratings.length === 0 ? <EmptyState title="هنوز امتیازی ثبت نشده" /> : (
              <ul className="max-h-96 divide-y divide-border overflow-y-auto" data-testid="overview-ratings">
                {d.recent_ratings.map(r => (
                  <li key={r.id} className="px-5 py-3">
                    <div className="flex flex-wrap items-center gap-2"><Stars value={r.score} /><Badge tone={r.source === "customer" ? "info" : r.source === "platform" ? "violet" : "brand"}>{SOURCE_LABELS[r.source]}</Badge>
                      {r.tracking_code && <span className="font-mono text-xs text-muted ltr">{r.tracking_code}</span>}
                      <span className="ms-auto text-xs text-muted">{faDate(r.created_at)}</span></div>
                    <div className="mt-1"><RatingTags tags={r.tags} /></div>
                    {r.comment && <p className="mt-1 text-sm text-text-2">{r.comment}</p>}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader title="آخرین سفارش‌ها و تسویه" subtitle="پورسانت هر سفارش در لحظه تحویل محاسبه و ثبت شده است." />
            {d.recent_orders.length === 0 ? <EmptyState title="سفارشی ندارد" /> : (
              <Table testId="overview-orders">
                <thead><tr><th>کد</th><th>وضعیت</th><th>کرایه</th><th>سطح / سفر روز</th><th>پورسانت</th><th>سهم راننده</th></tr></thead>
                <tbody>
                  {d.recent_orders.map(o => (
                    <tr key={o.id as number}>
                      <td><span className="font-mono text-xs font-bold ltr">{o.tracking_code as string}</span><div className="text-[11px] text-muted">{faShortDateTime((o.delivered_at ?? o.delivery_window_start) as string)}</div></td>
                      <td><OrderStatusBadge status={o.status as string} /></td>
                      <td><Rial value={o.delivery_fee as number} /></td>
                      <td className="text-xs">{o.commission_level ? <>{o.commission_level as string} · سفر {faNumber(o.day_trip_number as number)}</> : "—"}</td>
                      <td>{o.commission_amount != null ? <><Rial value={o.commission_amount as number} /><div className="text-[11px] text-muted tnum">{faNumber(o.commission_percent as number)}٪</div></> : "—"}</td>
                      <td>{o.driver_earning != null ? <Rial value={o.driver_earning as number} /> : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>

          <Card>
            <CardHeader title={<span className="flex items-center gap-2"><FileText className="size-4 text-brand" />مدارک</span>} />
            <div className="grid gap-3 p-5 sm:grid-cols-2">
              {docs.length === 0 && <p className="text-sm text-muted">مدرکی ثبت نشده (راننده توسط ادمین ساخته شده است).</p>}
              {docs.map(doc => <DocumentSlot key={doc.kind} kind={doc.kind as DocumentKind} doc={doc} required={false} disabled
                fileUrl={`/drivers/${id}/documents/${doc.kind}`} uploadUrl="" onUploaded={() => {}} onError={() => {}} />)}
            </div>
            <div className="border-t border-border px-5 py-3">
              <DataList columns={3} items={[["کد ملی", p.national_code as string], ["تاریخ تولد", p.birth_date ? faDate(p.birth_date as string) : null], ["بین‌شهری", p.intercity ? "بله" : "خیر"]]} />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

