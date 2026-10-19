import { useState, type FormEvent } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Inbox, Megaphone } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { BUSINESS_TYPES, EMPLOYEE_RANGES, FEATURES, ORDER_VOLUMES, REFERRAL_SOURCES, REQUEST_STATUS, referralLabel } from "@/lib/labels";
import { faDate, faNumber } from "@/lib/format";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Card, DataList, EmptyState, ErrorState, Field, Input, PageHeader, SegmentedControl, Table, TableSkeleton } from "@/ui/primitives";
import { promptDialog } from "@/ui/dialogs";

type Request = Schemas["OrganizationRequestResponse"];
type Status = "pending" | "approved" | "rejected";

export default function RequestsPage() {
  const me = useMe();
  const toast = useToast();
  const queryClient = useQueryClient();
  const isAdmin = me.role === "platform_admin";
  const [status, setStatus] = useState<Status | "all">("pending");
  const [active, setActive] = useState<Request | null>(null);
  const [approve, setApprove] = useState({ slug: "", username: "", email: "", password: "" });
  const [credentials, setCredentials] = useState<Schemas["OrganizationApproved"] | null>(null);

  const { data: requests, isLoading, error, refetch } = useQuery({
    queryKey: ["platform-requests", status],
    queryFn: () => unwrap(api.GET("/platform/organization-requests", { params: { query: status === "all" ? {} : { status } } })),
    placeholderData: keepPreviousData,
  });
  // همه درخواست‌ها برای خلاصه «از کجا با ما آشنا شدند»
  const { data: allRequests } = useQuery({
    queryKey: ["platform-requests", "all"],
    queryFn: () => unwrap(api.GET("/platform/organization-requests", { params: { query: {} } })),
  });
  const invalidate = () => { queryClient.invalidateQueries({ queryKey: ["platform-requests"] }); queryClient.invalidateQueries({ queryKey: ["platform-orgs"] }); };

  const approveMutation = useMutation({
    mutationFn: () => unwrap(api.POST("/platform/organization-requests/{request_id}/approve", {
      params: { path: { request_id: active!.id } },
      body: { slug: approve.slug, admin_username: approve.username || null, admin_email: approve.email || null, admin_password: approve.password || null },
    })),
    onSuccess: result => { setActive(null); setCredentials(result); invalidate(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const rejectMutation = useMutation({
    mutationFn: (reason: string) => unwrap(api.POST("/platform/organization-requests/{request_id}/reject", { params: { path: { request_id: active!.id } }, body: { reason } })),
    onSuccess: () => { toast.success("درخواست رد شد."); setActive(null); invalidate(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const canReview = isAdmin && active?.status === "pending";

  return (
    <>
      <PageHeader eyebrow="پلتفرم" title="درخواست‌های ثبت سازمان" subtitle="درخواست‌هایی که کسب‌وکارها از صفحه «درخواست استفاده» ثبت کرده‌اند" />
      {allRequests && allRequests.length > 0 && <ReferralSummary requests={allRequests} />}
      <Card>
        <div className="border-b border-border p-4">
          <SegmentedControl value={status} onChange={setStatus} options={[
            { value: "pending", label: "در انتظار" }, { value: "approved", label: "تأییدشده" }, { value: "rejected", label: "ردشده" }, { value: "all", label: "همه" },
          ]} />
        </div>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : requests!.length === 0 ? (
          <EmptyState icon={<Inbox className="size-5" />} title="درخواستی در این وضعیت نیست" />
        ) : (
          <Table testId="requests-table">
            <thead><tr><th>کسب‌وکار</th><th>حوزه</th><th>استان / شهر</th><th>سفارش ماهانه</th><th>مسئول</th><th>آشنایی</th><th>تاریخ</th><th>وضعیت</th></tr></thead>
            <tbody>
              {requests!.map(r => (
                <tr key={r.id} className="clickable" onClick={() => { setActive(r); setApprove({ slug: "", username: "", email: "", password: "" }); }}>
                  <td><div className="font-medium">{r.name}</div><div className="font-mono text-xs text-muted ltr">{r.tracking_code}</div></td>
                  <td className="text-text-2">{BUSINESS_TYPES[r.business_type ?? ""] ?? r.business_type}</td>
                  <td>{r.province} / {r.city}</td>
                  <td>{ORDER_VOLUMES[r.monthly_order_volume ?? ""] ?? r.monthly_order_volume}</td>
                  <td>{r.contact_name}<div className="font-mono text-xs text-muted ltr">{r.contact_mobile}</div></td>
                  <td className="max-w-40 truncate text-xs text-text-2" data-testid="request-referral" title={referralLabel(r.referral_source, r.referral_detail) ?? ""}>{referralLabel(r.referral_source, r.referral_detail) ?? <span className="text-muted">—</span>}</td>
                  <td className="text-xs text-text-2">{faDate(r.created_at)}</td>
                  <td><Badge tone={REQUEST_STATUS[r.status]?.tone ?? "muted"} dot>{REQUEST_STATUS[r.status]?.label ?? r.status}</Badge></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Modal open={!!active} onClose={() => setActive(null)} size="lg" title={active?.name ?? ""} description={active && `${active.tracking_code} · ثبت: ${faDate(active.created_at)}`}
        footer={canReview ? <>
          <Button variant="outline-danger" className="me-auto" loading={rejectMutation.isPending} onClick={() => {
            promptDialog({ title: "رد درخواست", label: "دلیل رد (برای متقاضی نمایش داده می‌شود)", minLength: 3, maxLength: 1000,
              multiline: true, confirmLabel: "رد درخواست", danger: true }).then(reason => { if (reason) rejectMutation.mutate(reason); });
          }}>رد درخواست</Button>
          <Button variant="secondary" onClick={() => setActive(null)}>بستن</Button>
          <Button type="submit" form="approve-form" loading={approveMutation.isPending}>تأیید و ساخت سازمان</Button>
        </> : <Button variant="secondary" onClick={() => setActive(null)}>بستن</Button>}>
        {active && (
          <div className="space-y-5">
            <Badge tone={REQUEST_STATUS[active.status]?.tone ?? "muted"} dot>{REQUEST_STATUS[active.status]?.label}</Badge>
            <DataList columns={3} items={[
              ["نام ثبتی", active.legal_name], ["حوزه", BUSINESS_TYPES[active.business_type ?? ""]], ["شناسه ملی", active.national_id],
              ["کد اقتصادی", active.economic_code], ["استان / شهر", `${active.province ?? ""} / ${active.city ?? ""}`], ["نشانی", active.address],
              ["کارکنان", EMPLOYEE_RANGES[active.employee_count ?? ""]], ["سفارش ماهانه", ORDER_VOLUMES[active.monthly_order_volume ?? ""]],
              ["انبارها", active.warehouse_count], ["راننده/خودرو", active.fleet_size], ["مسئول", active.contact_name],
              ["همراه", active.contact_mobile], ["ایمیل", active.contact_email],
              ["آشنایی با ما", referralLabel(active.referral_source, active.referral_detail) ?? "پاسخ نداده"],
            ]} />
            <div className="flex flex-wrap items-center gap-2 text-sm"><span className="text-muted">بخش‌های مورد نیاز:</span>
              {active.requested_features?.map(f => <Badge key={f} tone="brand">{FEATURES[f] ?? f}</Badge>)}</div>
            {active.notes && <p className="rounded-xl bg-surface-2 px-4 py-3 text-sm text-text-2">{active.notes}</p>}
            {active.rejection_reason && <p className="rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger">دلیل رد: {active.rejection_reason}</p>}
            {canReview && (
              <form id="approve-form" className="grid gap-4 rounded-xl border border-border p-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); approveMutation.mutate(); }}>
                <div className="eyebrow sm:col-span-2">تأیید و ساخت سازمان</div>
                <Field label="شناسه انگلیسی (slug) *"><Input className="ltr" required pattern="[A-Za-z0-9][A-Za-z0-9-]*" value={approve.slug} onChange={e => setApprove(a => ({ ...a, slug: e.target.value }))} /></Field>
                <Field label="نام کاربری ادمین" hint="خالی = slug_admin"><Input className="ltr" value={approve.username} onChange={e => setApprove(a => ({ ...a, username: e.target.value }))} /></Field>
                <Field label="ایمیل ادمین" hint="خالی = ایمیل مسئول"><Input type="email" className="ltr" value={approve.email} onChange={e => setApprove(a => ({ ...a, email: e.target.value }))} /></Field>
                <Field label="رمز عبور ادمین" hint="خالی = رمز موقت تصادفی"><Input className="ltr" minLength={6} value={approve.password} onChange={e => setApprove(a => ({ ...a, password: e.target.value }))} /></Field>
              </form>
            )}
          </div>
        )}
      </Modal>

      <Modal open={!!credentials} onClose={() => setCredentials(null)} title="سازمان ساخته شد ✓" footer={<Button onClick={() => setCredentials(null)}>متوجه شدم</Button>}>
        {credentials && (
          <div className="space-y-3 text-sm">
            <p>سازمان «{credentials.organization.name}» با شناسه <span className="font-mono ltr">{credentials.organization.slug}</span> ساخته شد.</p>
            <p>نام کاربری ادمین: <b className="font-mono ltr">{credentials.admin_username}</b></p>
            {credentials.temporary_password ? <>
              <p>رمز موقت: <b className="font-mono ltr">{credentials.temporary_password}</b></p>
              <p className="rounded-xl bg-warning-soft px-4 py-3 text-warning">این رمز فقط همین یک‌بار نمایش داده می‌شود؛ آن را برای مسئول سازمان ارسال کنید.</p>
            </> : <p className="text-muted">رمز همان است که وارد کردید.</p>}
          </div>
        )}
      </Modal>
    </>
  );
}

/** چند درخواست از هر منبع آمده‌اند — برای سنجیدن اثر بازاریابی */
function ReferralSummary({ requests }: { requests: Request[] }) {
  const counts = new Map<string, number>();
  for (const r of requests) counts.set(r.referral_source ?? "", (counts.get(r.referral_source ?? "") ?? 0) + 1);
  const answered = requests.length - (counts.get("") ?? 0);
  const rows = Object.keys(REFERRAL_SOURCES).filter(k => counts.has(k)).sort((a, b) => counts.get(b)! - counts.get(a)!);
  const others = [...new Set(requests.filter(r => r.referral_source === "other" && r.referral_detail).map(r => r.referral_detail!))];
  return (
    <Card className="mb-5 p-5" data-testid="referral-summary">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Megaphone className="size-4 text-brand" />
        <span className="font-bold">از کجا با ما آشنا شده‌اند؟</span>
        <span className="text-xs text-muted">{faNumber(answered)} پاسخ از {faNumber(requests.length)} درخواست</span>
      </div>
      {rows.length === 0 ? <p className="text-sm text-muted">هنوز هیچ متقاضی به این سؤال پاسخ نداده است.</p> : (
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
          {rows.map(k => {
            const n = counts.get(k)!;
            return (
              <div key={k} className="rounded-xl border border-border p-3" data-testid="referral-row" data-source={k}>
                <div className="flex items-baseline justify-between gap-2 text-sm"><span>{REFERRAL_SOURCES[k]}</span><b>{faNumber(n)}</b></div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2">
                  <div className="h-full rounded-full bg-brand transition-all duration-700" style={{ width: `${Math.round((n / answered) * 100)}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      )}
      {others.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-1.5 text-xs"><span className="text-muted">«سایر»:</span>
          {others.slice(0, 12).map(o => <Badge key={o} tone="muted">{o}</Badge>)}
        </div>
      )}
    </Card>
  );
}
