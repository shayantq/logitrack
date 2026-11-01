/**
 * پیام‌ها و وظایف پس‌زمینه ناموفق برای کارکنان پلتفرم. متن پیام هرگز نمایش داده نمی‌شود و گیرنده نیمه‌پنهان است.
 * اجرای دوباره دلیل می‌خواهد و در گزارش فعالیت می‌ماند. پیام حساس (رمز موقت، کد بازیابی) دوباره ارسال نمی‌شود.
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

export function OperationsHealth() {
  const me = useMe();
  const toast = useToast();
  const queryClient = useQueryClient();
  const isAdmin = me.role === "platform_admin";
  const { data, error, refetch, isLoading } = useQuery({ queryKey: KEY, queryFn: () => unwrap(api.GET("/platform/operations")), refetchInterval: 60_000 });
  const replay = useMutation({
    mutationFn: async ({ kind, id, reason }: { kind: "message" | "task"; id: number; reason: string }) => {
      if (kind === "message") await unwrap(api.POST("/platform/operations/messages/{message_id}/retry", { params: { path: { message_id: id } }, body: { reason } }));
      else await unwrap(api.POST("/platform/operations/tasks/{failure_id}/replay", { params: { path: { failure_id: id } }, body: { reason } }));
    },
    onSuccess: () => { toast.success("دوباره در صف قرار گرفت."); queryClient.invalidateQueries({ queryKey: KEY }); },
    onError: e => toast.error(errorMessage(e)),
  });
  const ask = async (kind: "message" | "task", id: number) => {
    const reason = await promptDialog({ title: "اجرای دوباره", label: "دلیل", required: true, minLength: 3, confirmLabel: "اجرا" });
    if (reason?.trim()) replay.mutate({ kind, id, reason: reason.trim() });
  };
  if (isLoading) return <Skeleton className="mb-6 h-24 rounded-2xl" />;
  if (error || !data) return <div className="mb-6"><ErrorState error={error} onRetry={refetch} /></div>;
  const empty = !data.messages.length && !data.tasks.length;
  return (
    <Card className="mb-6" data-testid="operations-health">
      <CardHeader title="سلامت پس‌زمینه" subtitle={`${faNumber(data.pending)} پیام در صف ارسال`} />
      {empty ? <p className="p-5 text-sm text-muted" data-testid="operations-empty">پیام یا وظیفه ناموفقی نیست.</p> : (
        <ul className="divide-y divide-border text-sm">
          {data.messages.map(m => (
            <li key={`m${m.id}`} className="flex flex-wrap items-center gap-2 px-5 py-3" data-testid="failed-message">
              <Badge tone="danger">{m.channel === "sms" ? "پیامک" : "ایمیل"} ناموفق</Badge>
              <span className="font-mono text-xs ltr">{m.recipient}</span>
              <span className="min-w-0 truncate text-xs text-muted">{faShortDateTime(m.created_at)} · {faNumber(m.attempts)} تلاش · {m.last_error}</span>
              {isAdmin && (m.replayable
                ? <Button size="sm" variant="secondary" className="ms-auto" icon={<RotateCcw className="size-4" />} onClick={() => ask("message", m.id)} data-testid="message-retry">ارسال دوباره</Button>
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
    </Card>
  );
}
