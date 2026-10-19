/** «مشکلی در این سفارش دارید؟» — درخواست پشتیبانی مشتری از صفحه پیگیری (پس از تأیید ۴ رقم آخر موبایل) */
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { ImagePlus, LifeBuoy, X } from "lucide-react";
import { errorMessage } from "@/api/client";
import { messageForm, postForm, TICKET_CATEGORIES, type Ticket } from "@/lib/tickets";
import { Modal } from "@/ui/overlays";
import { Button, Field, Textarea, cn } from "@/ui/primitives";

export function SupportRequest({ code, phone }: { code: string; phone: string }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState("");
  const [body, setBody] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => postForm<Ticket & { access_token: string }>(`/public/track/${encodeURIComponent(code)}/tickets`,
      messageForm(body, { phone, category }, file), false),
    onSuccess: t => navigate(`/support/${t.access_token}`, { state: { created: true } }),
    onError: e => setError(errorMessage(e)),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!category) return setError("موضوع مشکل را انتخاب کنید.");
    create.mutate();
  };

  return (
    <>
      <div className="card flex flex-wrap items-center gap-4 p-5" data-testid="track-support">
        <span className="grid size-11 place-items-center rounded-2xl bg-brand-soft text-brand"><LifeBuoy className="size-5" /></span>
        <div className="min-w-48 flex-1">
          <div className="font-bold">مشکلی در این سفارش دارید؟</div>
          <p className="mt-0.5 text-sm text-muted">تأخیر، آسیب‌دیدگی کالا یا هر موضوع دیگر را برای فروشنده بفرستید و پاسخ را دنبال کنید.</p>
        </div>
        <Button variant="secondary" onClick={() => setOpen(true)} data-testid="track-support-open">ثبت درخواست پشتیبانی</Button>
      </div>

      <Modal open={open} onClose={() => setOpen(false)} title="درخواست پشتیبانی" description={`سفارش ${code}`} testId="support-form"
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>انصراف</Button>
          <Button type="submit" form="support-request" loading={create.isPending} data-testid="support-submit">ارسال درخواست</Button></>}>
        <form id="support-request" onSubmit={submit} className="space-y-4">
          <div>
            <div className="mb-2 text-sm font-medium text-text-2">موضوع *</div>
            <div className="flex flex-wrap gap-2" role="radiogroup" data-testid="support-category">
              {Object.entries(TICKET_CATEGORIES.customer).map(([k, v]) => (
                <button key={k} type="button" role="radio" aria-checked={category === k} data-value={k} onClick={() => setCategory(k)}
                  className={cn("rounded-xl border px-3.5 py-2 text-sm transition", category === k ? "border-brand bg-brand text-brand-ink" : "border-border bg-surface text-text-2 hover:border-border-strong")}>
                  {v}
                </button>
              ))}
            </div>
          </div>
          <Field label="توضیح *"><Textarea required minLength={5} maxLength={3000} rows={4} value={body} onChange={e => setBody(e.target.value)}
            placeholder="مشکل را کامل توضیح دهید" data-testid="support-body" /></Field>
          <div>
            <label className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-dashed border-border-strong px-3.5 py-2 text-sm text-text-2 hover:border-brand hover:text-brand">
              <ImagePlus className="size-4" />{file ? "تعویض تصویر" : "افزودن تصویر (مثلاً کالای آسیب‌دیده)"}
              <input type="file" accept="image/png,image/jpeg,image/webp" className="hidden" data-testid="support-file"
                onChange={e => { const f = e.target.files?.[0]; if (f && f.size > 5 * 1024 * 1024) setError("حجم تصویر حداکثر ۵ مگابایت است."); else setFile(f ?? null); }} />
            </label>
            {file && <span className="ms-2 inline-flex items-center gap-1 text-xs text-muted">{file.name}
              <button type="button" onClick={() => setFile(null)} aria-label="حذف تصویر"><X className="size-3.5" /></button></span>}
          </div>
          {error && <p className="rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger" data-testid="support-error">{error}</p>}
          <p className="text-xs leading-6 text-muted">پس از ثبت، یک لینک اختصاصی می‌گیرید که با آن پاسخ فروشنده را می‌بینید و گفت‌وگو را ادامه می‌دهید؛ آن را نگه دارید.</p>
        </form>
      </Modal>
    </>
  );
}
