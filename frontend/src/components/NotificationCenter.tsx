/**
 * مرکز اعلان‌ها (زنگوله سربرگ پنل)
 * هر اعلان: آیکن و رنگ بر اساس نوع و شدت، عنوان، توضیح، جزئیات کوتاه، زمان نسبی، دکمه بستن (✕)
 * کلیک روی اعلان ← خوانده‌شده + رفتن به همان مورد در همان بخش (مثلاً کالای رو‌به‌اتمام در «انبار و کالاها»)
 * خواندن و بستن برای هر کاربر جداست (سرور).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BadgeCheck, Bell, BellOff, CalendarClock, CheckCheck, ChevronLeft, ClipboardCheck, IdCard, MessageSquareText,
  PackageX, Star, TimerOff, Trash2, TrendingDown, Truck, X, XCircle, type LucideIcon,
} from "lucide-react";
import { api, unwrap, type Schemas } from "@/api/client";
import { timeAgo } from "@/pages/users/shared";
import { faShortDateTime } from "@/lib/format";
import { Button, cn, toneClass, type Tone } from "@/ui/primitives";

type Note = Schemas["NotificationResponse"];
type NoteList = Schemas["NotificationList"];
const KEY = ["notifications"];

const KIND_ICON: Record<string, LucideIcon> = {
  low_stock: TrendingDown, out_of_stock: PackageX, order_failed: XCircle, order_expired: TimerOff, order_assigned: Truck,
  ticket_new: MessageSquareText, ticket_reply: MessageSquareText, stocktake_review: ClipboardCheck,
  stocktake_recount: ClipboardCheck, stocktake_approved: ClipboardCheck, driver_application: IdCard,
  driver_request: CalendarClock, application_result: BadgeCheck, request_result: BadgeCheck, low_rating: Star,
};
const CATEGORIES: { id: string; label: string; tone: Tone }[] = [
  { id: "inventory", label: "موجودی", tone: "info" },
  { id: "orders", label: "سفارش‌ها", tone: "brand" },
  { id: "tickets", label: "تیکت‌ها", tone: "violet" },
  { id: "stocktakes", label: "انبارگردانی", tone: "pink" },
  { id: "drivers", label: "رانندگان", tone: "orange" },
];
const CATEGORY_TONE: Record<string, Tone> = Object.fromEntries(CATEGORIES.map(c => [c.id, c.tone]));

/** رنگ آیکن: هشدارها رنگ شدت را می‌گیرند، اعلان‌های معمولی رنگ دسته خودشان را */
function toneOf(n: Note): Tone {
  if (n.severity === "danger" || n.severity === "warning" || n.severity === "success") return n.severity;
  return CATEGORY_TONE[n.category] ?? "brand";
}

export function NotificationCenter() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [category, setCategory] = useState("");
  const [leaving, setLeaving] = useState<Set<number>>(new Set());
  const root = useRef<HTMLDivElement>(null);

  const { data } = useQuery({ queryKey: KEY, queryFn: () => unwrap(api.GET("/notifications/")), refetchInterval: 30_000 });
  const items = data?.items ?? [];
  const unread = data?.unread_count ?? 0;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("pointerdown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  /** تغییر فوری فهرست در کش (بدون صبر برای سرور) و هم‌گام‌سازی بعد از پاسخ */
  function patch(fn: (list: NoteList) => NoteList) {
    queryClient.setQueryData<NoteList>(KEY, old => (old ? fn(old) : old));
  }
  const sync = { onSettled: () => queryClient.invalidateQueries({ queryKey: KEY }) };
  const read = useMutation({
    mutationFn: (id: number) => unwrap(api.PUT("/notifications/{notification_id}/read", { params: { path: { notification_id: id } } })),
    onMutate: id => patch(l => ({ unread_count: Math.max(0, l.unread_count - (l.items.some(i => i.id === id && !i.is_read) ? 1 : 0)),
      items: l.items.map(i => (i.id === id ? { ...i, is_read: true } : i)) })),
    ...sync,
  });
  const dismiss = useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE("/notifications/{notification_id}", { params: { path: { notification_id: id } } })),
    onMutate: id => patch(l => ({ unread_count: Math.max(0, l.unread_count - (l.items.some(i => i.id === id && !i.is_read) ? 1 : 0)),
      items: l.items.filter(i => i.id !== id) })),
    ...sync,
  });
  const readAll = useMutation({
    mutationFn: () => unwrap(api.PUT("/notifications/read-all")),
    onMutate: () => patch(l => ({ unread_count: 0, items: l.items.map(i => ({ ...i, is_read: true })) })),
    ...sync,
  });
  const clearAll = useMutation({
    mutationFn: () => unwrap(api.DELETE("/notifications/")),
    onMutate: () => patch(() => ({ unread_count: 0, items: [] })),
    ...sync,
  });

  function remove(id: number) {
    setLeaving(s => new Set(s).add(id));
    window.setTimeout(() => {
      dismiss.mutate(id);
      setLeaving(s => { const next = new Set(s); next.delete(id); return next; });
    }, 220);
  }
  function openNote(n: Note) {
    if (!n.is_read) read.mutate(n.id);
    setOpen(false);
    if (n.link) navigate(n.link);
  }

  const present = useMemo(() => new Set(items.map(i => i.category)), [items]);
  const visible = items.filter(i => (!unreadOnly || !i.is_read) && (!category || i.category === category));

  return (
    <div className="relative" ref={root}>
      <Button variant="ghost" size="icon" className="relative" aria-label="اعلان‌ها" aria-expanded={open} data-testid="notifications-bell"
        onClick={() => setOpen(o => !o)}>
        <Bell className={cn("size-[18px]", unread > 0 && "origin-top animate-[bell_1.2s_ease-in-out_1]")} />
        {unread > 0 && <span className="absolute -top-0.5 -left-0.5 grid min-w-5 place-items-center rounded-full bg-danger px-1 text-[10px] font-bold text-white ring-2 ring-surface"
          data-testid="notifications-count">{unread > 99 ? "۹۹+" : unread.toLocaleString("fa-IR")}</span>}
      </Button>

      {open && (
        <div role="dialog" aria-label="اعلان‌ها" data-testid="notifications-panel"
          className="fixed inset-x-3 top-[68px] z-50 flex max-h-[min(640px,calc(100svh-84px))] flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-float animate-[rise_.18s_ease-out] sm:absolute sm:inset-x-auto sm:end-0 sm:top-full sm:mt-2 sm:w-[420px]">
          <div className="flex items-center gap-2 border-b border-border px-4 py-3">
            <div className="min-w-0 flex-1">
              <div className="font-bold">اعلان‌ها</div>
              <div className="text-xs text-muted">{unread > 0 ? `${unread.toLocaleString("fa-IR")} اعلان خوانده‌نشده` : "همه اعلان‌ها را دیده‌اید"}</div>
            </div>
            <Button variant="ghost" size="sm" disabled={unread === 0} onClick={() => readAll.mutate()} icon={<CheckCheck className="size-4" />}
              data-testid="notifications-read-all">خواندن همه</Button>
            <Button variant="ghost" size="sm" disabled={items.length === 0} onClick={() => clearAll.mutate()} icon={<Trash2 className="size-4" />}
              className="hover:text-danger" data-testid="notifications-clear">پاک کردن</Button>
          </div>

          <div className="flex flex-wrap items-center gap-1.5 border-b border-border px-4 py-2.5">
            <div className="me-1 flex rounded-lg bg-surface-2 p-0.5 text-xs" role="tablist">
              {[false, true].map(u => (
                <button key={String(u)} role="tab" aria-selected={unreadOnly === u} onClick={() => setUnreadOnly(u)}
                  className={cn("rounded-md px-2.5 py-1 font-medium transition", unreadOnly === u ? "bg-surface text-text shadow-sm" : "text-muted hover:text-text")}>
                  {u ? "خوانده‌نشده" : "همه"}
                </button>
              ))}
            </div>
            {CATEGORIES.filter(c => present.has(c.id)).map(c => (
              <button key={c.id} onClick={() => setCategory(cur => (cur === c.id ? "" : c.id))} data-testid={`notifications-filter-${c.id}`}
                className={cn("rounded-full px-2.5 py-1 text-xs font-medium transition",
                  category === c.id ? toneClass(c.tone) : "text-muted hover:bg-surface-2 hover:text-text")}>
                {c.label}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto overscroll-contain" data-testid="notifications-list">
            {visible.length === 0 ? (
              <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
                <span className="grid size-11 place-items-center rounded-2xl bg-surface-2 text-muted"><BellOff className="size-5" /></span>
                <div className="text-sm font-medium">{items.length === 0 ? "اعلانی ندارید" : "اعلانی با این فیلتر نیست"}</div>
                <div className="text-xs text-muted">کمبود موجودی، سفارش ناموفق، تیکت و درخواست‌های تازه اینجا نمایش داده می‌شوند.</div>
              </div>
            ) : visible.map(n => (
              <NoteRow key={n.id} n={n} leaving={leaving.has(n.id)} onOpen={() => openNote(n)} onDismiss={() => remove(n.id)} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function NoteRow({ n, leaving, onOpen, onDismiss }: { n: Note; leaving: boolean; onOpen: () => void; onDismiss: () => void }) {
  const Icon = KIND_ICON[n.kind] ?? Bell;
  const tone = toneOf(n);
  return (
    <div className={cn("grid transition-[grid-template-rows,opacity] duration-200 ease-out", leaving ? "grid-rows-[0fr] opacity-0" : "grid-rows-[1fr]")}
      data-testid="notification-item" data-kind={n.kind} data-read={n.is_read ? "1" : "0"}>
      <div className="overflow-hidden">
        <div className={cn("group relative flex gap-3 border-b border-border px-4 py-3 transition hover:bg-surface-2", !n.is_read && "bg-brand-soft/40")}>
          {!n.is_read && <span className="absolute inset-y-3 right-0 w-[3px] rounded-l-full bg-brand" />}
          <span className={cn("mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl", toneClass(tone))}><Icon className="size-[18px]" /></span>
          <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-start outline-none after:absolute after:inset-0 focus-visible:after:rounded-lg focus-visible:after:ring-2 focus-visible:after:ring-brand"
            data-testid="notification-open">
            <div className="flex items-center gap-1.5 pe-6">
              <span className={cn("truncate text-sm", n.is_read ? "font-medium text-text-2" : "font-bold text-text")}>{n.title}</span>
              {!n.is_read && <span className="size-1.5 shrink-0 rounded-full bg-brand" aria-label="خوانده‌نشده" />}
            </div>
            <p className="mt-0.5 line-clamp-2 text-xs leading-5 text-text-2">{n.message}</p>
            {n.details.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {n.details.slice(0, 5).map(d => (
                  <span key={d.label} className="max-w-full truncate rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted">
                    {d.label}: <span className="font-medium text-text-2">{d.value}</span>
                  </span>
                ))}
              </div>
            )}
            <div className="mt-1.5 flex items-center gap-2 text-[11px] text-muted">
              <span title={faShortDateTime(n.created_at)}>{timeAgo(n.created_at)}</span>
              {n.link && <span className="ms-auto inline-flex items-center gap-0.5 font-medium text-brand opacity-0 transition group-hover:opacity-100">مشاهده<ChevronLeft className="size-3" /></span>}
            </div>
          </button>
          <button type="button" onClick={onDismiss} aria-label="حذف اعلان" data-testid="notification-dismiss"
            className="absolute top-2.5 left-2.5 z-10 grid size-7 place-items-center rounded-lg text-muted transition hover:bg-danger-soft hover:text-danger focus-visible:outline-2 focus-visible:outline-brand">
            <X className="size-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
