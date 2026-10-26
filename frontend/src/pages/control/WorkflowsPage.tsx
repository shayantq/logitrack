/**
 * گردش‌کار اسناد (فصل ۲۰): ماشین وضعیت هر سند و عملیات — وضعیت‌ها به ترتیب، انتقال‌های مجاز، اقدام و انجام‌دهنده.
 * مرجع آموزش کاربران؛ اجرای واقعی و کنترل نقش/مجوز هر انتقال در سرور است.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Flag, GitBranch } from "lucide-react";
import { api, unwrap } from "@/api/client";
import { Badge, Card, ErrorState, PageHeader, Skeleton, cn } from "@/ui/primitives";

export default function WorkflowsPage() {
  const q = useQuery({ queryKey: ["workflows"], queryFn: () => unwrap(api.GET("/workflows/")), staleTime: Infinity });
  const [active, setActive] = useState<string | null>(null);
  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const current = q.data.find(w => w.code === (active ?? q.data[0]?.code)) ?? q.data[0];
  return (
    <>
      <PageHeader eyebrow="تنظیمات" title="گردش‌کار اسناد" subtitle="هر سند از چه وضعیت‌هایی می‌گذرد، با چه اقدامی و توسط چه کسی" />
      <div className="grid gap-5 lg:grid-cols-[16rem_1fr]">
        <Card className="h-fit p-2" data-testid="workflow-list">
          {q.data.map(w => (
            <button key={w.code} type="button" onClick={() => setActive(w.code)} data-testid="workflow-item"
              className={cn("flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-start text-sm transition",
                current.code === w.code ? "bg-brand-soft font-semibold text-text" : "text-text-2 hover:bg-surface-2")}>
              <GitBranch className="size-4 text-brand" />{w.label}<span className="ms-auto text-xs text-muted">{w.states.length}</span>
            </button>
          ))}
        </Card>
        <Card className="p-5" data-testid="workflow-detail" data-code={current.code}>
          <h2 className="text-lg font-bold">{current.label}</h2>
          {current.note && <p className="mt-1 text-sm text-text-2">{current.note}</p>}
          <div className="mt-4 flex flex-wrap items-center gap-2" data-testid="workflow-states">
            {current.states.map((s, i) => (
              <span key={s.code} className="flex items-center gap-2">
                <Badge tone={s.final ? "muted" : i === 0 ? "brand" : "info"}>{s.final && <Flag className="size-3" />}{s.label}</Badge>
                {i < current.states.length - 1 && <ArrowLeft className="size-3.5 text-muted" />}
              </span>
            ))}
          </div>
          <div className="mt-5 overflow-x-auto">
            <table className="table-base" data-testid="workflow-transitions">
              <thead><tr><th>از</th><th>به</th><th>اقدام</th><th>انجام‌دهنده</th></tr></thead>
              <tbody>{current.transitions.map((t, i) => {
                const label = (c: string) => current.states.find(s => s.code === c)?.label ?? c;
                return (
                  <tr key={i}><td><Badge tone="muted">{label(t.from)}</Badge></td><td><Badge tone="info">{label(t.to)}</Badge></td>
                    <td className="text-sm">{t.action}</td><td className="text-xs text-text-2">{t.actor}</td></tr>
                );
              })}</tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  );
}
