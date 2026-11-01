/**
 * مدیریت یک سازمان برای ادمین پلتفرم: پلن، تعلیق، دسترسی موقت پشتیبانی، خروجی داده و خروج سازمان.
 * عملیات حساس شناسه سازمان را به‌صورت تایپی می‌خواهد و همه با دلیل در گزارش فعالیت می‌ماند.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { api, authFetch, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { faDate, faNumber, faShortDateTime } from "@/lib/format";
import { promptDialog } from "@/ui/dialogs";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Select, Skeleton } from "@/ui/primitives";

type Org = Schemas["OrganizationStats"];
type PlanId = Schemas["PlanIn"]["plan_id"];
const PLANS: [PlanId, string][] = [["trial", "آزمایشی"], ["basic", "پایه"], ["pro", "حرفه‌ای"], ["enterprise", "سازمانی"]];

const askReason = (title: string) => promptDialog({ title, label: "دلیل", required: true, minLength: 3, multiline: true, confirmLabel: "ثبت" });

export function OrganizationAdmin({ org, onClose }: { org: Org | null; onClose: () => void }) {
  const me = useMe();
  const toast = useToast();
  const queryClient = useQueryClient();
  const id = org?.id ?? 0;
  const [plan, setPlan] = useState<PlanId | "">("");
  const open = org !== null;
  const summary = useQuery({ queryKey: ["org-plan", id], queryFn: () => unwrap(api.GET("/platform/organizations/{organization_id}/plan", { params: { path: { organization_id: id } } })), enabled: open });
  const grants = useQuery({ queryKey: ["org-grants", id], queryFn: () => unwrap(api.GET("/platform/organizations/{organization_id}/support-access", { params: { path: { organization_id: id } } })), enabled: open });
  const exportsList = useQuery({ queryKey: ["org-exports", id], queryFn: () => unwrap(api.GET("/platform/organizations/{organization_id}/exports", { params: { path: { organization_id: id } } })), enabled: open, refetchInterval: 15_000 });
  const path = { params: { path: { organization_id: id } } };
  const refresh = () => { for (const key of ["org-plan", "org-grants", "org-exports", "platform-orgs"]) queryClient.invalidateQueries({ queryKey: [key] }); };
  const run = useMutation({
    mutationFn: (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => { toast.success("ثبت شد."); refresh(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const typed = (title: string) => promptDialog({ title, label: `برای تأیید، شناسه سازمان را بنویسید: ${org?.slug} (شماره ${faNumber(id)})`, required: true, confirmLabel: "تأیید", danger: true });
  const suspend = async () => {
    const reason = await askReason(`تعلیق «${org?.name}»`);
    if (!reason?.trim()) return;
    const confirm_slug = await typed("تعلیق سازمان: کار تازه بسته می‌شود و کارهای در جریان ادامه دارند");
    if (confirm_slug) run.mutate(() => unwrap(api.POST("/platform/organizations/{organization_id}/suspend", { ...path, body: { reason: reason.trim(), confirm_slug } })));
  };
  const resume = async () => {
    const reason = await askReason(`برداشتن تعلیق «${org?.name}»`);
    if (reason?.trim()) run.mutate(() => unwrap(api.POST("/platform/organizations/{organization_id}/resume", { ...path, body: { reason: reason.trim() } })));
  };
  const changePlan = async () => {
    const reason = await askReason("تغییر پلن");
    if (reason?.trim() && plan) run.mutate(() => unwrap(api.PUT("/platform/organizations/{organization_id}/plan", { ...path, body: { plan_id: plan, reason: reason.trim() } })));
  };
  const grant = async () => {
    const reason = await askReason("دسترسی موقت پشتیبانی (۶۰ دقیقه)");
    if (reason?.trim()) run.mutate(() => unwrap(api.POST("/platform/organizations/{organization_id}/support-access", { ...path, body: { user_id: me.id, reason: reason.trim(), minutes: 60 } })));
  };
  const startExport = async () => {
    const reason = await askReason("خروجی کامل داده سازمان");
    if (reason?.trim()) run.mutate(() => unwrap(api.POST("/platform/organizations/{organization_id}/exports", { ...path, body: { reason: reason.trim() } })));
  };
  const download = async (exportId: number) => {
    const res = await authFetch(`/platform/organizations/${id}/exports/${exportId}/download`);
    if (!res.ok) return toast.error("فایل در دسترس نیست.");
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url; a.download = `organization-${id}-export-${exportId}.zip`; a.click();
    URL.revokeObjectURL(url);
  };
  const deprovision = async () => {
    const reason = await askReason(`خروج «${org?.name}»`);
    if (!reason?.trim()) return;
    const confirm_slug = await typed("سازمان همین حالا بسته می‌شود و داده شخصی پس از ۳۰ روز پاک می‌شود");
    if (confirm_slug) run.mutate(() => unwrap(api.POST("/platform/organizations/{organization_id}/deprovision", { ...path, body: { reason: reason.trim(), confirm_slug } })));
  };

  return (
    <Modal open={open} onClose={onClose} title={org ? `مدیریت ${org.name}` : ""} size="lg" testId="org-admin">
      {!org ? null : (
        <div className="space-y-6 text-sm">
          <section className="space-y-2" data-testid="org-plan">
            <h4 className="font-bold">پلن و مصرف</h4>
            {summary.isLoading ? <Skeleton className="h-16" /> : summary.data && <>
              <p className="text-text-2">{summary.data.label} (نسخه {faNumber(summary.data.version)}){summary.data.grace_until && ` — مهلت تا ${faDate(summary.data.grace_until)}`}</p>
              <ul className="grid gap-2 sm:grid-cols-2">{summary.data.resources.map(r => (
                <li key={r.key} className="flex justify-between rounded-lg bg-surface-2 px-3 py-2"><span>{r.label}</span><span className={r.near_limit ? "font-semibold text-warning" : ""}>{faNumber(r.used)} از {faNumber(r.limit)}</span></li>
              ))}</ul>
              <div className="flex flex-wrap gap-2">
                <Select value={plan || summary.data.plan_id} onChange={e => setPlan(e.target.value as PlanId)} className="w-44" aria-label="پلن" data-testid="org-plan-select">
                  {PLANS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </Select>
                <Button size="sm" variant="secondary" disabled={!plan || plan === summary.data.plan_id} onClick={changePlan} data-testid="org-plan-save">تغییر پلن</Button>
              </div>
            </>}
          </section>

          <section className="space-y-2">
            <h4 className="font-bold">تعلیق</h4>
            {org.suspended_at ? <>
              <p className="text-warning">تعلیق از {faShortDateTime(org.suspended_at)}: {org.suspension_reason}</p>
              <Button size="sm" variant="secondary" onClick={resume} data-testid="org-resume">برداشتن تعلیق</Button>
            </> : <Button size="sm" variant="outline-danger" onClick={suspend} data-testid="org-suspend">تعلیق سازمان</Button>}
          </section>

          <section className="space-y-2" data-testid="org-support">
            <h4 className="font-bold">دسترسی موقت پشتیبانی</h4>
            <ul className="space-y-1">{(grants.data ?? []).map(g => (
              <li key={g.id} className="flex flex-wrap items-center gap-2">
                <Badge tone={g.active ? "warning" : "muted"}>{g.active ? "فعال" : "پایان‌یافته"}</Badge>{g.user_name} — {g.reason} — تا {faShortDateTime(g.expires_at)}
                {g.active && <Button size="sm" variant="ghost" onClick={() => run.mutate(() => unwrap(api.POST("/platform/support-access/{grant_id}/revoke", { params: { path: { grant_id: g.id } } })))} data-testid="grant-revoke">لغو</Button>}
              </li>
            ))}</ul>
            <Button size="sm" variant="secondary" onClick={grant} data-testid="grant-create">دسترسی برای خودم (۶۰ دقیقه)</Button>
          </section>

          <section className="space-y-2" data-testid="org-exports">
            <h4 className="font-bold">خروجی داده و خروج سازمان</h4>
            <ul className="space-y-1">{(exportsList.data ?? []).map(x => (
              <li key={x.id} className="flex flex-wrap items-center gap-2">
                <Badge tone={x.status === "done" ? "success" : x.status === "failed" ? "danger" : "muted"}>{x.status === "done" ? "آماده" : x.status === "failed" ? "ناموفق" : "در حال ساخت"}</Badge>{faShortDateTime(x.created_at)}
                {x.status === "done" && <Button size="sm" variant="ghost" icon={<Download className="size-4" />} onClick={() => download(x.id)}>دریافت</Button>}
              </li>
            ))}</ul>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" onClick={startExport} data-testid="export-create">ساخت خروجی</Button>
              {org.deprovision_requested_at
                ? <Button size="sm" variant="ghost" onClick={async () => { const reason = await askReason("لغو خروج سازمان"); if (reason?.trim()) run.mutate(() => unwrap(api.POST("/platform/organizations/{organization_id}/deprovision/cancel", { ...path, body: { reason: reason.trim() } }))); }}>لغو خروج (ثبت‌شده در {faDate(org.deprovision_requested_at)})</Button>
                : <Button size="sm" variant="outline-danger" onClick={deprovision} data-testid="org-deprovision">ثبت خروج سازمان</Button>}
            </div>
          </section>
        </div>
      )}
    </Modal>
  );
}
