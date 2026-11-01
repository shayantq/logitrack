/**
 * ثبت نتیجه تحویل در صفحه راننده. فیلدها فقط بعد از انتخاب نتیجه می‌آیند:
 * تحویل موفق: تحویل‌گیرنده، نقش، عکس اختیاری و یادداشت کمبود یا آسیب.
 * ناموفق: دلیل (الزامی)، یادداشت و پیشنهاد زمان تلاش بعدی.
 */
import { useState, type FormEvent } from "react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useToast } from "@/components/Toast";
import { compressImage, uploadWithProgress } from "@/lib/driver";
import { Modal } from "@/ui/overlays";
import { Button, Field, Input, Select, Textarea } from "@/ui/primitives";

type Order = Schemas["OrderResponse"];
export type Outcome = "delivered" | "failed";

const RECIPIENT_ROLES = [["self", "خود گیرنده"], ["family", "خانواده"], ["colleague", "همکار"], ["guard", "نگهبان"], ["other", "دیگر"]] as const;
const FAILURE_REASONS = [
  ["recipient_absent", "گیرنده در دسترس نبود"], ["wrong_address", "نشانی نادرست"], ["refused", "گیرنده تحویل نگرفت"],
  ["damaged", "کالا آسیب دیده بود"], ["access_issue", "دسترسی به محل ممکن نبود"], ["vehicle_issue", "مشکل خودرو"], ["other", "سایر"],
] as const;
type Role = (typeof RECIPIENT_ROLES)[number][0];
type Reason = (typeof FAILURE_REASONS)[number][0];

export function DeliveryOutcomeModal({ order, outcome, onClose, onSaved }: { order: Order; outcome: Outcome | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [recipient, setRecipient] = useState(order.recipient_name ?? "");
  const [role, setRole] = useState<Role>("self");
  const [issue, setIssue] = useState("");
  const [reason, setReason] = useState<Reason | "">("");
  const [note, setNote] = useState("");
  const [nextAt, setNextAt] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);
  const [method, setMethod] = useState("");
  const [methodNote, setMethodNote] = useState("");
  const [partial, setPartial] = useState(false);
  const [lines, setLines] = useState<Record<number, { quantity: string; reason: string }>>({});
  const [busy, setBusy] = useState(false);
  const delivered = outcome === "delivered";

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      const saved = await unwrap(api.PUT("/orders/{order_id}/status", {
        params: { path: { order_id: order.id } },
        body: delivered
          ? { order_status: "delivered", recipient_name: recipient || null, recipient_role: role, exception_note: issue || null, note: null,
              delivery_lines: partial ? Object.entries(lines).filter(([id, l]) => l.quantity !== "" && Number(l.quantity) < (order.items.find(i => i.id === Number(id))?.quantity ?? 0))
                .map(([id, l]) => ({ item_id: Number(id), delivered_quantity: Number(l.quantity), reason: l.reason })) : null }
          : { order_status: "failed", failure_reason: reason as Reason, note: note || null, next_attempt_at: nextAt ? new Date(nextAt).toISOString() : null },
      }));
      if (delivered && photo) {
        const blob = await compressImage(photo);
        const type = issue ? "damage" : "delivery";
        // وضعیت ثبت شده؛ شکست آپلود عکس نباید راننده را برای ثبت دوباره نگه دارد
        await uploadWithProgress(`/orders/${order.id}/attempts/${saved.delivery_attempt_count}/photo?photo_type=${type}`, blob, photo.name, () => {}, { delivery_method: method, ...(method === "other" ? { method_note: methodNote } : {}) })
          .catch(e => toast.error(`تحویل ثبت شد ولی عکس بارگذاری نشد: ${errorMessage(e)}`));
      }
      toast.success(delivered ? "تحویل ثبت شد." : "تحویل ناموفق ثبت شد؛ سازمان درباره ادامه کار تصمیم می‌گیرد.");
      onSaved();
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={!!outcome} onClose={onClose} title={delivered ? "ثبت تحویل" : "ثبت تحویل ناموفق"} testId="outcome-modal"
      footer={<>
        <Button variant="ghost" onClick={onClose}>انصراف</Button>
        <Button type="submit" form="outcome-form" loading={busy} variant={delivered ? "primary" : "danger"} disabled={!delivered && !reason} data-testid="outcome-save">
          {delivered ? "ثبت تحویل" : "ثبت ناموفق"}
        </Button>
      </>}>
      <form id="outcome-form" className="space-y-4" onSubmit={submit}>
        {delivered ? <>
          <Field label="تحویل‌گیرنده"><Input value={recipient} onChange={e => setRecipient(e.target.value)} maxLength={150} data-testid="outcome-recipient" /></Field>
          <Field label="نسبت با گیرنده">
            <Select value={role} onChange={e => setRole(e.target.value as Role)} data-testid="outcome-role">
              {RECIPIENT_ROLES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </Field>
          <Field label="عکس مدرک (اختیاری)">
            <Input type="file" accept="image/*" capture="environment" onChange={e => setPhoto(e.target.files?.[0] ?? null)} data-testid="outcome-photo" />
          </Field>
          {photo && <Field label="روش تحویل">
            <Select required value={method} onChange={e => setMethod(e.target.value)} data-testid="outcome-method">
              <option value="">انتخاب کنید</option>
              <option value="handed_to_recipient">تحویل به گیرنده</option>
              <option value="left_at_door">گذاشتن پشت در</option>
              <option value="other">سایر</option>
            </Select>
          </Field>}
          {photo && method === "other" && <Field label="توضیح روش تحویل"><Input required minLength={3} maxLength={300} value={methodNote} onChange={e => setMethodNote(e.target.value)} data-testid="outcome-method-note" /></Field>}
          <Field label="کمبود یا آسیب (اختیاری)"><Textarea rows={2} value={issue} onChange={e => setIssue(e.target.value)} maxLength={500} data-testid="outcome-issue" /></Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="size-4 accent-[var(--brand)]" checked={partial} onChange={e => setPartial(e.target.checked)} data-testid="outcome-partial" />
            همه اقلام تحویل نشد
          </label>
          {partial && order.items.map(item => {
            const line = lines[item.id] ?? { quantity: String(item.quantity), reason: "" };
            const change = (patch: Partial<typeof line>) => setLines(all => ({ ...all, [item.id]: { ...line, ...patch } }));
            return (
              <div key={item.id} className="grid gap-2 rounded-xl border border-border p-3 sm:grid-cols-2" data-testid="outcome-line">
                <Field label={`${item.product_name}: تحویل‌شده از ${item.quantity}`}>
                  <Input type="number" min={0} max={item.quantity} value={line.quantity} onChange={e => change({ quantity: e.target.value })} data-testid="outcome-line-quantity" />
                </Field>
                {Number(line.quantity) < item.quantity && <Field label="دلیل"><Input value={line.reason} minLength={2} required maxLength={300} onChange={e => change({ reason: e.target.value })} data-testid="outcome-line-reason" /></Field>}
              </div>
            );
          })}
        </> : <>
          <Field label="دلیل">
            <Select value={reason} onChange={e => setReason(e.target.value as Reason)} required data-testid="outcome-reason">
              <option value="">انتخاب دلیل...</option>
              {FAILURE_REASONS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </Field>
          <Field label="توضیح (اختیاری)"><Textarea rows={2} value={note} onChange={e => setNote(e.target.value)} maxLength={500} data-testid="outcome-note" /></Field>
          <Field label="زمان پیشنهادی برای تلاش بعدی (اختیاری)"><Input type="datetime-local" value={nextAt} onChange={e => setNextAt(e.target.value)} data-testid="outcome-next" /></Field>
        </>}
      </form>
    </Modal>
  );
}
