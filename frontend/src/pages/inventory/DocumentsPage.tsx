/**
 * اسناد انبار: رسید، حواله، اصلاحیه، انتقال، تغییر وضعیت و … — هر تغییر موجودی یک سند قطعی است.
 * سند قطعی ویرایش یا حذف نمی‌شود؛ اشتباه با «سند برگشت» خنثی می‌شود و هر دو سند در سابقه می‌مانند.
 */
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileStack, RotateCcw, Search } from "lucide-react";
import { api, errorMessage, newIdempotencyKey, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { MovementBadge } from "@/components/StatusBadges";
import { useToast } from "@/components/Toast";
import { useWarehouses } from "@/hooks/data";
import { DOCUMENT_STATUS, DOCUMENT_TYPES, STOCK_STATUS, type StockStatus } from "@/lib/labels";
import { faDateTime, faNumber } from "@/lib/format";
import { promptDialog } from "@/ui/dialogs";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Card, EmptyState, ErrorState, Input, PageHeader, Select, Table, TableSkeleton } from "@/ui/primitives";

type Doc = Schemas["StockDocumentOut"];

export function DocTypeBadge({ type }: { type: string }) {
  const t = DOCUMENT_TYPES[type];
  return <Badge tone={t?.tone ?? "muted"}>{t?.label ?? type}</Badge>;
}

export function DocStatusBadge({ status }: { status: string }) {
  const s = DOCUMENT_STATUS[status];
  return <Badge tone={s?.tone ?? "muted"} dot>{s?.label ?? status}</Badge>;
}

export default function DocumentsPage() {
  const me = useMe();
  const [params, setParams] = useSearchParams();
  const { data: warehouses = [] } = useWarehouses();
  const filters = {
    doc_type: params.get("type") || undefined,
    status: params.get("status") || undefined,
    warehouse_id: params.get("warehouse") ? Number(params.get("warehouse")) : undefined,
    q: params.get("q") || undefined,
  };
  const openId = params.get("doc") ? Number(params.get("doc")) : null;
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  };
  const { data: docs, isLoading, error, refetch } = useQuery({
    queryKey: ["documents", filters],
    queryFn: () => unwrap(api.GET("/inventory/documents", { params: { query: { ...filters, doc_type: filters.doc_type as never, status: filters.status as never, limit: 200 } } })),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader eyebrow="انبار" title="اسناد انبار"
        subtitle="هر تغییر موجودی یک سند قطعی است؛ سند هرگز ویرایش یا حذف نمی‌شود و اشتباه با سند برگشت اصلاح می‌شود." />
      <Card>
        <div className="grid gap-3 border-b border-border p-4 md:grid-cols-4">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" />
            <Input className="pr-10" placeholder="کد سند یا شماره فاکتور" value={params.get("q") ?? ""} onChange={e => setFilter("q", e.target.value)} data-testid="docs-search" />
          </div>
          <Select value={params.get("type") ?? ""} onChange={e => setFilter("type", e.target.value)} aria-label="نوع سند" data-testid="docs-type">
            <option value="">همه انواع سند</option>
            {Object.entries(DOCUMENT_TYPES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
          <Select value={params.get("status") ?? ""} onChange={e => setFilter("status", e.target.value)} aria-label="وضعیت سند">
            <option value="">همه وضعیت‌ها</option>
            {Object.entries(DOCUMENT_STATUS).filter(([k]) => k !== "draft" && k !== "canceled").map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
          {me.role === "org_admin" ? (
            <Select value={params.get("warehouse") ?? ""} onChange={e => setFilter("warehouse", e.target.value)} aria-label="انبار">
              <option value="">همه انبارها</option>{warehouses.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          ) : <div className="hidden md:block" />}
        </div>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : !docs?.length ? (
          <EmptyState icon={<FileStack className="size-5" />} title="سندی با این فیلترها نیست" />
        ) : (
          <Table testId="documents-table">
            <thead><tr><th>کد سند</th><th>نوع</th><th>وضعیت</th><th>زمان</th><th>انبار</th><th>ورود</th><th>خروج</th><th>طرف / مرجع</th><th>کاربر</th></tr></thead>
            <tbody>
              {docs.map(d => (
                <tr key={d.id} className="cursor-pointer hover:bg-surface-2" onClick={() => setFilter("doc", String(d.id))} data-testid="document-row" data-code={d.code} data-type={d.doc_type} data-status={d.status}>
                  <td className="font-mono text-xs font-semibold ltr text-start">{d.code}</td>
                  <td><DocTypeBadge type={d.doc_type} /></td>
                  <td><DocStatusBadge status={d.status} /></td>
                  <td className="whitespace-nowrap text-xs text-text-2">{faDateTime(d.created_at)}</td>
                  <td className="text-text-2">{d.warehouse_name ?? "—"}</td>
                  <td className="tnum text-success">{d.total_in ? `+${faNumber(d.total_in)}` : "—"}</td>
                  <td className="tnum text-danger">{d.total_out ? `−${faNumber(d.total_out)}` : "—"}</td>
                  <td className="max-w-60 text-xs text-text-2">
                    {d.partner_name ?? ""}{d.external_ref ? ` · ${d.external_ref}` : ""}
                    {d.reversal_of_code && <span className="font-mono ltr"> ↩ {d.reversal_of_code}</span>}
                    {d.reference_type === "order" && <Badge className="ms-1">سفارش #{faNumber(d.reference_id)}</Badge>}
                  </td>
                  <td className="text-xs text-text-2">{d.created_by_name ?? "سیستم"}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <DocumentModal id={openId} onClose={() => setFilter("doc", "")} onOpen={id => setFilter("doc", String(id))} />
    </>
  );
}

export function DocumentModal({ id, onClose, onOpen }: { id: number | null; onClose: () => void; onOpen: (id: number) => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data: doc, isLoading } = useQuery({
    queryKey: ["documents", "detail", id],
    queryFn: () => unwrap(api.GET("/inventory/documents/{document_id}", { params: { path: { document_id: id! } } })),
    enabled: id != null,
  });
  const reverse = useMutation({
    mutationFn: (args: { reason: string; key: string }) => unwrap(api.POST("/inventory/documents/{document_id}/reverse", {
      params: { path: { document_id: id! }, header: { "Idempotency-Key": args.key } }, body: { reason: args.reason } })),
    onSuccess: (reversal: Doc) => {
      toast.success(`سند برگشت ${reversal.code} ثبت شد.`);
      ["documents", "movements", "products", "stock-buckets", "catalog-product"].forEach(k => queryClient.invalidateQueries({ queryKey: [k] }));
      onOpen(reversal.id);
    },
    onError: e => toast.error(errorMessage(e)),
  });
  async function askReverse(d: Doc) {
    const reason = await promptDialog({
      title: `برگشت سند ${d.code}`, text: "اثر این سند با یک سند برگشت خنثی می‌شود؛ خود سند و گردش‌هایش حذف نمی‌شوند.",
      label: "دلیل برگشت", placeholder: "مثلاً ثبت تکراری یا مقدار اشتباه", required: true, minLength: 3, maxLength: 500,
      confirmLabel: "ثبت سند برگشت", danger: true,
    });
    if (reason) reverse.mutate({ reason, key: newIdempotencyKey() });
  }

  return (
    <Modal open={id != null} onClose={onClose} size="lg" testId="document-detail"
      title={doc ? <span className="flex flex-wrap items-center gap-2"><span className="font-mono ltr">{doc.code}</span><DocTypeBadge type={doc.doc_type} /><DocStatusBadge status={doc.status} /></span> : "سند انبار"}
      description={doc && `${faDateTime(doc.created_at)} · ${doc.created_by_name ?? "سیستم"}${doc.warehouse_name ? ` · ${doc.warehouse_name}` : ""}`}
      footer={doc?.can_reverse && <Button variant="outline-danger" icon={<RotateCcw className="size-4" />} loading={reverse.isPending} onClick={() => askReverse(doc)} data-testid="document-reverse">سند برگشت</Button>}>
      {isLoading || !doc ? <div className="h-40 animate-pulse rounded-xl bg-surface-2" /> : (
        <div className="space-y-4">
          <dl className="grid gap-3 text-sm sm:grid-cols-3">
            {doc.partner_name && <div><dt className="text-xs text-muted">طرف تجاری</dt><dd className="font-medium">{doc.partner_name}</dd></div>}
            {doc.external_ref && <div><dt className="text-xs text-muted">فاکتور / بارنامه</dt><dd className="font-mono ltr text-start">{doc.external_ref}</dd></div>}
            {doc.note && <div className="sm:col-span-3"><dt className="text-xs text-muted">توضیح</dt><dd>{doc.note}</dd></div>}
            {doc.reversal_of_id && <div><dt className="text-xs text-muted">برگشتِ سند</dt><dd><button className="font-mono text-brand ltr hover:underline" onClick={() => onOpen(doc.reversal_of_id!)}>{doc.reversal_of_code}</button></dd></div>}
            {doc.reversed_by_id && <div><dt className="text-xs text-muted">برگشت‌خورده با</dt><dd><button className="font-mono text-brand ltr hover:underline" onClick={() => onOpen(doc.reversed_by_id!)} data-testid="document-reversed-by">{doc.reversed_by_code}</button></dd></div>}
          </dl>
          <div className="overflow-x-auto">
            <table className="table-base" data-testid="document-movements">
              <thead><tr><th>کالا</th><th>انبار</th><th>وضعیت کیفی</th><th>نوع گردش</th><th>تغییر</th><th>مانده</th></tr></thead>
              <tbody>
                {doc.movements.map(m => (
                  <tr key={m.id}>
                    <td><div className="font-medium">{m.product_name}</div><div className="font-mono text-xs text-muted">{m.product_sku}</div></td>
                    <td className="text-text-2">{m.warehouse_name ?? "—"}</td>
                    <td><Badge tone={STOCK_STATUS[m.stock_status as StockStatus]?.tone ?? "muted"}>{STOCK_STATUS[m.stock_status as StockStatus]?.label ?? m.stock_status}</Badge></td>
                    <td><MovementBadge type={m.movement_type} /></td>
                    <td className={`tnum font-bold ltr text-end ${m.quantity_change > 0 ? "text-success" : "text-danger"}`}>{m.quantity_change > 0 ? "+" : ""}{faNumber(m.quantity_change)}</td>
                    <td className="tnum">{faNumber(m.balance_after)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Modal>
  );
}
