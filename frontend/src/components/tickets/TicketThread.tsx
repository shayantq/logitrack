/**
 * گفت‌وگوی تیکت (مثل پیام‌رسان): پیام‌های من یک طرف، طرف مقابل طرف دیگر، رویدادهای سیستم وسط.
 * پیام بین سازمان و پشتیبانی و یادداشت داخلی با برچسب و رنگ جدا نشان داده می‌شوند تا اشتباهی به مشتری نرسد.
 */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { EyeOff, ImagePlus, Lock, Send, ShieldCheck, X } from "lucide-react";
import { authFetch } from "@/api/client";
import { faShortDateTime } from "@/lib/format";
import { type Side, type Ticket } from "@/lib/tickets";
import { Modal } from "@/ui/overlays";
import { Button, Textarea, cn } from "@/ui/primitives";

type Message = Ticket["messages"][number];

const SIDE_NAME: Record<string, string> = { platform: "پشتیبانی پسینه", org: "سازمان", requester: "", system: "سیستم" };

function useImage(url: string, auth: boolean) {
  return useQuery({
    queryKey: ["ticket-image", url],
    queryFn: async () => {
      if (!auth) return url;
      const res = await authFetch(url);
      return res.ok ? URL.createObjectURL(await res.blob()) : null;
    },
    staleTime: Infinity,
  }).data ?? null;
}

function Attachment({ url, auth }: { url: string; auth: boolean }) {
  const src = useImage(url, auth);
  const [open, setOpen] = useState(false);
  if (!src) return <div className="mt-2 h-24 w-32 animate-pulse rounded-lg bg-black/5" />;
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="mt-2 block overflow-hidden rounded-lg border border-black/5" data-testid="ticket-attachment">
        <img src={src} alt="پیوست" className="max-h-48 max-w-full object-cover transition hover:scale-[1.02]" />
      </button>
      <Modal open={open} onClose={() => setOpen(false)} title="تصویر پیوست" size="lg">
        <img src={src} alt="پیوست" className="mx-auto max-h-[70dvh] rounded-xl" />
      </Modal>
    </>
  );
}

export function TicketThread({ ticket, attachmentUrl, auth = true, onSend, sending = false }: {
  ticket: Ticket;
  attachmentUrl: (messageId: number) => string;
  auth?: boolean;
  onSend?: (body: string, visibility: string, file: File | null) => Promise<unknown>;
  sending?: boolean;
}) {
  const side = ticket.viewer_side as Side;
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [ticket.messages.length]);

  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex-1 space-y-3 overflow-y-auto px-1 py-2" data-testid="ticket-thread">
        {ticket.messages.map(m => <Bubble key={m.id} m={m} side={side} attachment={m.has_attachment ? attachmentUrl(m.id) : null} auth={auth} />)}
        <div ref={end} />
      </div>
      {onSend && ticket.reply_options.length > 0
        ? <Composer options={ticket.reply_options} onSend={onSend} sending={sending} reopen={ticket.status === "resolved"} />
        : ticket.status === "closed" && <p className="mt-3 rounded-xl bg-surface-2 px-4 py-3 text-center text-sm text-muted">این تیکت بسته شده است.</p>}
    </div>
  );
}

function Bubble({ m, side, attachment, auth }: { m: Message; side: Side; attachment: string | null; auth: boolean }) {
  if (m.author_side === "system") {
    return (
      <div className="flex justify-center" data-testid="ticket-message" data-side="system">
        <div className={cn("max-w-[90%] rounded-full px-3.5 py-1.5 text-center text-xs text-muted", m.visibility === "staff" ? "bg-violet-soft/60" : "bg-surface-2")}>
          {m.body} <span className="opacity-70">· {faShortDateTime(m.created_at)}</span>
        </div>
      </div>
    );
  }
  const mine = m.author_side === side;
  const note = m.visibility === "side";
  const staff = m.visibility === "staff";
  const who = m.author_side === "platform" ? `${m.author_name ?? ""} · ${SIDE_NAME.platform}` : m.author_name || SIDE_NAME[m.author_side] || "";
  return (
    <div className={cn("flex", mine ? "justify-start" : "justify-end")} data-testid="ticket-message" data-side={m.author_side} data-visibility={m.visibility}>
      <div className={cn("max-w-[85%] rounded-2xl px-4 py-3 text-sm shadow-sm sm:max-w-[75%]",
        note ? "border-2 border-dashed border-warning/50 bg-warning-soft/40" :
          staff ? "border border-violet/30 bg-violet-soft/50" :
            mine ? "rounded-ss-md bg-brand text-brand-ink" : "rounded-se-md border border-border bg-surface")}>
        <div className={cn("mb-1 flex flex-wrap items-center gap-x-2 text-[11px]", mine && !note && !staff ? "text-brand-ink/80" : "text-muted")}>
          <span className="font-semibold">{who}</span>
          {note && <span className="inline-flex items-center gap-1 font-semibold text-warning"><Lock className="size-3" />یادداشت داخلی</span>}
          {staff && <span className="inline-flex items-center gap-1 font-semibold text-violet"><ShieldCheck className="size-3" />بین سازمان و پشتیبانی</span>}
        </div>
        <p className="whitespace-pre-wrap leading-7">{m.body}</p>
        {attachment && <Attachment url={attachment} auth={auth} />}
        <div className={cn("mt-1 text-[10px]", mine && !note && !staff ? "text-brand-ink/70" : "text-muted")}>{faShortDateTime(m.created_at)}</div>
      </div>
    </div>
  );
}

function Composer({ options, onSend, sending, reopen }: {
  options: Ticket["reply_options"]; onSend: (body: string, visibility: string, file: File | null) => Promise<unknown>; sending: boolean; reopen: boolean;
}) {
  const [visibility, setVisibility] = useState(options[0].visibility);
  const [body, setBody] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (!options.some(o => o.visibility === visibility)) setVisibility(options[0].visibility); }, [options, visibility]);
  useEffect(() => {
    if (!file) { setPreview(null); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const pickFile = (f: File | undefined) => {
    setError(null);
    if (!f) return;
    if (!/^image\/(png|jpe?g|webp)$/.test(f.type)) return setError("فقط تصویر PNG، JPG یا WEBP.");
    if (f.size > 5 * 1024 * 1024) return setError("حجم تصویر حداکثر ۵ مگابایت است.");
    setFile(f);
  };
  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    if (!body.trim() && !file) return;
    try {
      await onSend(body.trim(), visibility, file);
      setBody("");
      setFile(null);
    } catch { /* پیام خطا را صفحه نشان می‌دهد */ }
  };
  const note = visibility === "side";
  const staff = visibility === "staff";

  return (
    <form onSubmit={submit} className={cn("mt-3 rounded-2xl border p-3 transition",
      note ? "border-dashed border-warning/60 bg-warning-soft/30" : staff ? "border-violet/40 bg-violet-soft/30" : "border-border bg-surface")} data-testid="ticket-composer">
      {options.length > 1 && (
        <div className="mb-2 flex flex-wrap gap-1.5" role="radiogroup" aria-label="نوع پیام">
          {options.map(o => (
            <button key={o.visibility} type="button" role="radio" aria-checked={visibility === o.visibility} data-visibility={o.visibility}
              onClick={() => setVisibility(o.visibility)}
              className={cn("rounded-lg px-3 py-1.5 text-xs font-medium transition",
                visibility === o.visibility ? (o.visibility === "side" ? "bg-warning text-white" : o.visibility === "staff" ? "bg-violet text-white" : "bg-brand text-brand-ink")
                  : "bg-surface-2 text-text-2 hover:text-text")}>
              {o.label}
            </button>
          ))}
        </div>
      )}
      {note && <p className="mb-2 flex items-center gap-1.5 text-xs text-warning"><EyeOff className="size-3.5" />فقط همکاران شما این یادداشت را می‌بینند.</p>}
      {staff && <p className="mb-2 flex items-center gap-1.5 text-xs text-violet"><ShieldCheck className="size-3.5" />مشتری این پیام را نمی‌بیند.</p>}
      {reopen && !note && <p className="mb-2 text-xs text-muted">با ارسال پیام، تیکت دوباره باز می‌شود.</p>}
      <Textarea rows={3} value={body} onChange={e => setBody(e.target.value)} maxLength={5000} data-testid="ticket-body"
        placeholder={note ? "یادداشت داخلی..." : "پیام خود را بنویسید..."} className="resize-none border-0 bg-transparent px-1 focus:ring-0"
        onKeyDown={e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit(); }} />
      {preview && (
        <div className="relative mt-2 inline-block">
          <img src={preview} alt="" className="h-20 rounded-lg border border-border object-cover" />
          <button type="button" onClick={() => setFile(null)} aria-label="حذف تصویر"
            className="absolute -left-2 -top-2 grid size-6 place-items-center rounded-full bg-text text-bg shadow"><X className="size-3.5" /></button>
        </div>
      )}
      {error && <p className="mt-2 text-xs text-danger">{error}</p>}
      <div className="mt-2 flex items-center justify-between gap-2">
        <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" data-testid="ticket-file"
          onChange={e => { pickFile(e.target.files?.[0]); e.target.value = ""; }} />
        <Button type="button" variant="ghost" size="sm" icon={<ImagePlus className="size-4" />} onClick={() => input.current?.click()}>تصویر</Button>
        <Button type="submit" size="sm" loading={sending} disabled={!body.trim() && !file} icon={<Send className="size-4" />} data-testid="ticket-send"
          variant={note ? "secondary" : "primary"}>{note ? "ثبت یادداشت" : "ارسال"}</Button>
      </div>
    </form>
  );
}
