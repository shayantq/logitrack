/**
 * پیام‌ها و وظایف پس‌زمینه ناموفق برای کارکنان پلتفرم. متن پیام هرگز نمایش داده نمی‌شود و گیرنده نیمه‌پنهان است.
 * اجرای دوباره دلیل می‌خواهد و در گزارش فعالیت می‌ماند. پیام حساس (رمز موقت، کد بازیابی) دوباره ارسال نمی‌شود.
 * پیام «نامعلوم» جدا نشان داده می‌شود: پذیرش سرویس‌دهنده با رسیدن به گیرنده یکی نیست و ارسال دوباره خطر تکرار دارد.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { api, errorMessage, unwrap } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { faNumber, faShortDateTime } from "@/lib/format";
import { promptDialog } from "@/ui/dialogs";
import { Badge, Button, Card, CardHeader, ErrorState, Skeleton } from "@/ui/primitives";

const KEY = ["platform-operations"];

/** قابلیت‌هایی که می‌شود سریع خاموش کرد؛ توقف اضطراری بر فهرست مجاز مقدم است */
function FeatureFlags({ isAdmin }: { isAdmin: boolean }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ["feature-flags"], queryFn: () => unwrap(api.GET("/platform/feature-flags")) });
  const save = useMutation({
    mutationFn: ({ key, kill, reason, allowlist }: { key: string; kill: boolean; reason: string; allowlist: number[] }) =>
      unwrap(api.PUT("/platform/feature-flags/{key}", { params: { path: { key } }, body: { enabled: true, kill_switch: kill, allowlist, reason } })),
    onSuccess: () => { toast.success("ثبت شد."); queryClient.invalidateQueries({ queryKey: ["feature-flags"] }); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <ul className="divide-y divide-border border-t border-border text-sm" data-testid="feature-flags">
      {data.map(f => (
        <li key={f.key} className="flex flex-wrap items-center gap-2 px-5 py-3" data-testid="feature-flag">
          <span className="font-medium">{f.label}</span>
          <Badge tone={f.kill_switch ? "danger" : "success"}>{f.kill_switch ? "متوقف" : f.allowlist.length ? `${faNumber(f.allowlist.length)} سازمان` : "همه سازمان‌ها"}</Badge>
          {isAdmin && <Button size="sm" variant={f.kill_switch ? "secondary" : "outline-danger"} className="ms-auto" data-testid="flag-kill"
            onClick={() => promptDialog({ title: f.kill_switch ? "برداشتن توقف" : "توقف اضطراری", label: "دلیل", required: true, minLength: 3, confirmLabel: "ثبت", danger: !f.kill_switch })
              .then(reason => { if (reason?.trim()) save.mutate({ key: f.key, kill: !f.kill_switch, reason: reason.trim(), allowlist: f.allowlist }); })}>{f.kill_switch ? "برداشتن توقف" : "توقف اضطراری"}</Button>}
        </li>
      ))}
    </ul>
  );
}

export function OperationsHealth() {
  const me = useMe();
  const toast = useToast();
  const queryClient = useQueryClient();
  const isAdmin = me.role === "platform_admin";
  const { data, error, refetch, isLoading } = useQuery({ queryKey: KEY, queryFn: () => unwrap(api.GET("/platform/operations")), refetchInterval: 60_000 });
  const replay = useMutation({
    mutationFn: async ({ kind, id, reason }: { kind: "message" | "task"; id: number; reason: string }) => {
      if (kind === "message") await unwrap(api.POST("/platform/operations/messages/{message_id}/retry", { params: { path: { message_id: id } }, body: { reason, conflict_reviewed: false } }));
      else await unwrap(api.POST("/platform/operations/tasks/{failure_id}/replay", { params: { path: { failure_id: id } }, body: { reason, conflict_reviewed: false } }));
    },
    onSuccess: () => { toast.success("دوباره در صف قرار گرفت."); queryClient.invalidateQueries({ queryKey: KEY }); },
    onError: e => toast.error(errorMessage(e)),
  });
  const ask = async (kind: "message" | "task", id: number, conflict = false) => {
    const reason = await promptDialog(conflict
      ? { title: "ارسال دوباره پس از برخورد شناسه", label: "پاسخ کاوه‌نگار با این پیام نمی‌خواند و شناسه تازه می‌گیرد. دلیل بررسی", required: true, minLength: 3, confirmLabel: "بررسی شد، ارسال" }
      : { title: "اجرای دوباره", label: "دلیل", required: true, minLength: 3, confirmLabel: "اجرا" });
    if (!reason?.trim()) return;
    if (conflict) resolve.mutate({ id, kind: "conflict", reason: reason.trim() });
    else replay.mutate({ kind, id, reason: reason.trim() });
  };
  const resolve = useMutation({
    mutationFn: async ({ id, kind, reason }: { id: number; kind: "confirm_accepted" | "resend" | "conflict"; reason: string }) => {
      if (kind === "conflict") await unwrap(api.POST("/platform/operations/messages/{message_id}/retry", { params: { path: { message_id: id } }, body: { reason, conflict_reviewed: true } }));
      else await unwrap(api.POST("/platform/operations/messages/{message_id}/resolve", { params: { path: { message_id: id } }, body: { action: kind, reason, accept_duplicate_risk: kind === "resend" } }));
    },
    onSuccess: () => { toast.success("ثبت شد."); queryClient.invalidateQueries({ queryKey: KEY }); },
    onError: e => toast.error(errorMessage(e)),
  });
  const settle = async (id: number, kind: "confirm_accepted" | "resend") => {
    const reason = await promptDialog(kind === "resend"
      ? { title: "ارسال دوباره با خطر پیامک تکراری", label: "شاید گیرنده پیامک را گرفته باشد و دوباره بگیرد. با همان شناسه فرستاده می‌شود تا کاوه‌نگار تکرار را رد کند. دلیل", required: true, minLength: 3, confirmLabel: "می‌پذیرم، ارسال", danger: true }
      : { title: "ثبت پذیرش سرویس‌دهنده", label: "پس از بررسی پنل کاوه‌نگار؛ چیزی فرستاده نمی‌شود و رسیدن به گیرنده را ثابت نمی‌کند. دلیل", required: true, minLength: 3, confirmLabel: "ثبت" });
    if (reason?.trim()) resolve.mutate({ id, kind, reason: reason.trim() });
  };
  if (isLoading) return <Skeleton className="mb-6 h-24 rounded-2xl" />;
  if (error || !data) return <div className="mb-6"><ErrorState error={error} onRetry={refetch} /></div>;
  const unconfirmed = data.unconfirmed ?? [];
  const empty = !data.messages.length && !data.tasks.length && !unconfirmed.length;
  return (
    <Card className="mb-6" data-testid="operations-health">
      <CardHeader title="سلامت پس‌زمینه"
        subtitle={`${faNumber(data.pending)} پیام در صف ارسال${data.oldest_pending_seconds > 0 ? ` · قدیمی‌ترین ${faNumber(Math.round(data.oldest_pending_seconds / 60))} دقیقه` : ""} · صف وظایف: ${data.queue_depth == null ? "نامعلوم" : faNumber(data.queue_depth)}`} />
      {unconfirmed.length > 0 && (
        <section className="border-b border-border" data-testid="unconfirmed-messages">
          <p className="px-5 pt-3 text-sm font-bold">نتیجه نامعلوم ({faNumber(unconfirmed.length)})</p>
          <p className="px-5 text-xs text-muted">شاید کاوه‌نگار این پیام‌ها را پذیرفته باشد. خودکار دوباره فرستاده نمی‌شوند و ناموفق هم حساب نمی‌شوند.</p>
          <ul className="divide-y divide-border text-sm">
            {unconfirmed.map(m => (
              <li key={`u${m.id}`} className="flex flex-wrap items-center gap-2 px-5 py-3" data-testid="unconfirmed-message">
                <Badge tone="warning">پیامک نامعلوم</Badge>
                <span className="font-mono text-xs ltr">{m.recipient}</span>
                <span className="min-w-0 truncate text-xs text-muted">{faShortDateTime(m.first_attempt_at ?? m.created_at)} · {faNumber(m.attempts)} تلاش{m.sensitive ? " · حساس" : ""}{m.provider_status != null ? ` · کد سرویس‌دهنده ${faNumber(m.provider_status)}` : ""}</span>
                {isAdmin && (
                  <span className="ms-auto flex flex-wrap gap-2">
                    <Button size="sm" variant="secondary" onClick={() => settle(m.id, "confirm_accepted")} data-testid="unconfirmed-accept">پذیرش ثبت شود</Button>
                    {m.sensitive
                      ? <span className="text-xs text-muted">حساس؛ کد باید دوباره صادر شود</span>
                      : <Button size="sm" variant="outline-danger" onClick={() => settle(m.id, "resend")} data-testid="unconfirmed-resend">ارسال دوباره</Button>}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {empty ? <p className="p-5 text-sm text-muted" data-testid="operations-empty">پیام یا وظیفه ناموفقی نیست.</p> : (
        <ul className="divide-y divide-border text-sm">
          {data.messages.map(m => (
            <li key={`m${m.id}`} className="flex flex-wrap items-center gap-2 px-5 py-3" data-testid="failed-message">
              <Badge tone="danger">{m.channel === "sms" ? "پیامک" : "ایمیل"} ناموفق</Badge>
              <span className="font-mono text-xs ltr">{m.recipient}</span>
              <span className="min-w-0 truncate text-xs text-muted">{faShortDateTime(m.created_at)} · {faNumber(m.attempts)} تلاش · {m.last_error}</span>
              {isAdmin && (m.replayable
                ? <Button size="sm" variant="secondary" className="ms-auto" icon={<RotateCcw className="size-4" />} onClick={() => ask("message", m.id, m.conflict)} data-testid="message-retry">{m.conflict ? "بررسی برخورد و ارسال" : "ارسال دوباره"}</Button>
                : <span className="ms-auto text-xs text-muted">حساس؛ باید دوباره صادر شود</span>)}
            </li>
          ))}
          {data.tasks.map(t => (
            <li key={`t${t.id}`} className="flex flex-wrap items-center gap-2 px-5 py-3" data-testid="failed-task">
              <Badge tone="warning">وظیفه ناموفق</Badge>
              <span className="font-mono text-xs ltr">{t.task_name}</span>
              <span className="min-w-0 truncate text-xs text-muted">{faShortDateTime(t.created_at)}{t.organization_id ? ` · سازمان ${faNumber(t.organization_id)}` : ""} · {t.error}</span>
              {isAdmin && t.replayable && <Button size="sm" variant="secondary" className="ms-auto" icon={<RotateCcw className="size-4" />} onClick={() => ask("task", t.id)} data-testid="task-replay">اجرای دوباره</Button>}
            </li>
          ))}
        </ul>
      )}
      <FeatureFlags isAdmin={isAdmin} />
    </Card>
  );
}
