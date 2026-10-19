/** بررسی پرونده‌های احراز هویت رانندگان + مدیریت لینک‌های دعوت (ادمین سازمان) */
import { useState, type FormEvent } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Copy, ExternalLink, Link2, Plus, Power, ShieldCheck, UserCheck, XCircle } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useDocumentUrl } from "@/components/driver/DocumentSlot";
import { PlateView } from "@/components/driver/DriverInputs";
import { useToast } from "@/components/Toast";
import { DOCUMENTS, DRIVER_STATUS, MISSING_LABELS, VEHICLE_KINDS, type DocumentKind, type DriverStatus } from "@/lib/driver";
import { faDate, faDateTime, faNumber } from "@/lib/format";
import { Modal } from "@/ui/overlays";
import { useDeepLink } from "@/hooks/useDeepLink";
import {
  Badge, Button, Card, CardHeader, DataList, EmptyState, ErrorState, Field, Input, PageHeader, SegmentedControl, StatCard, Table,
  TableSkeleton, Textarea, cn,
} from "@/ui/primitives";

type Filter = DriverStatus | "all";

export default function DriverReviewPage() {
  const [filter, setFilter] = useState<Filter>("submitted");
  const [activeId, setActiveId] = useState<number | null>(null);
  const flash = useDeepLink("driver", { onHit: setActiveId });
  const all = useQuery({ queryKey: ["driver-applications", "all"], queryFn: () => unwrap(api.GET("/drivers/applications")) });
  const list = useQuery({
    queryKey: ["driver-applications", filter],
    queryFn: () => unwrap(api.GET("/drivers/applications", { params: { query: filter === "all" ? {} : { status: filter } } })),
    placeholderData: keepPreviousData,
  });
  const count = (s: DriverStatus) => (all.data ?? []).filter(a => a.driver_status === s).length;

  return (
    <>
      <PageHeader eyebrow="تیم" title="احراز هویت رانندگان" subtitle="پرونده‌هایی که رانندگان با لینک دعوت ارسال کرده‌اند — فقط رانندگان تأییدشده سفارش می‌گیرند." />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="منتظر بررسی" value={faNumber(count("submitted"))} tone="warning" icon={<ShieldCheck className="size-[18px]" />} />
        <StatCard label="در حال تکمیل" value={faNumber(count("incomplete"))} tone="muted" />
        <StatCard label="تأییدشده (با پرونده)" value={faNumber(count("approved"))} tone="success" />
        <StatCard label="ردشده" value={faNumber(count("rejected"))} tone="danger" />
      </div>

      <Card className="mb-6">
        <div className="border-b border-border p-4">
          <SegmentedControl value={filter} onChange={setFilter} options={[
            { value: "submitted", label: "منتظر بررسی" }, { value: "incomplete", label: "در حال تکمیل" },
            { value: "rejected", label: "ردشده" }, { value: "approved", label: "تأییدشده" }, { value: "all", label: "همه" },
          ]} />
        </div>
        {list.isLoading ? <TableSkeleton /> : list.error ? <ErrorState error={list.error} onRetry={list.refetch} /> : list.data!.length === 0 ? (
          <EmptyState icon={<UserCheck className="size-5" />} title="پرونده‌ای در این وضعیت نیست" text="لینک دعوت را برای رانندگان بفرستید تا ثبت‌نام کنند." />
        ) : (
          <Table testId="drivers-table">
            <thead><tr><th>راننده</th><th>وسیله</th><th>پلاک</th><th>شهر</th><th>مدارک</th><th>ارسال</th><th>وضعیت</th></tr></thead>
            <tbody>
              {list.data!.map(a => (
                <tr key={a.user_id} className={cn("clickable", flash === a.user_id && "focus-flash")} data-focus={`driver-${a.user_id}`} onClick={() => setActiveId(a.user_id)}>
                  <td><div className="font-medium">{a.full_name ?? a.username}</div><div className="font-mono text-xs text-muted ltr">{a.mobile}</div></td>
                  <td className="text-text-2">{VEHICLE_KINDS.find(k => k.value === a.vehicle_type)?.label ?? "—"}<div className="text-xs text-muted">{a.vehicle_model}</div></td>
                  <td>{a.license_plate ? <PlateView plate={a.license_plate} className="h-7 scale-90" /> : "—"}</td>
                  <td>{a.city ?? "—"}</td>
                  <td className="tnum">{faNumber(a.documents.length)}/{faNumber(a.required_documents.length)}</td>
                  <td className="text-xs text-text-2">{a.submitted_at ? faDateTime(a.submitted_at) : "—"}</td>
                  <td><StatusBadge status={a.driver_status} /></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <InvitesCard />
      {activeId !== null && <ReviewModal driverId={activeId} onClose={() => setActiveId(null)} />}
    </>
  );
}

function StatusBadge({ status }: { status: string }) {
  const s = DRIVER_STATUS[status as DriverStatus];
  return <Badge tone={s?.tone ?? "muted"} dot>{s?.label ?? status}</Badge>;
}

function ReviewModal({ driverId, onClose }: { driverId: number; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const { data: a } = useQuery({
    queryKey: ["driver-application", driverId],
    queryFn: () => unwrap(api.GET("/drivers/applications/{driver_id}", { params: { path: { driver_id: driverId } } })),
  });
  const done = (message: string) => {
    toast.success(message);
    ["driver-applications", "driver-pending-count", "vehicles", "users"].forEach(k => queryClient.invalidateQueries({ queryKey: [k] }));
    onClose();
  };
  const approve = useMutation({
    mutationFn: () => unwrap(api.POST("/drivers/applications/{driver_id}/approve", { params: { path: { driver_id: driverId } } })),
    onSuccess: () => done("راننده تأیید شد و خودرویش به ناوگان اضافه شد."),
    onError: e => toast.error(errorMessage(e)),
  });
  const reject = useMutation({
    mutationFn: () => unwrap(api.POST("/drivers/applications/{driver_id}/reject", { params: { path: { driver_id: driverId } }, body: { reason } })),
    onSuccess: () => done("پرونده رد شد و دلیل برای راننده نمایش داده می‌شود."),
    onError: e => toast.error(errorMessage(e)),
  });
  const reviewable = a?.driver_status === "submitted";

  return (
    <Modal open onClose={onClose} size="xl" testId="review-modal"
      title={a ? <span className="flex items-center gap-3">{a.full_name ?? a.username}<StatusBadge status={a.driver_status} /></span> : "پرونده راننده"}
      description={a ? `${a.username} · ${a.driver_code ?? ""} · ثبت‌نام: ${faDate(a.created_at)}${a.invite_label ? ` · دعوت: ${a.invite_label}` : ""}` : undefined}
      footer={reviewable ? (rejecting ? <>
        <Button variant="ghost" onClick={() => setRejecting(false)}>انصراف</Button>
        <Button variant="danger" disabled={reason.trim().length < 3} loading={reject.isPending} onClick={() => reject.mutate()} data-testid="reject-confirm">ثبت رد پرونده</Button>
      </> : <>
        <Button variant="outline-danger" icon={<XCircle className="size-4" />} className="me-auto" onClick={() => setRejecting(true)} data-testid="reject-driver">رد پرونده</Button>
        <Button variant="secondary" onClick={onClose}>بستن</Button>
        <Button icon={<CheckCircle2 className="size-4" />} loading={approve.isPending} onClick={() => approve.mutate()} data-testid="approve-driver">تأیید راننده</Button>
      </>) : <Button variant="secondary" onClick={onClose}>بستن</Button>}>
      {!a ? <TableSkeleton rows={4} /> : (
        <div className="space-y-6">
          {a.rejection_reason && <p className="rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger">دلیل رد قبلی: {a.rejection_reason}</p>}
          {rejecting && (
            <Field label="دلیل رد (برای راننده نمایش داده می‌شود)">
              <Textarea autoFocus rows={3} value={reason} onChange={e => setReason(e.target.value)} placeholder="مثلاً: تصویر کارت ملی خوانا نیست." data-testid="reject-reason" />
            </Field>
          )}
          {a.missing.length > 0 && (
            <p className="rounded-xl bg-warning-soft px-4 py-3 text-sm text-warning">ناقص: {a.missing.map(k => MISSING_LABELS[k] ?? k).join("، ")}</p>
          )}
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="space-y-5">
              <SectionTitle>مشخصات فردی</SectionTitle>
              <DataList items={[
                ["نام", [a.first_name, a.last_name].filter(Boolean).join(" ")], ["کد ملی", <span className="font-mono ltr">{a.national_code}</span>],
                ["تاریخ تولد", a.birth_date ? faDate(a.birth_date) : null], ["همراه", <span className="font-mono ltr">{a.mobile}</span>],
              ]} />
              <SectionTitle>وسیله</SectionTitle>
              <DataList items={[
                ["نوع", VEHICLE_KINDS.find(k => k.value === a.vehicle_type)?.label], ["مدل / رنگ", [a.vehicle_model, a.vehicle_color].filter(Boolean).join(" — ")],
                ["پلاک", a.license_plate ? <PlateView plate={a.license_plate} /> : null], ["سقف بار", a.max_weight_kg ? `${faNumber(a.max_weight_kg)} کیلوگرم` : null],
                ["بین‌شهری", a.intercity ? "بله" : "خیر"], ["اعتبار معاینه فنی", a.inspection_expiry ? faDate(a.inspection_expiry) : null],
              ]} />
              <SectionTitle>محل سکونت</SectionTitle>
              <DataList items={[["استان / شهر", [a.province, a.city].filter(Boolean).join(" / ")], ["کد پستی", a.postal_code], ["نشانی", a.address]]} />
            </div>
            <div>
              <SectionTitle>مدارک</SectionTitle>
              <div className="grid grid-cols-2 gap-3" data-testid="review-documents">
                {a.required_documents.map(kind => (
                  <DocumentPreview key={kind} driverId={a.user_id} kind={kind as DocumentKind} doc={a.documents.find(d => d.kind === kind)} />
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

function SectionTitle({ children }: { children: string }) {
  return <h3 className="mb-3 text-sm font-bold text-text-2">{children}</h3>;
}

function DocumentPreview({ driverId, kind, doc }: { driverId: number; kind: DocumentKind; doc?: Schemas["DriverDocumentInfo"] }) {
  const url = useDocumentUrl(`/drivers/${driverId}/documents/${kind}`, doc);
  const isVideo = kind === "video";
  return (
    <figure className={cn("overflow-hidden rounded-2xl border", doc ? "border-border" : "border-dashed border-danger/40", isVideo && "col-span-2")}>
      <div className={cn("grid place-items-center bg-surface-2", isVideo ? "aspect-video" : "aspect-[4/3]")}>
        {!doc ? <span className="text-xs text-danger">بارگذاری نشده</span> : !url ? <span className="text-xs text-muted">…</span>
          : isVideo ? <video src={url} controls playsInline className="size-full bg-black object-contain" data-testid="review-video" />
          : <a href={url} target="_blank" rel="noreferrer" className="size-full"><img src={url} alt={DOCUMENTS[kind].label} className="size-full object-cover transition hover:scale-105" /></a>}
      </div>
      <figcaption className="flex items-center justify-between gap-2 px-3 py-2 text-xs">
        <span className="font-medium">{DOCUMENTS[kind].label}</span>
        {doc && url && !isVideo && <a href={url} target="_blank" rel="noreferrer" className="text-muted hover:text-brand" aria-label="اندازه کامل"><ExternalLink className="size-3.5" /></a>}
      </figcaption>
    </figure>
  );
}

function InvitesCard() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ label: "", expires_in_days: "", max_uses: "" });
  const { data: invites = [], isLoading } = useQuery({ queryKey: ["driver-invites"], queryFn: () => unwrap(api.GET("/drivers/invites")) });
  const link = (code: string) => `${location.origin}/join/${code}`;
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/drivers/invites", { body: {
      label: form.label || null, expires_in_days: form.expires_in_days ? Number(form.expires_in_days) : null,
      max_uses: form.max_uses ? Number(form.max_uses) : null,
    } })),
    onSuccess: invite => {
      queryClient.invalidateQueries({ queryKey: ["driver-invites"] });
      setOpen(false);
      setForm({ label: "", expires_in_days: "", max_uses: "" });
      navigator.clipboard?.writeText(link(invite.code)).catch(() => {});
      toast.success("لینک دعوت ساخته و کپی شد.");
    },
    onError: e => toast.error(errorMessage(e)),
  });
  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) =>
      unwrap(api.PATCH("/drivers/invites/{invite_id}", { params: { path: { invite_id: id } }, body: { is_active: active } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["driver-invites"] }),
    onError: e => toast.error(errorMessage(e)),
  });

  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><Link2 className="size-5 text-brand" />لینک‌های دعوت راننده</span>}
        subtitle="راننده با این لینک حساب می‌سازد و پرونده‌اش را تکمیل می‌کند."
        actions={<Button size="sm" icon={<Plus className="size-4" />} onClick={() => setOpen(true)} data-testid="invite-create">لینک جدید</Button>} />
      {isLoading ? <TableSkeleton rows={2} /> : invites.length === 0 ? (
        <EmptyState icon={<Link2 className="size-5" />} title="هنوز لینک دعوتی نساخته‌اید" />
      ) : (
        <Table testId="invites-table">
          <thead><tr><th>عنوان</th><th>کد</th><th>استفاده</th><th>انقضا</th><th>وضعیت</th><th /></tr></thead>
          <tbody>
            {invites.map(i => (
              <tr key={i.id}>
                <td className="font-medium">{i.label ?? "—"}</td>
                <td className="font-mono font-bold ltr">{i.code}</td>
                <td className="tnum">{faNumber(i.uses)}{i.max_uses ? ` / ${faNumber(i.max_uses)}` : ""}</td>
                <td className="text-xs text-text-2">{i.expires_at ? faDate(i.expires_at) : "بدون انقضا"}</td>
                <td>{i.is_usable ? <Badge tone="success" dot>فعال</Badge> : <Badge tone="muted" dot>{i.is_active ? "منقضی/تکمیل" : "غیرفعال"}</Badge>}</td>
                <td>
                  <div className="flex justify-end gap-1">
                    <Button size="sm" variant="ghost" icon={<Copy className="size-4" />} disabled={!i.is_usable}
                      onClick={() => navigator.clipboard?.writeText(link(i.code)).then(() => toast.success("لینک کپی شد."))}>کپی لینک</Button>
                    <Button size="sm" variant="ghost" icon={<Power className="size-4" />} onClick={() => toggle.mutate({ id: i.id, active: !i.is_active })}>
                      {i.is_active ? "غیرفعال" : "فعال"}</Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="لینک دعوت جدید"
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>انصراف</Button><Button type="submit" form="invite-form" loading={create.isPending}>ساخت و کپی لینک</Button></>}>
        <form id="invite-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
          <Field label="عنوان" hint="برای شناخت لینک — مثلاً «رانندگان قزوین»" className="sm:col-span-2"><Input value={form.label} maxLength={100} onChange={e => setForm(f => ({ ...f, label: e.target.value }))} data-testid="invite-label" /></Field>
          <Field label="اعتبار (روز)" hint="خالی = بدون انقضا"><Input type="number" min={1} max={365} value={form.expires_in_days} onChange={e => setForm(f => ({ ...f, expires_in_days: e.target.value }))} /></Field>
          <Field label="حداکثر تعداد ثبت‌نام" hint="خالی = نامحدود"><Input type="number" min={1} value={form.max_uses} onChange={e => setForm(f => ({ ...f, max_uses: e.target.value }))} /></Field>
        </form>
      </Modal>
    </Card>
  );
}

