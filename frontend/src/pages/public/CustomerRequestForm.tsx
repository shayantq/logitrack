/**
 * درخواست مشتری از صفحه رهگیری، فقط پس از ورود ۴ رقم موبایل. چیزی مستقیم تغییر نمی‌کند و سازمان تصمیم می‌گیرد.
 * گزینه‌ها با مرحله سفارش عوض می‌شوند؛ پس از تحویل فقط مرجوعی و اختلاف می‌ماند.
 */
import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Printer } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { faNumber, faShortDateTime } from "@/lib/format";
import { Badge, Button, Field, Input, Textarea } from "@/ui/primitives";

type Track = Schemas["TrackResponse"];
type Kind = Schemas["CustomerRequestIn"]["kind"];

const LABELS: Record<Kind, string> = { address_change: "تغییر نشانی", cancel: "لغو سفارش", return: "مرجوعی", dispute: "کالا را تحویل نگرفته‌ام یا ناقص است" };

export function CustomerRequestForm({ track, phone }: { track: Track; phone: string }) {
  const queryClient = useQueryClient();
  const delivered = track.status === "delivered";
  const early = ["pending", "assigned", "picking_up"].includes(track.status);
  const kinds: Kind[] = delivered ? ["return", "dispute"] : early ? ["address_change", "cancel"] : [];
  const [kind, setKind] = useState<Kind | null>(null);
  const [note, setNote] = useState("");
  const [province, setProvince] = useState(track.destination_province ?? "");
  const [city, setCity] = useState(track.destination_city ?? "");
  const [address, setAddress] = useState("");
  const [quantities, setQuantities] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const details = track.details;
  const send = useMutation({
    mutationFn: () => unwrap(api.POST("/public/track/{code}/requests", {
      params: { path: { code: track.tracking_code } },
      body: {
        phone, kind: kind as Kind, note: note || null,
        address: kind === "address_change" ? { destination_province: province, destination_city: city, destination_address: address } : null,
        items: kind === "return" ? Object.entries(quantities).filter(([, q]) => Number(q) > 0).map(([id, q]) => ({ product_id: Number(id), quantity: Number(q) })) : null,
      },
    })),
    onSuccess: () => {
      setKind(null); setNote(""); setDone(true); setError(null);
      queryClient.invalidateQueries({ queryKey: ["track"] });
    },
    onError: e => setError(errorMessage(e)),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); setError(null); send.mutate(); };

  return (
    <div className="card space-y-4 p-6 print:hidden" data-testid="customer-request-form">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-bold">درخواست از فروشنده</h2>
        {delivered && <Button size="sm" variant="ghost" icon={<Printer className="size-4" />} onClick={() => window.print()} data-testid="track-print">چاپ رسید</Button>}
      </div>
      {!!details?.requests?.length && (
        <ul className="divide-y divide-border rounded-xl border border-border text-sm" data-testid="my-requests">
          {details.requests.map(r => (
            <li key={r.id} className="flex flex-wrap items-center gap-2 px-4 py-2.5">
              <span className="font-medium">{r.kind_label}</span><Badge tone={r.status === "pending" ? "warning" : r.status === "approved" ? "success" : "muted"}>{r.status_label}</Badge>
              <span className="text-xs text-muted">{faShortDateTime(r.created_at)}</span>
              {r.decision_note && <span className="w-full text-text-2">{r.decision_note}</span>}
            </li>
          ))}
        </ul>
      )}
      {done && <p className="rounded-xl bg-success-soft px-4 py-3 text-sm text-success" data-testid="request-sent">درخواست ثبت شد. نتیجه را همین‌جا می‌بینید.</p>}
      {!kinds.length ? <p className="text-sm text-muted">در این مرحله از سفارش درخواستی ممکن نیست. اگر مشکلی هست از پشتیبانی کمک بگیرید.</p> : (
        <>
          <div className="flex flex-wrap gap-2">
            {kinds.map(k => <Button key={k} size="sm" variant={kind === k ? "primary" : "secondary"} onClick={() => { setKind(k); setDone(false); }} data-testid={`request-${k}`}>{LABELS[k]}</Button>)}
          </div>
          {kind && (
            <form className="space-y-3" onSubmit={submit}>
              {kind === "address_change" && <div className="grid gap-3 sm:grid-cols-2">
                <Field label="استان"><Input value={province} required onChange={e => setProvince(e.target.value)} data-testid="request-province" /></Field>
                <Field label="شهر"><Input value={city} required onChange={e => setCity(e.target.value)} data-testid="request-city" /></Field>
                <Field label="نشانی کامل" className="sm:col-span-2"><Textarea rows={2} value={address} required minLength={5} maxLength={500} onChange={e => setAddress(e.target.value)} data-testid="request-address" /></Field>
              </div>}
              {kind === "return" && details?.items.map(i => i.id != null && (
                <Field key={i.id} label={`${i.name} (تا ${faNumber(i.delivered_quantity ?? i.quantity)} عدد)`}>
                  <Input type="number" min={0} max={i.delivered_quantity ?? i.quantity} value={quantities[i.id] ?? ""} data-testid="request-quantity"
                    onChange={e => setQuantities(q => ({ ...q, [i.id as number]: e.target.value }))} />
                </Field>
              ))}
              <Field label="توضیح"><Textarea rows={2} value={note} maxLength={500} onChange={e => setNote(e.target.value)} data-testid="request-note" /></Field>
              {error && <p className="rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger" data-testid="request-error">{error}</p>}
              <Button type="submit" loading={send.isPending} data-testid="request-submit">ثبت درخواست</Button>
            </form>
          )}
        </>
      )}
    </div>
  );
}
