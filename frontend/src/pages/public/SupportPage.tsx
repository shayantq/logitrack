/** پیگیری درخواست پشتیبانی مشتری با لینک اختصاصی (/support/:token) — بدون ورود، به‌روزرسانی خودکار */
import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Copy, LifeBuoy, Package, X } from "lucide-react";
import { api, errorMessage, unwrap } from "@/api/client";
import { BRAND } from "@/brand";
import { useToast } from "@/components/Toast";
import { TicketThread } from "@/components/tickets/TicketThread";
import { messageForm, postForm, TICKET_STATUS, waitingLabel, type Ticket } from "@/lib/tickets";
import { faShortDateTime } from "@/lib/format";
import { Badge, Button, Spinner } from "@/ui/primitives";
import { PublicFooter, PublicHeader } from "./chrome";

export default function SupportPage() {
  const { token = "" } = useParams();
  const { state } = useLocation() as { state?: { created?: boolean } };
  const toast = useToast();
  const queryClient = useQueryClient();
  const key = ["support", token];
  const query = useQuery({
    queryKey: key,
    queryFn: () => unwrap(api.GET("/public/tickets/{token}", { params: { path: { token } } })),
    refetchInterval: q => (q.state.data?.status === "closed" ? false : 15_000),
    retry: false,
  });
  useEffect(() => { document.title = `پیگیری درخواست پشتیبانی — ${BRAND.name}`; }, []);
  const [justCreated, setJustCreated] = useState(!!state?.created);
  const send = useMutation({
    mutationFn: ({ body, file }: { body: string; file: File | null }) =>
      postForm<Ticket>(`/public/tickets/${token}/messages`, messageForm(body, {}, file), false),
    onSuccess: t => queryClient.setQueryData(key, t),
    onError: e => toast.error(errorMessage(e)),
  });
  const resolve = useMutation({
    mutationFn: () => unwrap(api.POST("/public/tickets/{token}/resolve", { params: { path: { token } } })),
    onSuccess: t => { queryClient.setQueryData(key, t); toast.success("ممنون؛ درخواست حل‌شده ثبت شد."); },
  });
  const t = query.data;
  const waiting = t ? waitingLabel(t, "requester") : null;

  return (
    <div className="min-h-svh bg-bg text-text">
      <PublicHeader />
      <main className="mx-auto max-w-3xl px-4 pb-24 pt-28 sm:px-6">
        {query.isLoading ? <div className="grid place-items-center py-24"><Spinner className="size-7" /></div>
          : query.error || !t ? (
            <div className="card p-10 text-center" data-testid="support-error">
              <X className="mx-auto size-10 text-danger" />
              <p className="mt-3 font-semibold">{errorMessage(query.error) || "درخواستی با این لینک یافت نشد."}</p>
            </div>
          ) : (
            <div className="stagger space-y-5" data-testid="support-page" data-status={t.status}>
              {justCreated && (
                <div className="card flex items-start gap-3 border-success/30 bg-success-soft/60 p-5" data-testid="support-created">
                  <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" />
                  <div className="flex-1 text-sm leading-7">
                    <div className="font-bold">درخواست شما ثبت شد (کد <span className="font-mono ltr">{t.code}</span>).</div>
                    این صفحه را نشانه‌گذاری کنید یا لینک آن را نگه دارید؛ پاسخ فروشنده همین‌جا نمایش داده می‌شود.
                  </div>
                  <button type="button" onClick={() => setJustCreated(false)} aria-label="بستن" className="text-muted hover:text-text"><X className="size-4" /></button>
                </div>
              )}
              <div className="card p-5 sm:p-6">
                <div className="flex flex-wrap items-start gap-3">
                  <span className="grid size-11 place-items-center rounded-2xl bg-brand-soft text-brand"><LifeBuoy className="size-5" /></span>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-muted">{t.organization_name}</div>
                    <h1 className="text-lg font-bold leading-8">{t.subject}</h1>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                      <span className="font-mono ltr">{t.code}</span>
                      <Badge tone={TICKET_STATUS[t.status].tone}>{TICKET_STATUS[t.status].label}</Badge>
                      {waiting && <Badge tone={waiting.mine ? "brand" : "muted"} dot={waiting.mine}>{waiting.label}</Badge>}
                      <span>· {faShortDateTime(t.created_at)}</span>
                    </div>
                  </div>
                  <Button size="sm" variant="ghost" icon={<Copy className="size-3.5" />}
                    onClick={() => navigator.clipboard?.writeText(location.href).then(() => toast.success("لینک کپی شد."), () => {})}>کپی لینک</Button>
                </div>
                {t.order_tracking_code && (
                  <Link to={`/track/${t.order_tracking_code}`} className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-brand hover:underline">
                    <Package className="size-4" />پیگیری سفارش <span className="font-mono ltr">{t.order_tracking_code}</span>
                  </Link>
                )}
              </div>
              <div className="card p-4 sm:p-5">
                <TicketThread ticket={t} auth={false} attachmentUrl={mid => `/public/tickets/${token}/messages/${mid}/attachment`}
                  onSend={(body, _v, file) => send.mutateAsync({ body, file })} sending={send.isPending} />
                {t.status === "open" && (
                  <div className="mt-3 flex justify-end">
                    <Button size="sm" variant="soft" icon={<CheckCircle2 className="size-4" />} loading={resolve.isPending}
                      onClick={() => resolve.mutate()} data-testid="support-resolve">مشکلم حل شد</Button>
                  </div>
                )}
              </div>
            </div>
          )}
      </main>
      <PublicFooter />
    </div>
  );
}
