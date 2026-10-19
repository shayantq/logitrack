/** درخواست‌های راننده: مرخصی فوری/عادی و تغییر خودرو (با مدارک) — بررسی با ادمین سازمان */
import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarOff, Car, Plus, Send, X } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { DocumentSlot } from "@/components/driver/DocumentSlot";
import { JalaliDateInput, PlateInput, PlateView, thisJalaliYear } from "@/components/driver/DriverInputs";
import { useToast } from "@/components/Toast";
import { VEHICLE_KINDS, type DocumentKind } from "@/lib/driver";
import { LEAVE_CATEGORIES, LEAVE_TYPES, REQUEST_STATUS, iranDateTime } from "@/lib/driverPortal";
import { faDate, faDateTime, faNumber, latinDigits } from "@/lib/format";
import { isoDate } from "@/lib/schedule";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, SegmentedControl, Skeleton, Textarea, cn } from "@/ui/primitives";
import { TimeField } from "@/ui/datetime";
import { confirmDialog } from "@/ui/dialogs";

type Req = Schemas["DriverRequestResponse"];

export default function DriverRequestsPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [leaveOpen, setLeaveOpen] = useState(params.get("new") === "leave");
  const [vehicleDraft, setVehicleDraft] = useState<Req | "new" | null>(params.get("new") === "vehicle" ? "new" : null);
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ["my-requests"], queryFn: () => unwrap(api.GET("/driver/requests")) });
  useEffect(() => { if (params.get("new")) setParams({}, { replace: true }); }, [params, setParams]);

  const cancel = useMutation({
    mutationFn: (id: number) => unwrap(api.POST("/driver/requests/{request_id}/cancel", { params: { path: { request_id: id } } })),
    onSuccess: () => { toast.success("درخواست لغو شد."); queryClient.invalidateQueries({ queryKey: ["my-requests"] }); queryClient.invalidateQueries({ queryKey: ["agenda"] }); },
    onError: e => toast.error(errorMessage(e)),
  });
  const now = new Date().toISOString();
  const cancellable = (r: Req) => r.status === "pending" || r.status === "draft" || (r.status === "approved" && r.kind === "leave" && (r.starts_at ?? "") + "Z" > now);

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader eyebrow="راننده" title="درخواست‌های من" subtitle="مرخصی یا تغییر خودرو را از اینجا درخواست کنید؛ نتیجه بررسی ادمین همین‌جا نمایش داده می‌شود."
        actions={<div className="flex flex-wrap gap-2">
          <Button icon={<CalendarOff className="size-4" />} onClick={() => setLeaveOpen(true)} data-testid="new-leave">درخواست مرخصی</Button>
          <Button variant="secondary" icon={<Car className="size-4" />} onClick={() => setVehicleDraft("new")} data-testid="new-vehicle-request">تغییر خودرو</Button>
        </div>} />

      {isLoading ? <Skeleton className="h-40 rounded-2xl" /> : error ? <ErrorState error={error} onRetry={refetch} /> : data!.length === 0 ? (
        <Card><EmptyState icon={<Send className="size-5" />} title="هنوز درخواستی نفرستاده‌اید" /></Card>
      ) : (
        <div className="space-y-3" data-testid="my-requests">
          {data!.map(r => {
            const s = REQUEST_STATUS[r.status];
            const urgent = r.kind === "leave" && r.leave_type === "urgent";
            return (
              <Card key={r.id} className={cn("p-4", urgent && r.status === "pending" && "border-danger/40")} data-testid="my-request" data-status={r.status}>
                <div className="flex flex-wrap items-start gap-3">
                  <span className={cn("grid size-10 shrink-0 place-items-center rounded-xl", r.kind === "leave" ? (urgent ? "bg-danger-soft text-danger" : "bg-warning-soft text-warning") : "bg-info-soft text-info")}>
                    {r.kind === "leave" ? <CalendarOff className="size-5" /> : <Car className="size-5" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-bold">{r.kind === "leave" ? LEAVE_TYPES[r.leave_type ?? "normal"].label : "تغییر خودرو"}</span>
                      {r.kind === "leave" && <span className="text-sm text-muted">— {LEAVE_CATEGORIES[r.category ?? "other"]}</span>}
                      <Badge tone={s?.tone ?? "muted"} dot>{s?.label}</Badge>
                    </div>
                    {r.kind === "leave" ? (
                      <p className="mt-1 text-sm text-text-2">{faDateTime(r.starts_at)} تا {faDateTime(r.ends_at)} · {r.reason}</p>
                    ) : (
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-text-2">
                        {r.vehicle_data?.vehicle_model as string} · {faNumber(r.vehicle_data?.max_weight_kg as number)} کیلو
                        <PlateView plate={r.vehicle_data?.license_plate as string} className="h-7 origin-right scale-90" />
                      </div>
                    )}
                    {r.review_note && <p className={cn("mt-2 rounded-lg px-3 py-1.5 text-sm", r.status === "rejected" ? "bg-danger-soft text-danger" : "bg-success-soft text-success")}>نظر ادمین: {r.review_note}</p>}
                    {r.status === "draft" && <p className="mt-2 text-sm text-warning">مدارک خودروی جدید را بارگذاری و درخواست را ارسال کنید.</p>}
                  </div>
                  <div className="flex gap-1.5">
                    {r.status === "draft" && <Button size="sm" onClick={() => setVehicleDraft(r)}>تکمیل و ارسال</Button>}
                    {cancellable(r) && <Button size="sm" variant="ghost" icon={<X className="size-4" />} loading={cancel.isPending && cancel.variables === r.id}
                      onClick={() => confirmDialog({ title: "این درخواست لغو شود؟", confirmLabel: "لغو درخواست", danger: true }).then(ok => ok && cancel.mutate(r.id))}>لغو</Button>}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {leaveOpen && <LeaveModal onClose={() => setLeaveOpen(false)} />}
      {vehicleDraft && <VehicleChangeModal draft={vehicleDraft === "new" ? null : vehicleDraft} onClose={() => setVehicleDraft(null)} />}
    </div>
  );
}

function LeaveModal({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const today = isoDate(new Date());
  const [form, setForm] = useState({ leave_type: "normal" as "normal" | "urgent", category: "", fromDate: null as string | null, fromTime: "08:00",
    toDate: null as string | null, toTime: "20:00", reason: "" });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm(f => ({ ...f, [k]: v }));
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/driver/requests/leave", { body: {
      leave_type: form.leave_type, category: form.category as Schemas["LeaveRequestCreate"]["category"], reason: form.reason,
      starts_at: iranDateTime(form.fromDate!, form.fromTime), ends_at: iranDateTime(form.toDate!, form.toTime),
    } })),
    onSuccess: () => { toast.success("درخواست مرخصی برای ادمین فرستاده شد."); queryClient.invalidateQueries({ queryKey: ["my-requests"] }); onClose(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const valid = form.category && form.fromDate && form.toDate && form.reason.trim().length >= 3;

  return (
    <Modal open onClose={onClose} title="درخواست مرخصی" testId="leave-modal"
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button>
        <Button type="submit" form="leave-form" disabled={!valid} loading={create.isPending} data-testid="leave-submit">ارسال برای ادمین</Button></>}>
      <form id="leave-form" className="space-y-5" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
        <div>
          <SegmentedControl value={form.leave_type} onChange={v => { set("leave_type", v); if (v === "urgent" && !form.fromDate) { set("fromDate", today); set("toDate", today); } }}
            options={[{ value: "normal", label: "مرخصی عادی" }, { value: "urgent", label: "مرخصی فوری" }]} />
          <p className={cn("mt-2 flex items-center gap-1.5 text-xs", form.leave_type === "urgent" ? "text-danger" : "text-muted")}>
            {form.leave_type === "urgent" && <AlertTriangle className="size-3.5" />}{LEAVE_TYPES[form.leave_type].hint}</p>
        </div>
        <div>
          <div className="mb-2 text-sm font-medium text-text-2">علت</div>
          <div className="flex flex-wrap gap-2" data-testid="leave-category">
            {Object.entries(LEAVE_CATEGORIES).map(([k, v]) => (
              <button key={k} type="button" onClick={() => set("category", k)}
                className={cn("rounded-xl border px-3.5 py-2 text-sm transition", form.category === k ? "border-brand bg-brand text-brand-ink" : "border-border hover:border-border-strong")}>{v}</button>
            ))}
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="از">
            <JalaliDateInput key={`from-${form.leave_type}`} value={form.fromDate} onChange={v => set("fromDate", v)} fromYear={thisJalaliYear()} toYear={thisJalaliYear() + 1} testId="leave-from" />
            <div className="mt-2"><TimeField value={form.fromTime} onChange={v => set("fromTime", v)} testId="leave-from-time" aria-label="ساعت شروع" /></div>
          </Field>
          <Field label="تا">
            <JalaliDateInput key={`to-${form.leave_type}`} value={form.toDate} onChange={v => set("toDate", v)} fromYear={thisJalaliYear()} toYear={thisJalaliYear() + 1} testId="leave-to" />
            <div className="mt-2"><TimeField value={form.toTime} onChange={v => set("toTime", v)} testId="leave-to-time" aria-label="ساعت پایان" /></div>
          </Field>
        </div>
        <Field label="توضیح"><Textarea rows={3} maxLength={500} value={form.reason} onChange={e => set("reason", e.target.value)} placeholder="مثلاً: مراسم خانوادگی در شهر دیگر" data-testid="leave-reason" /></Field>
        <p className="text-xs leading-6 text-muted">با تأیید ادمین، در این بازه سفارشی به شما پیشنهاد نمی‌شود و سفارش‌هایی که هنوز بارگیری نکرده‌اید به راننده دیگری سپرده می‌شوند.</p>
      </form>
    </Modal>
  );
}

function VehicleChangeModal({ draft, onClose }: { draft: Req | null; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [request, setRequest] = useState<Req | null>(draft);
  const [form, setForm] = useState({ vehicle_type: "", vehicle_model: "", vehicle_color: "", license_plate: "", max_weight_kg: "", inspection_expiry: null as string | null, note: "" });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm(f => ({ ...f, [k]: v }));
  const motorcycle = form.vehicle_type === "motorcycle";
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["my-requests"] });

  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/driver/requests/vehicle", { body: {
      vehicle_type: form.vehicle_type as Schemas["VehicleChangeCreate"]["vehicle_type"], vehicle_model: form.vehicle_model,
      vehicle_color: form.vehicle_color || null, license_plate: form.license_plate, max_weight_kg: Number(latinDigits(form.max_weight_kg)),
      inspection_expiry: motorcycle ? null : form.inspection_expiry, note: form.note || null,
    } })),
    onSuccess: r => { setRequest(r); refresh(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const submit = useMutation({
    mutationFn: () => unwrap(api.POST("/driver/requests/{request_id}/submit", { params: { path: { request_id: request!.id } } })),
    onSuccess: () => { toast.success("درخواست تغییر خودرو برای ادمین فرستاده شد."); refresh(); onClose(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const valid = form.vehicle_type && form.vehicle_model.trim().length >= 2 && form.license_plate && Number(latinDigits(form.max_weight_kg)) > 0
    && (motorcycle || form.inspection_expiry);

  return (
    <Modal open onClose={onClose} size="lg" title="درخواست تغییر خودرو" testId="vehicle-request-modal"
      description={request ? "مدارک خودروی جدید را بارگذاری و درخواست را ارسال کنید." : "مشخصات خودروی جدید را وارد کنید."}
      footer={request ? <>
        <Button variant="secondary" onClick={onClose}>بعداً</Button>
        <Button icon={<Send className="size-4" />} disabled={request.missing.length > 0} loading={submit.isPending} onClick={() => submit.mutate()} data-testid="vehicle-request-submit">ارسال برای ادمین</Button>
      </> : <>
        <Button variant="secondary" onClick={onClose}>انصراف</Button>
        <Button disabled={!valid} loading={create.isPending} onClick={() => create.mutate()} data-testid="vehicle-request-next">ادامه: مدارک</Button>
      </>}>
      {!request ? (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5" role="radiogroup" data-testid="vr-kind">
            {VEHICLE_KINDS.map(k => (
              <button key={k.value} type="button" role="radio" aria-checked={form.vehicle_type === k.value} onClick={() => set("vehicle_type", k.value)}
                className={cn("flex flex-col items-center gap-1.5 rounded-xl border-2 p-3 text-sm transition", form.vehicle_type === k.value ? "border-brand bg-brand-soft" : "border-border")}>
                <k.icon className={cn("size-6", form.vehicle_type === k.value ? "text-brand" : "text-muted")} />{k.label}
              </button>
            ))}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="مدل"><Input value={form.vehicle_model} onChange={e => set("vehicle_model", e.target.value)} data-testid="vr-model" /></Field>
            <Field label="رنگ" hint="اختیاری"><Input value={form.vehicle_color} onChange={e => set("vehicle_color", e.target.value)} /></Field>
            <Field label="پلاک" className="sm:col-span-2">
              <PlateInput key={String(motorcycle)} motorcycle={motorcycle} value={form.license_plate} onChange={v => set("license_plate", v)} />
            </Field>
            <Field label="سقف بار (کیلوگرم)" hint={form.vehicle_type ? `حداکثر ${faNumber(VEHICLE_KINDS.find(k => k.value === form.vehicle_type)!.maxKg)}` : undefined}>
              <Input type="number" min={1} value={form.max_weight_kg} onChange={e => set("max_weight_kg", e.target.value)} data-testid="vr-weight" />
            </Field>
            {!motorcycle && <Field label="اعتبار معاینه فنی تا"><JalaliDateInput value={form.inspection_expiry} onChange={v => set("inspection_expiry", v)} fromYear={thisJalaliYear()} toYear={thisJalaliYear() + 3} testId="vr-inspection" /></Field>}
            <Field label="توضیح برای ادمین" hint="اختیاری" className="sm:col-span-2"><Input value={form.note} maxLength={500} onChange={e => set("note", e.target.value)} placeholder="مثلاً: خودروی قبلی را فروختم" /></Field>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3 rounded-xl bg-surface-2 px-4 py-3 text-sm">
            <Plus className="size-4 text-brand" /><b>{request.vehicle_data?.vehicle_model as string}</b>
            <PlateView plate={request.vehicle_data?.license_plate as string} />
            <span className="text-muted">{faNumber(request.vehicle_data?.max_weight_kg as number)} کیلو</span>
            {request.vehicle_data?.inspection_expiry ? <span className="text-muted">معاینه تا {faDate(request.vehicle_data.inspection_expiry as string)}</span> : null}
          </div>
          {request.required_documents.map(kind => (
            <DocumentSlot key={kind} kind={kind as DocumentKind} required doc={request.documents.find(d => d.kind === kind)}
              fileUrl={`/driver/requests/${request.id}/documents/${kind}`} uploadUrl={`/driver/requests/${request.id}/documents/${kind}`}
              onUploaded={r => { setRequest(r as Req); toast.success("مدرک بارگذاری شد."); }} onError={toast.error} />
          ))}
        </div>
      )}
    </Modal>
  );
}
