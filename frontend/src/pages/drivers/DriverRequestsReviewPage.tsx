/** بررسی درخواست‌های رانندگان (مرخصی فوری/عادی و تغییر خودرو) توسط ادمین سازمان */
import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, CalendarOff, Car, CheckCircle2, Inbox, XCircle } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useDocumentUrl } from "@/components/driver/DocumentSlot";
import { PlateView } from "@/components/driver/DriverInputs";
import { OrderStatusBadge } from "@/components/StatusBadges";
import { useToast } from "@/components/Toast";
import { DOCUMENTS, type DocumentKind } from "@/lib/driver";
import { LEAVE_CATEGORIES, LEAVE_TYPES, REQUEST_STATUS } from "@/lib/driverPortal";
import { VEHICLE_TYPES } from "@/lib/labels";
import { faDate, faDateTime, faNumber, faShortDateTime } from "@/lib/format";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, SegmentedControl, Skeleton, Textarea, cn } from "@/ui/primitives";
import { useDeepLink } from "@/hooks/useDeepLink";

type Req = Schemas["DriverRequestResponse"];
type Status = "pending" | "approved" | "rejected" | "all";
type Kind = "leave" | "vehicle_change" | "all";

export default function DriverRequestsReviewPage() {
  const [status, setStatus] = useState<Status>("pending");
  const [kind, setKind] = useState<Kind>("all");
  // از اعلان: همه وضعیت‌ها نمایش داده می‌شوند تا درخواست (حتی اگر ادمین دیگری بررسی کرده باشد) دیده شود
  const flash = useDeepLink("request", { onHit: () => { setStatus("all"); setKind("all"); } });
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["driver-requests", status, kind],
    queryFn: () => unwrap(api.GET("/driver-requests", { params: { query: {
      ...(status === "all" ? {} : { status }), ...(kind === "all" ? {} : { kind }) } } })),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });

  return (
    <>
      <PageHeader eyebrow="تیم" title="درخواست‌های رانندگان" subtitle="مرخصی‌های فوری بالای فهرست می‌آیند. با تأیید مرخصی، سفارش‌های بارگیری‌نشده آن راننده آزاد می‌شوند." />
      <div className="mb-5 flex flex-wrap gap-3">
        <SegmentedControl value={status} onChange={setStatus} options={[
          { value: "pending", label: "منتظر بررسی" }, { value: "approved", label: "تأییدشده" }, { value: "rejected", label: "ردشده" }, { value: "all", label: "همه" }]} />
        <SegmentedControl value={kind} onChange={setKind} options={[
          { value: "all", label: "همه انواع" }, { value: "leave", label: "مرخصی" }, { value: "vehicle_change", label: "تغییر خودرو" }]} />
      </div>
      {isLoading ? <Skeleton className="h-48 rounded-2xl" /> : error ? <ErrorState error={error} onRetry={refetch} /> : data!.length === 0 ? (
        <Card><EmptyState icon={<Inbox className="size-5" />} title="درخواستی در این وضعیت نیست" /></Card>
      ) : (
        <div className="space-y-4" data-testid="driver-requests">
          {data!.map(r => <RequestCard key={r.id} r={r} flash={flash === r.id} />)}
        </div>
      )}
    </>
  );
}

function RequestCard({ r, flash }: { r: Req; flash?: boolean }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");
  const done = (msg: string) => {
    toast.success(msg);
    for (const k of ["driver-requests", "driver-requests-count", "schedules", "orders", "vehicles"]) queryClient.invalidateQueries({ queryKey: [k] });
  };
  const approve = useMutation({
    mutationFn: () => unwrap(api.POST("/driver-requests/{request_id}/approve", { params: { path: { request_id: r.id } }, body: { note: note || null } })),
    onSuccess: () => done(r.kind === "leave" ? "مرخصی تأیید و در برنامه راننده ثبت شد." : "تغییر خودرو تأیید شد و خودروی جدید به ناوگان اضافه شد."),
    onError: e => toast.error(errorMessage(e)),
  });
  const reject = useMutation({
    mutationFn: () => unwrap(api.POST("/driver-requests/{request_id}/reject", { params: { path: { request_id: r.id } }, body: { note } })),
    onSuccess: () => done("درخواست رد شد."),
    onError: e => toast.error(errorMessage(e)),
  });
  const urgent = r.kind === "leave" && r.leave_type === "urgent";
  const s = REQUEST_STATUS[r.status];
  const assigned = r.affected_orders.filter(o => o.status === "assigned").length;
  const inProgress = r.affected_orders.length - assigned;

  return (
    <Card className={cn("overflow-hidden", urgent && r.status === "pending" && "border-danger/50", flash && "focus-flash")} data-testid="driver-request" data-kind={r.kind}
      data-focus={`request-${r.id}`}>
      <div className={cn("flex flex-wrap items-center gap-3 border-b border-border px-5 py-3.5", urgent && r.status === "pending" && "bg-danger-soft/50")}>
        <span className={cn("grid size-9 place-items-center rounded-xl", r.kind === "leave" ? (urgent ? "bg-danger text-white" : "bg-warning-soft text-warning") : "bg-info-soft text-info")}>
          {r.kind === "leave" ? <CalendarOff className="size-[18px]" /> : <Car className="size-[18px]" />}
        </span>
        <div>
          <div className="font-bold">{r.driver_name} <span className="font-mono text-xs font-normal text-muted">{r.driver_code}</span></div>
          <div className="text-xs text-muted">{r.kind === "leave" ? LEAVE_TYPES[r.leave_type ?? "normal"].label : "تغییر خودرو"} · ارسال: {faDateTime(r.submitted_at)}</div>
        </div>
        {urgent && <Badge tone="danger"><AlertTriangle className="size-3" />فوری</Badge>}
        <Badge tone={s?.tone ?? "muted"} dot className="ms-auto">{s?.label}</Badge>
      </div>

      <div className="space-y-4 p-5">
        {r.kind === "leave" ? (
          <>
            <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
              <span><span className="text-muted">علت: </span><b>{LEAVE_CATEGORIES[r.category ?? "other"]}</b></span>
              <span><span className="text-muted">از </span><b>{faDateTime(r.starts_at)}</b><span className="text-muted"> تا </span><b>{faDateTime(r.ends_at)}</b></span>
            </div>
            <p className="rounded-xl bg-surface-2 px-4 py-2.5 text-sm text-text-2">{r.reason}</p>
            {r.status === "pending" && r.affected_orders.length > 0 && (
              <div className="rounded-xl border border-warning/40 bg-warning-soft/60 p-3 text-sm" data-testid="affected-orders">
                <div className="mb-2 font-semibold text-warning">
                  {faNumber(r.affected_orders.length)} سفارش این راننده در این بازه است
                  {assigned > 0 && ` — با تأیید، ${faNumber(assigned)} سفارش بارگیری‌نشده به «در انتظار تخصیص» برمی‌گردد`}
                  {inProgress > 0 && ` و ${faNumber(inProgress)} سفارشِ در جریان دست نمی‌خورد`}.
                </div>
                <ul className="flex flex-wrap gap-2">
                  {r.affected_orders.map(o => (
                    <li key={o.id} className="flex items-center gap-2 rounded-lg bg-surface px-2.5 py-1">
                      <span className="font-mono text-xs font-bold ltr">{o.tracking_code}</span><OrderStatusBadge status={o.status} />
                      <span className="text-xs text-muted">{o.destination_city} · {faShortDateTime(o.delivery_window_start)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : <VehicleChange r={r} />}

        {r.review_note && <p className={cn("rounded-xl px-4 py-2.5 text-sm", r.status === "rejected" ? "bg-danger-soft text-danger" : "bg-success-soft text-success")}>نظر ادمین: {r.review_note}</p>}

        {r.status === "pending" && (
          <div className="space-y-3 border-t border-border pt-4">
            <Textarea rows={2} value={note} onChange={e => setNote(e.target.value)} data-testid="review-note"
              placeholder={rejecting ? "دلیل رد (برای راننده نمایش داده می‌شود)" : "یادداشت برای راننده (اختیاری)"} />
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="outline-danger" icon={<XCircle className="size-4" />} loading={reject.isPending}
                onClick={() => { if (note.trim().length < 3) { setRejecting(true); toast.error("دلیل رد را در کادر بالا بنویسید."); return; } reject.mutate(); }}
                data-testid="request-reject">رد</Button>
              <Button icon={<CheckCircle2 className="size-4" />} loading={approve.isPending} onClick={() => approve.mutate()} data-testid="request-approve">تأیید</Button>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

function VehicleChange({ r }: { r: Req }) {
  const v = r.vehicle_data ?? {};
  const cur = r.current_vehicle;
  return (
    <div className="space-y-4">
      <div className="grid items-center gap-3 sm:grid-cols-[1fr_auto_1fr]">
        <div className="rounded-xl border border-border p-3 text-sm opacity-75">
          <div className="mb-1 text-xs text-muted">{r.status === "approved" ? "خودروی قبلی" : "خودروی فعلی"}</div>
          {cur ? <><div className="font-semibold">{cur.model as string} · {VEHICLE_TYPES[cur.type as string]}</div>
            <div className="mt-1 flex items-center gap-2"><PlateView plate={cur.license_plate as string} className="h-7 origin-right scale-90" /><span className="text-muted">{faNumber(cur.capacity_kg as number)} کیلو</span></div></>
            : <span className="text-muted">ندارد</span>}
        </div>
        <ArrowLeft className="mx-auto size-5 text-brand" />
        <div className="rounded-xl border-2 border-brand/50 bg-brand-soft/40 p-3 text-sm" data-testid="new-vehicle">
          <div className="mb-1 text-xs text-muted">خودروی جدید</div>
          <div className="font-semibold">{v.vehicle_model as string} · {VEHICLE_TYPES[v.vehicle_type as string]}{v.vehicle_color ? ` · ${v.vehicle_color}` : ""}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2"><PlateView plate={v.license_plate as string} className="h-7 origin-right scale-90" />
            <span className="text-muted">{faNumber(v.max_weight_kg as number)} کیلو</span>
            {v.inspection_expiry ? <span className="text-muted">· معاینه تا {faDate(v.inspection_expiry as string)}</span> : null}</div>
        </div>
      </div>
      {r.reason && <p className="rounded-xl bg-surface-2 px-4 py-2.5 text-sm text-text-2">{r.reason}</p>}
      <div className="grid max-w-xl grid-cols-3 gap-3">
        {r.required_documents.map(kind => <RequestDoc key={kind} requestId={r.id} kind={kind as DocumentKind} doc={r.documents.find(d => d.kind === kind)} />)}
      </div>
    </div>
  );
}

function RequestDoc({ requestId, kind, doc }: { requestId: number; kind: DocumentKind; doc?: Schemas["RequestDocument"] }) {
  const url = useDocumentUrl(`/driver-requests/${requestId}/documents/${kind}`, doc);
  return (
    <figure className="overflow-hidden rounded-xl border border-border">
      <div className="grid aspect-[4/3] place-items-center bg-surface-2">
        {url ? <a href={url} target="_blank" rel="noreferrer" className="size-full"><img src={url} alt={DOCUMENTS[kind].label} className="size-full object-cover" /></a>
          : <span className="text-xs text-muted">{doc ? "…" : "ندارد"}</span>}
      </div>
      <figcaption className="px-3 py-1.5 text-xs font-medium">{DOCUMENTS[kind].label}</figcaption>
    </figure>
  );
}
