/** درخواست خرید و تأیید آن. پرداخت و رسید خودکار ندارد؛ مبلغ برآورد از آخرین بهای ثبت‌شده است. */
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, ShoppingCart, X } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { UpdatedAt } from "@/components/UpdatedAt";
import { useProducts } from "@/hooks/data";
import { faNumber, faShortDateTime } from "@/lib/format";
import { faMoneyShort } from "@/pages/reports/period";
import { promptDialog } from "@/ui/dialogs";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, SegmentedControl, Select, Skeleton } from "@/ui/primitives";
import { WarehousePicker, useWarehouseChoice } from "./shared";

type Request = Schemas["PurchaseRequestOut"];
type Filter = "pending" | "approved" | "rejected" | "canceled";
const TONE: Record<string, "warning" | "success" | "danger" | "muted"> = { pending: "warning", approved: "success", rejected: "danger", canceled: "muted" };

export default function PurchaseRequestsPage() {
  const me = useMe();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Filter>("pending");
  const [creating, setCreating] = useState(false);
  const q = useQuery({
    queryKey: ["purchase-requests", status],
    queryFn: () => unwrap(api.GET("/purchase-requests/", { params: { query: { status } } })),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["purchase-requests"] });
  const decide = useMutation({
    mutationFn: (args: { id: number; approve: boolean; note: string | null }) => unwrap(api.POST("/purchase-requests/{request_id}/decide", {
      params: { path: { request_id: args.id } }, body: { approve: args.approve, note: args.note } })),
    onSuccess: () => { toast.success("تصمیم ثبت شد."); void refresh(); },
    onError: e => { toast.error(errorMessage(e)); void refresh(); },
  });
  const cancel = useMutation({
    mutationFn: (id: number) => unwrap(api.POST("/purchase-requests/{request_id}/cancel", { params: { path: { request_id: id } }, body: { note: null } })),
    onSuccess: () => { toast.success("درخواست لغو شد."); void refresh(); },
    onError: e => { toast.error(errorMessage(e)); void refresh(); },
  });

  return (
    <div data-testid="purchase-page">
      <PageHeader eyebrow="انبار" title="درخواست خرید" subtitle="ثبت و تصمیم؛ پرداخت و رسید خودکار در این صفحه نیست"
        actions={<Button icon={<Plus className="size-4" />} onClick={() => setCreating(true)} data-testid="purchase-new">درخواست تازه</Button>} />
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <SegmentedControl value={status} onChange={setStatus} options={[{ value: "pending", label: "منتظر تصمیم" }, { value: "approved", label: "تأیید" }, { value: "rejected", label: "رد" }, { value: "canceled", label: "لغو" }]} />
        <UpdatedAt at={q.dataUpdatedAt} />
      </div>
      {q.isLoading ? <Skeleton className="h-40 rounded-2xl" /> : q.error ? <ErrorState error={q.error} onRetry={q.refetch} /> : !q.data?.length ? (
        <Card><EmptyState icon={<ShoppingCart className="size-5" />} title="درخواستی در این وضعیت نیست" /></Card>
      ) : (
        <div className="space-y-4">
          {q.data.map(r => (
            <RequestCard key={r.id} request={r} canDecide={me.role === "org_admin" && r.requested_by_id !== me.id && r.status === "pending"}
              canCancel={r.status === "pending" && (me.role === "org_admin" || r.requested_by_id === me.id)}
              onApprove={() => decide.mutate({ id: r.id, approve: true, note: null })}
              onReject={() => promptDialog({ title: `رد ${r.code}`, label: "دلیل", required: true, minLength: 3, maxLength: 500 }).then(note => note && decide.mutate({ id: r.id, approve: false, note }))}
              onCancel={() => cancel.mutate(r.id)} />
          ))}
        </div>
      )}
      {creating && <NewRequestModal onClose={() => setCreating(false)} onCreated={() => { setCreating(false); setStatus("pending"); void refresh(); }} />}
    </div>
  );
}

function RequestCard({ request: r, canDecide, canCancel, onApprove, onReject, onCancel }: {
  request: Request; canDecide: boolean; canCancel: boolean; onApprove: () => void; onReject: () => void; onCancel: () => void;
}) {
  return (
    <Card className="p-4" data-testid="purchase-row" data-code={r.code} data-status={r.status}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-bold ltr">{r.code}</span>
        <Badge tone={TONE[r.status] ?? "muted"} dot>{r.status_label}</Badge>
        <span className="text-xs text-muted">{r.warehouse_name} · {r.requested_by ?? "—"} · {faShortDateTime(r.created_at)}</span>
      </div>
      <ul className="mt-3 space-y-1 text-sm">
        {r.lines.map(line => <li key={`${line.product_id}-${line.product_name}`} className="flex justify-between gap-3"><span className="truncate">{line.product_name}</span><span className="tnum">{faNumber(line.quantity)}</span></li>)}
      </ul>
      {r.estimated_total !== null && r.estimated_total !== undefined && (
        <p className="mt-2 text-xs text-muted">برآورد از آخرین بهای ثبت‌شده: {faMoneyShort(r.estimated_total)} ریال{r.estimate_complete ? "" : " (بعضی کالاها بها ندارند)"}</p>
      )}
      {r.note && <p className="mt-2 text-sm text-text-2">{r.note}</p>}
      <ul className="mt-3 space-y-1 border-t border-border pt-2 text-xs text-muted" data-testid="purchase-history">
        {r.events.map((e, i) => <li key={i}>{e.action_label} · {e.actor ?? "—"} · {faShortDateTime(e.at)}{e.note && ` · ${e.note}`}</li>)}
      </ul>
      {(canDecide || canCancel) && (
        <div className="mt-3 flex flex-wrap gap-2">
          {canDecide && <Button size="sm" onClick={onApprove} data-testid="purchase-approve">تأیید</Button>}
          {canDecide && <Button size="sm" variant="secondary" onClick={onReject} data-testid="purchase-reject">رد</Button>}
          {canCancel && <Button size="sm" variant="ghost" icon={<X className="size-4" />} onClick={onCancel} data-testid="purchase-cancel">لغو</Button>}
        </div>
      )}
    </Card>
  );
}

function NewRequestModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const toast = useToast();
  const choice = useWarehouseChoice();
  const { data: products = [] } = useProducts();
  const [product, setProduct] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/purchase-requests/", { body: { warehouse_id: choice.value ? Number(choice.value) : null, note: note || null, lines: [{ product_id: Number(product), quantity: Number(quantity) }] } })),
    onSuccess: () => { toast.success("درخواست ثبت شد."); onCreated(); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <Modal open onClose={onClose} title="درخواست خرید تازه" testId="purchase-modal"
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="purchase-form" loading={save.isPending} data-testid="purchase-save">ثبت</Button></>}>
      <form id="purchase-form" className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        <Field label="انبار"><WarehousePicker choice={choice} /></Field>
        <Field label="کالا">
          <Select required searchable value={product} onChange={e => setProduct(e.target.value)} data-testid="purchase-product">
            <option value="">انتخاب کنید</option>
            {products.map(p => <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>)}
          </Select>
        </Field>
        <Field label="تعداد"><Input required type="number" min={1} value={quantity} onChange={e => setQuantity(e.target.value)} data-testid="purchase-qty" /></Field>
        <Field label="توضیح"><Input maxLength={500} value={note} onChange={e => setNote(e.target.value)} /></Field>
      </form>
    </Modal>
  );
}
