/**
 * میز پشتیبانی (مرحله ۱۱) — یک صفحه برای سه نقش:
 *   org: همه تیکت‌های مشتریان، رانندگان و تیکت‌های خود سازمان به پشتیبانی پسینه
 *   driver: تیکت‌های خود راننده به سازمان
 *   platform: تیکت‌های ارجاعی همه سازمان‌ها
 * فهرست و گفت‌وگو کنار هم (روی موبایل جدا)؛ هر ۱۵ ثانیه به‌روز می‌شود.
 */
import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Building2, CheckCircle2, Clock, Inbox, LifeBuoy, Lock, MessageSquarePlus, Package, Search, Share2, Truck, UserRound } from "lucide-react";
import { api, errorMessage, unwrap } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { TicketThread } from "@/components/tickets/TicketThread";
import { useUsers } from "@/hooks/data";
import { faShortDateTime } from "@/lib/format";
import { messageForm, postForm, TICKET_CATEGORIES, TICKET_PRIORITY, TICKET_SOURCE, TICKET_STATUS, waitingLabel, type Side, type Ticket, type TicketRow } from "@/lib/tickets";
import { confirmDialog, promptDialog } from "@/ui/dialogs";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, SegmentedControl, Select, Skeleton, Textarea, cn } from "@/ui/primitives";
import { OrderDetailModal } from "../orders/OrderDetailModal";
import { FileField } from "@/ui/file";

type Mode = "org" | "driver" | "platform";
type Tab = "waiting" | "open" | "resolved" | "all";

const CONFIG: Record<Mode, { api: string; route: string; side: Side; title: string; subtitle: string; eyebrow: string }> = {
  org: { api: "/tickets", route: "/app/tickets", side: "org", eyebrow: "ارتباط", title: "پشتیبانی و تیکت‌ها",
    subtitle: "درخواست‌های مشتریان و رانندگان، و تیکت‌های سازمان به پشتیبانی پسینه" },
  driver: { api: "/tickets", route: "/app/driver/support", side: "requester", eyebrow: "راننده", title: "پشتیبانی",
    subtitle: "مشکل یا سؤالتان را برای سازمان بفرستید و پاسخ را همین‌جا ببینید" },
  platform: { api: "/platform/tickets", route: "/app/platform/tickets", side: "platform", eyebrow: "پلتفرم", title: "تیکت‌های پشتیبانی",
    subtitle: "تیکت‌هایی که سازمان‌ها باز کرده یا به پشتیبانی پسینه ارجاع داده‌اند" },
};

const SOURCE_ICON = { customer: UserRound, driver: Truck, org: Building2 } as const;

export function TicketsWorkspace({ mode }: { mode: Mode }) {
  const cfg = CONFIG[mode];
  const { id } = useParams();
  const selected = id ? Number(id) : null;
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>(mode === "driver" ? "all" : "waiting");
  const [source, setSource] = useState<string>("");
  const [q, setQ] = useState("");
  const [newOpen, setNewOpen] = useState(false);

  const params = { waiting: tab === "waiting" || undefined, status: tab === "open" || tab === "resolved" ? tab : undefined,
    source: source || undefined, q: q.trim() || undefined } as const;
  const list = useQuery({
    queryKey: ["tickets", mode, params],
    queryFn: () => mode === "platform"
      ? unwrap(api.GET("/platform/tickets/", { params: { query: params as never } }))
      : unwrap(api.GET("/tickets/", { params: { query: params as never } })),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  });

  return (
    <>
      <PageHeader eyebrow={cfg.eyebrow} title={cfg.title} subtitle={cfg.subtitle}
        actions={mode !== "platform" && (
          <Button icon={<MessageSquarePlus className="size-4" />} onClick={() => setNewOpen(true)} data-testid="ticket-new">
            {mode === "org" ? "تیکت به پشتیبانی پسینه" : "تیکت جدید"}
          </Button>
        )} />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        <Card className={cn("flex max-h-[78vh] flex-col overflow-hidden", selected != null && "hidden lg:flex")}>
          <div className="space-y-2.5 border-b border-border p-3">
            <SegmentedControl value={tab} onChange={setTab} options={[
              ...(mode === "driver" ? [] : [{ value: "waiting" as Tab, label: "منتظر من" }]),
              { value: "open", label: "باز" }, { value: "resolved", label: "حل‌شده" }, { value: "all", label: "همه" },
            ]} />
            <div className="flex gap-2">
              <label className="relative flex-1">
                <Search className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
                <input value={q} onChange={e => setQ(e.target.value)} placeholder="کد، موضوع یا نام" data-testid="ticket-search"
                  className="h-10 w-full rounded-xl border border-border bg-surface pe-3 ps-9 text-sm outline-none focus:border-brand" />
              </label>
              {mode !== "driver" && (
                <Select value={source} onChange={e => setSource(e.target.value)} className="w-32" aria-label="منبع">
                  <option value="">همه منابع</option>
                  {mode === "org" && <><option value="customer">مشتری</option><option value="driver">راننده</option></>}
                  <option value="org">{mode === "org" ? "به پشتیبانی" : "سازمان"}</option>
                  {mode === "platform" && <><option value="customer">مشتری (ارجاعی)</option><option value="driver">راننده (ارجاعی)</option></>}
                </Select>
              )}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto" data-testid="tickets-list">
            {list.isLoading ? <div className="space-y-2 p-3">{[0, 1, 2].map(i => <Skeleton key={i} className="h-20" />)}</div>
              : list.error ? <ErrorState error={list.error} onRetry={list.refetch} />
                : !list.data?.length ? <EmptyState icon={<Inbox className="size-5" />} title={tab === "waiting" ? "تیکتی منتظر پاسخ شما نیست" : "تیکتی پیدا نشد"} />
                  : list.data.map(t => <TicketListRow key={t.id} t={t} side={cfg.side} mode={mode} active={t.id === selected}
                    onClick={() => navigate(`${cfg.route}/${t.id}`)} />)}
          </div>
        </Card>

        <div className={cn(selected == null && "hidden lg:block")}>
          {selected ? <TicketPanel key={selected} id={selected} mode={mode} />
            : <Card className="grid h-full min-h-80 place-items-center p-10 text-center">
                <div><LifeBuoy className="mx-auto size-10 text-muted" /><p className="mt-3 text-sm text-muted">یک تیکت را از فهرست انتخاب کنید.</p></div>
              </Card>}
        </div>
      </div>
      {newOpen && <NewTicketModal mode={mode} onClose={() => setNewOpen(false)} onCreated={t => navigate(`${cfg.route}/${t.id}`)} />}
    </>
  );
}

function TicketListRow({ t, side, mode, active, onClick }: { t: TicketRow; side: Side; mode: Mode; active: boolean; onClick: () => void }) {
  const waiting = waitingLabel(t, side);
  const Icon = SOURCE_ICON[t.source as keyof typeof SOURCE_ICON] ?? UserRound;
  return (
    <button type="button" onClick={onClick} data-testid="ticket-row" data-code={t.code} aria-pressed={active}
      className={cn("block w-full border-b border-border px-4 py-3 text-start transition last:border-b-0", active ? "bg-brand-soft/60" : "hover:bg-surface-2")}>
      <div className="flex items-center gap-2">
        <span className={cn("grid size-7 shrink-0 place-items-center rounded-lg", waiting?.mine ? "bg-brand text-brand-ink" : "bg-surface-2 text-muted")}><Icon className="size-3.5" /></span>
        <span className="min-w-0 flex-1 truncate text-sm font-semibold">{t.subject}</span>
        {t.priority !== "normal" && <Badge tone={TICKET_PRIORITY[t.priority].tone}>{TICKET_PRIORITY[t.priority].label}</Badge>}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
        <span className="font-mono ltr">{t.code}</span>
        {mode === "platform" && t.organization_name && <span>· {t.organization_name}</span>}
        {t.requester_name && mode !== "driver" && <span>· {t.requester_name}</span>}
        <span className="ms-auto">{faShortDateTime(t.last_activity_at)}</span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        {t.status !== "open" ? <Badge tone={TICKET_STATUS[t.status].tone}>{TICKET_STATUS[t.status].label}</Badge>
          : waiting && <Badge tone={waiting.mine ? "brand" : "muted"} dot={waiting.mine}>{waiting.label}</Badge>}
        {t.overdue && waiting?.mine && <Badge tone="danger"><Clock className="size-3" />بیش از ۲۴ ساعت</Badge>}
        {t.escalated_at && mode === "org" && <Badge tone="violet">ارجاع به پشتیبانی</Badge>}
      </div>
    </button>
  );
}

function TicketPanel({ id, mode }: { id: number; mode: Mode }) {
  const cfg = CONFIG[mode];
  const toast = useToast();
  const queryClient = useQueryClient();
  const me = useMe();
  const [orderOpen, setOrderOpen] = useState(false);
  const detail = useQuery({
    queryKey: ["ticket", mode, id],
    queryFn: () => mode === "platform"
      ? unwrap(api.GET("/platform/tickets/{ticket_id}", { params: { path: { ticket_id: id } } }))
      : unwrap(api.GET("/tickets/{ticket_id}", { params: { path: { ticket_id: id } } })),
    refetchInterval: 15_000,
  });
  const staff = useUsers(mode === "org" && me.role === "org_admin");
  const refresh = (t: Ticket) => {
    queryClient.setQueryData(["ticket", mode, id], t);
    queryClient.invalidateQueries({ queryKey: ["tickets"] });
    queryClient.invalidateQueries({ queryKey: ["tickets-summary"] });
  };
  const send = useMutation({
    mutationFn: ({ body, visibility, file }: { body: string; visibility: string; file: File | null }) =>
      postForm<Ticket>(`${cfg.api}/${id}/messages`, messageForm(body, { visibility }, file)),
    onSuccess: t => refresh(t),
    onError: e => toast.error(errorMessage(e)),
  });
  const action = useMutation({
    mutationFn: (fn: () => Promise<Ticket>) => fn(),
    onSuccess: t => refresh(t),
    onError: e => toast.error(errorMessage(e)),
  });

  if (detail.isLoading) return <Card className="p-6"><Skeleton className="h-96" /></Card>;
  if (detail.error || !detail.data) return <ErrorState error={detail.error} onRetry={detail.refetch} />;
  const t = detail.data;
  const waiting = waitingLabel(t, cfg.side);
  const path = { params: { path: { ticket_id: id } } };
  const resolveLabel = cfg.side === "requester" ? "مشکلم حل شد"
    : mode === "platform" && t.source !== "org" ? "پایان بررسی و برگشت به سازمان" : t.source === "org" && mode === "org" ? "مشکل حل شد" : "حل‌شده";

  return (
    <Card className="flex max-h-[78vh] min-h-[60vh] flex-col overflow-hidden animate-fade" data-testid="ticket-detail" data-status={t.status}>
      <div className="border-b border-border p-4 sm:p-5">
        <div className="flex items-start gap-3">
          <Link to={cfg.route} className="grid size-8 shrink-0 place-items-center rounded-lg text-muted hover:bg-surface-2 lg:hidden" aria-label="بازگشت"><ArrowRight className="size-4" /></Link>
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-bold leading-8">{t.subject}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted">
              <span className="font-mono ltr">{t.code}</span>
              <Badge tone={TICKET_STATUS[t.status].tone}>{TICKET_STATUS[t.status].label}</Badge>
              {t.priority !== "normal" && <Badge tone={TICKET_PRIORITY[t.priority].tone}>اولویت {TICKET_PRIORITY[t.priority].label}</Badge>}
              <Badge tone="muted">{t.category_label}</Badge>
              <Badge tone="muted">از طرف {TICKET_SOURCE[t.source]}</Badge>
              {waiting && <Badge tone={waiting.mine ? "brand" : "muted"} dot={waiting.mine}>{waiting.label}</Badge>}
            </div>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-text-2">
          {mode === "platform" && t.organization_name && <span className="inline-flex items-center gap-1"><Building2 className="size-3.5" />{t.organization_name}</span>}
          {t.requester_name && cfg.side !== "requester" && <span className="inline-flex items-center gap-1"><UserRound className="size-3.5" />{t.requester_name}
            {t.requester_mobile && <a href={`tel:${t.requester_mobile}`} className="font-mono text-brand ltr">{t.requester_mobile}</a>}</span>}
          {t.order_tracking_code && (mode === "org"
            ? <button type="button" onClick={() => setOrderOpen(true)} className="inline-flex items-center gap-1 font-medium text-brand hover:underline" data-testid="ticket-order">
                <Package className="size-3.5" />سفارش <span className="font-mono ltr">{t.order_tracking_code}</span></button>
            : <span className="inline-flex items-center gap-1"><Package className="size-3.5" />سفارش <span className="font-mono ltr">{t.order_tracking_code}</span></span>)}
          <span className="inline-flex items-center gap-1"><Clock className="size-3.5" />{faShortDateTime(t.created_at)}</span>
        </div>
        {t.escalation_reason && (
          <p className="mt-3 flex items-start gap-2 rounded-xl bg-violet-soft/50 px-3 py-2 text-xs text-text-2"><Share2 className="mt-0.5 size-3.5 shrink-0 text-violet" />
            ارجاع به پشتیبانی پسینه: {t.escalation_reason}</p>
        )}
        {(t.can_escalate || t.can_resolve || t.can_close || t.can_manage) && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {t.can_manage && <>
              <Select value={t.priority} onChange={e => action.mutate(() => unwrap(api.PATCH("/tickets/{ticket_id}", { ...path, body: { priority: e.target.value as "normal", unassign: false } })))}
                className="h-8 w-28 text-xs" aria-label="اولویت" data-testid="ticket-priority">
                {Object.entries(TICKET_PRIORITY).map(([k, v]) => <option key={k} value={k}>اولویت {v.label}</option>)}
              </Select>
              {me.role === "org_admin" && (
                <Select value={t.assignee_id ?? ""} className="h-8 w-40 text-xs" aria-label="مسئول" data-testid="ticket-assignee"
                  onChange={e => action.mutate(() => unwrap(api.PATCH("/tickets/{ticket_id}", { ...path, body: e.target.value ? { assignee_id: Number(e.target.value), unassign: false } : { unassign: true } })))}>
                  <option value="">بدون مسئول</option>
                  {(staff.data ?? []).filter(u => u.role === "org_admin" || u.role === "warehouse_manager")
                    .map(u => <option key={u.id} value={u.id}>{u.full_name || u.username}</option>)}
                </Select>
              )}
            </>}
            <div className="ms-auto flex flex-wrap gap-2">
              {t.can_escalate && <Button size="sm" variant="secondary" icon={<Share2 className="size-3.5" />} data-testid="ticket-escalate"
                onClick={() => promptDialog({ title: "ارجاع به پشتیبانی پسینه", label: "چه کمکی از پشتیبانی پسینه لازم دارید؟", minLength: 5, maxLength: 1000,
                  multiline: true, confirmLabel: "ارجاع", text: "پشتیبانی پسینه گفت‌وگو را می‌بیند (به‌جز یادداشت‌های داخلی) و با شما — نه مستقیم با مشتری — صحبت می‌کند." })
                  .then(reason => reason && action.mutate(() => unwrap(api.POST("/tickets/{ticket_id}/escalate", { ...path, body: { reason } }))))}>
                ارجاع به پشتیبانی</Button>}
              {t.can_resolve && <Button size="sm" variant="soft" icon={<CheckCircle2 className="size-3.5" />} data-testid="ticket-resolve"
                onClick={() => action.mutate(() => mode === "platform"
                  ? unwrap(api.POST("/platform/tickets/{ticket_id}/resolve", path)) : unwrap(api.POST("/tickets/{ticket_id}/resolve", path)))}>{resolveLabel}</Button>}
              {t.can_close && <Button size="sm" variant="ghost" icon={<Lock className="size-3.5" />} data-testid="ticket-close"
                onClick={() => confirmDialog({ title: "تیکت بسته شود؟", text: "بعد از بستن، هیچ طرفی نمی‌تواند پیام جدید بفرستد.", confirmLabel: "بستن تیکت", danger: true })
                  .then(ok => ok && action.mutate(() => mode === "platform"
                    ? unwrap(api.POST("/platform/tickets/{ticket_id}/close", path)) : unwrap(api.POST("/tickets/{ticket_id}/close", path))))}>بستن</Button>}
            </div>
          </div>
        )}
      </div>
      <div className="flex min-h-0 flex-1 flex-col p-4 sm:p-5">
        <TicketThread ticket={t} attachmentUrl={mid => `${cfg.api}/${id}/messages/${mid}/attachment`}
          onSend={(body, visibility, file) => send.mutateAsync({ body, visibility, file })} sending={send.isPending} />
      </div>
      {mode === "org" && <OrderDetailModal orderId={orderOpen ? t.order_id ?? null : null} onClose={() => setOrderOpen(false)} />}
    </Card>
  );
}

function NewTicketModal({ mode, onClose, onCreated }: { mode: Mode; onClose: () => void; onCreated: (t: Ticket) => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const source = mode === "driver" ? "driver" : "org";
  const categories = TICKET_CATEGORIES[source];
  const [form, setForm] = useState({ category: "", subject: "", priority: "normal", order_id: "", body: "" });
  const [file, setFile] = useState<File | null>(null);
  const orders = useQuery({
    queryKey: ["orders", "ticket-picker"],
    queryFn: () => unwrap(api.GET("/orders/", { params: { query: { limit: 50 } } })),
    enabled: mode === "driver",
  });
  const create = useMutation({
    mutationFn: () => postForm<Ticket>("/tickets/", messageForm(form.body, {
      category: form.category, subject: mode === "org" ? form.subject : null, priority: mode === "org" ? form.priority : null, order_id: form.order_id || null,
    }, file)),
    onSuccess: t => {
      toast.success(`تیکت ${t.code} ثبت شد.`);
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      onCreated(t);
      onClose();
    },
    onError: e => toast.error(errorMessage(e)),
  });
  const recent = useMemo(() => (orders.data ?? []).slice(0, 50), [orders.data]);

  return (
    <Modal open onClose={onClose} title={mode === "org" ? "تیکت به پشتیبانی پسینه" : "تیکت جدید به سازمان"} testId="ticket-new-form"
      description={mode === "org" ? "مشکل فنی، حساب کاربری، مالی یا پیشنهاد — تیم پشتیبانی پسینه پاسخ می‌دهد." : "پاسخ سازمان را همین‌جا و با نشان کنار منو می‌بینید."}
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="new-ticket" loading={create.isPending} data-testid="ticket-submit">ثبت تیکت</Button></>}>
      <form id="new-ticket" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
        <Field label="موضوع *">
          <Select required value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value }))} data-testid="ticket-category">
            <option value="">انتخاب کنید</option>{Object.entries(categories).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
        </Field>
        {mode === "org" ? (
          <Field label="اولویت">
            <Select value={form.priority} onChange={e => setForm(f => ({ ...f, priority: e.target.value }))}>
              {Object.entries(TICKET_PRIORITY).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </Select>
          </Field>
        ) : (
          <Field label="سفارش مرتبط" hint="اختیاری">
            <Select value={form.order_id} onChange={e => setForm(f => ({ ...f, order_id: e.target.value }))} data-testid="ticket-order-pick">
              <option value="">بدون سفارش</option>
              {recent.map(o => <option key={o.id} value={o.id}>{o.tracking_code} — {o.destination_city}</option>)}
            </Select>
          </Field>
        )}
        {mode === "org" && <Field label="عنوان *" className="sm:col-span-2"><Input required minLength={3} maxLength={200} value={form.subject}
          onChange={e => setForm(f => ({ ...f, subject: e.target.value }))} placeholder="خلاصه مشکل در یک جمله" data-testid="ticket-subject" /></Field>}
        <Field label="شرح *" className="sm:col-span-2"><Textarea required minLength={5} maxLength={5000} rows={5} value={form.body}
          onChange={e => setForm(f => ({ ...f, body: e.target.value }))} placeholder="جزئیات مشکل را بنویسید" data-testid="ticket-new-body" /></Field>
        <Field label="تصویر" hint="اختیاری — PNG، JPG یا WEBP تا ۵ مگابایت" className="sm:col-span-2">
          <FileField file={file} onChange={setFile} accept="image/png,image/jpeg,image/webp" testId="ticket-new-file" placeholder="تصویری انتخاب نشده" button="انتخاب تصویر" />
        </Field>
        {mode === "org" && <p className="flex items-start gap-2 text-xs text-muted sm:col-span-2"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          برای مشکل یک مشتری، از خود تیکت مشتری «ارجاع به پشتیبانی» را بزنید تا گفت‌وگو کامل دیده شود.</p>}
      </form>
    </Modal>
  );
}

export const OrgTicketsPage = () => <TicketsWorkspace mode="org" />;
export const DriverSupportPage = () => <TicketsWorkspace mode="driver" />;
export const PlatformTicketsPage = () => <TicketsWorkspace mode="platform" />;
