/**
 * مرکز استثنا: کارهایی که از روند عادی خارج شده‌اند، با مسئول، مهلت و تاریخچه.
 * از مرکز اقدام و خط زمانی سفارش باز می‌شود و در منو نیست. فیلترها در آدرس صفحه می‌مانند.
 */
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw, UserCheck } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { useUsers } from "@/hooks/data";
import { faNumber, faShortDateTime } from "@/lib/format";
import { promptDialog } from "@/ui/dialogs";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Card, EmptyState, ErrorState, Input, PageHeader, Select, Skeleton, Textarea } from "@/ui/primitives";

type Item = Schemas["ExceptionOut"];
type Update = Schemas["ExceptionUpdate"];

const SEVERITY_TONE = { low: "muted", medium: "info", high: "warning", critical: "danger" } as const;
const STATUS_OPTIONS = [["active", "باز"], ["resolved", "حل‌شده"], ["merged", "ادغام‌شده"], ["all", "همه"]] as const;
const TEAMS = [["warehouse", "انبار"], ["fleet", "ناوگان"], ["support", "پشتیبانی"], ["management", "مدیریت"]] as const;
const SEVERITIES = [["critical", "بحرانی"], ["high", "زیاد"], ["medium", "متوسط"], ["low", "کم"]] as const;

export default function ExceptionsPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [open, setOpen] = useState<number | null>(null);
  const status = (params.get("status") ?? "active") as (typeof STATUS_OPTIONS)[number][0];
  const team = params.get("team") ?? "";
  const severity = params.get("severity") ?? "";
  const urgent = params.get("urgent") === "true";
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key === "severity") next.delete("urgent");
    setParams(next, { replace: true });
  };
  const { data, error, refetch, isLoading } = useQuery({
    queryKey: ["exceptions", status, team, severity, urgent],
    queryFn: () => unwrap(api.GET("/exceptions/", { params: { query: {
      status, urgent, team: (team || null) as Item["team"] | null, severity: (severity || null) as Item["severity"] | null,
    } } })),
  });
  const refresh = () => { queryClient.invalidateQueries({ queryKey: ["exceptions"] }); queryClient.invalidateQueries({ queryKey: ["action-center"] }); };
  const scan = useMutation({
    mutationFn: () => unwrap(api.POST("/exceptions/scan")),
    onSuccess: r => { toast.success(`بررسی شد: ${faNumber(r.created)} مورد تازه، ${faNumber(r.closed)} مورد بسته شد.`); refresh(); },
    onError: e => toast.error(errorMessage(e)),
  });

  return (
    <>
      <PageHeader eyebrow="عملیات" title="مرکز استثنا" subtitle="کارهایی که از روند عادی خارج شده‌اند؛ هر ۱۵ دقیقه خودکار بررسی می‌شوند."
        actions={<Button variant="secondary" icon={<RefreshCw className="size-4" />} loading={scan.isPending} onClick={() => scan.mutate()} data-testid="exceptions-scan">بررسی دوباره</Button>} />
      <div className="mb-4 flex flex-wrap gap-2">
        <Select value={status} onChange={e => setFilter("status", e.target.value)} className="w-40" aria-label="وضعیت" data-testid="exceptions-status">
          {STATUS_OPTIONS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
        <Select value={team} onChange={e => setFilter("team", e.target.value)} className="w-40" aria-label="تیم" data-testid="exceptions-team">
          <option value="">همه تیم‌ها</option>{TEAMS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
        <Select value={urgent ? "urgent" : severity} onChange={e => e.target.value === "urgent" ? setParams({ status, urgent: "true" }, { replace: true }) : setFilter("severity", e.target.value)} className="w-40" aria-label="شدت" data-testid="exceptions-severity">
          <option value="">همه شدت‌ها</option><option value="urgent">فوری (زیاد و بحرانی)</option>{SEVERITIES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
      </div>
      {isLoading ? <Skeleton className="h-48 rounded-2xl" /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data?.length ? (
        <Card><EmptyState icon={<AlertTriangle className="size-5" />} title="استثنایی نیست" text="موردی با این فیلترها پیدا نشد." /></Card>
      ) : (
        <div className="space-y-3">
          {data.map(item => <ExceptionCard key={item.id} item={item} onOpen={() => setOpen(item.id)} onChanged={refresh} />)}
        </div>
      )}
      <ExceptionModal id={open} onClose={() => setOpen(null)} onChanged={refresh} />
    </>
  );
}

function useUpdate(id: number | null, onChanged: () => void) {
  const toast = useToast();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Update) => unwrap(api.PATCH("/exceptions/{exception_id}", { params: { path: { exception_id: id! } }, body })),
    onSuccess: () => { toast.success("ثبت شد."); onChanged(); queryClient.invalidateQueries({ queryKey: ["exception", id] }); },
    onError: e => toast.error(errorMessage(e)),
  });
}

const askResolution = () => promptDialog({ title: "بستن استثنا", label: "نتیجه", required: true, multiline: true, confirmLabel: "بستن" });

function ExceptionCard({ item, onOpen, onChanged }: { item: Item; onOpen: () => void; onChanged: () => void }) {
  const update = useUpdate(item.id, onChanged);
  const active = ["open", "in_progress", "waiting"].includes(item.status);
  return (
    <Card className="p-4" data-testid="exception-card" data-kind={item.kind} data-status={item.status}>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="font-bold hover:text-brand" onClick={onOpen} data-testid="exception-open">{item.kind_label}</button>
        <Badge tone={SEVERITY_TONE[item.severity]}>{item.severity_label}</Badge>
        <Badge tone="muted">{item.team_label}</Badge>
        <Badge tone={active ? "brand" : "muted"}>{item.status_label}</Badge>
        {item.overdue && <Badge tone="danger">از مهلت گذشته</Badge>}
      </div>
      <p className="mt-2 text-sm text-text-2">{item.trigger_reason}</p>
      {active && item.suggested_action && <p className="mt-1 text-sm"><span className="text-muted">اقدام پیشنهادی: </span>{item.suggested_action}</p>}
      {item.resolution && <p className="mt-1 text-sm"><span className="text-muted">نتیجه: </span>{item.resolution}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-muted">
        <span>باز شده: {faShortDateTime(item.opened_at)}</span>
        {item.due_at && <span>مهلت: {faShortDateTime(item.due_at)}</span>}
        <span>مسئول: {item.owner_name ?? "تعیین نشده"}</span>
        <span className="ms-auto flex flex-wrap items-center gap-2">
          {item.link && <Link to={item.link} className="font-medium text-brand">مشاهده مورد ←</Link>}
          {active && item.suggested_owner && (
            <Button size="sm" variant="soft" icon={<UserCheck className="size-4" />} loading={update.isPending} data-testid="exception-suggest"
              onClick={() => update.mutate({ owner_id: item.suggested_owner!.id })}>
              پیشنهاد: {item.suggested_owner.name} ({faNumber(item.suggested_owner.open_count)} مورد باز)
            </Button>
          )}
          {active && <Button size="sm" variant="secondary" data-testid="exception-resolve"
            onClick={() => askResolution().then(r => { if (r) update.mutate({ status: "resolved", resolution: r }); })}>بستن</Button>}
        </span>
      </div>
    </Card>
  );
}

function ExceptionModal({ id, onClose, onChanged }: { id: number | null; onClose: () => void; onChanged: () => void }) {
  const me = useMe();
  const [note, setNote] = useState("");
  const [mergeInto, setMergeInto] = useState("");
  const update = useUpdate(id, () => { setNote(""); setMergeInto(""); onChanged(); });
  const { data: users = [] } = useUsers(id !== null && me.role === "org_admin");
  const { data } = useQuery({
    queryKey: ["exception", id],
    queryFn: () => unwrap(api.GET("/exceptions/{exception_id}", { params: { path: { exception_id: id! } } })),
    enabled: id !== null,
  });
  const active = !!data && ["open", "in_progress", "waiting"].includes(data.status);
  return (
    <Modal open={id !== null} onClose={onClose} title={data ? `${data.kind_label} #${faNumber(data.id)}` : "استثنا"} size="lg" testId="exception-modal">
      {!data ? <Skeleton className="h-40" /> : (
        <div className="space-y-4">
          <p className="text-sm text-text-2">{data.trigger_reason}</p>
          {active && (
            <div className="grid gap-3 sm:grid-cols-2">
              {me.role === "org_admin" && (
                <Select value={data.owner_id ?? ""} aria-label="مسئول" data-testid="exception-owner"
                  onChange={e => update.mutate({ owner_id: e.target.value ? Number(e.target.value) : null })}>
                  <option value="">بدون مسئول</option>
                  {users.filter(u => u.role === "org_admin" || u.role === "warehouse_manager").map(u => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
                </Select>
              )}
              <Select value={data.status} aria-label="وضعیت" data-testid="exception-state" onChange={e => update.mutate({ status: e.target.value as "open" })}>
                <option value="open">باز</option><option value="in_progress">در حال رسیدگی</option><option value="waiting">منتظر</option>
              </Select>
              <div className="flex gap-2 sm:col-span-2">
                <Textarea rows={2} placeholder="یادداشت" value={note} onChange={e => setNote(e.target.value)} maxLength={500} data-testid="exception-note" />
                <Button variant="secondary" disabled={!note.trim()} loading={update.isPending} onClick={() => update.mutate({ note })} data-testid="exception-note-save">ثبت</Button>
              </div>
              <div className="flex gap-2 sm:col-span-2">
                <Input placeholder="شماره استثنای مقصد برای ادغام" inputMode="numeric" value={mergeInto} onChange={e => setMergeInto(e.target.value)} aria-label="ادغام در" />
                <Button variant="ghost" disabled={!Number(mergeInto)} onClick={() => update.mutate({ merged_into_id: Number(mergeInto) })}>ادغام</Button>
              </div>
            </div>
          )}
          <div>
            <h4 className="mb-2 text-sm font-bold">تاریخچه</h4>
            <ul className="divide-y divide-border rounded-xl border border-border text-sm" data-testid="exception-events">
              {data.events.map((e, i) => (
                <li key={i} className="px-4 py-2">
                  <div className="flex flex-wrap justify-between gap-2"><span className="font-medium">{e.action}</span><span className="text-xs text-muted">{faShortDateTime(e.at)} — {e.actor}</span></div>
                  {e.note && <p className="mt-1 text-text-2">{e.note}</p>}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </Modal>
  );
}
