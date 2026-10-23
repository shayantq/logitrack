import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { BookOpen } from "lucide-react";
import { api, unwrap } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { MovementBadge } from "@/components/StatusBadges";
import { useProducts, useWarehouses } from "@/hooks/data";
import { MOVEMENT_TYPES, STOCK_STATUS, type StockStatus } from "@/lib/labels";
import { faDateTime, faNumber } from "@/lib/format";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Select, Table, TableSkeleton } from "@/ui/primitives";
import { DateField } from "@/ui/datetime";
import { DocumentModal } from "./DocumentsPage";

export default function LedgerPage() {
  const me = useMe();
  const [params, setParams] = useSearchParams();
  const { data: products = [] } = useProducts();
  const { data: warehouses = [] } = useWarehouses();
  const [docId, setDocId] = useState<number | null>(null);
  const filters = {
    product_id: params.get("product") ? Number(params.get("product")) : undefined,
    warehouse_id: params.get("warehouse") ? Number(params.get("warehouse")) : undefined,
    movement_type: params.get("type") || undefined,
    date_from: params.get("from") || undefined,
    date_to: params.get("to") || undefined,
    stock_status: params.get("status") || undefined,
  };
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  };

  const { data: movements, isLoading, error, refetch } = useQuery({
    queryKey: ["movements", filters],
    queryFn: () => unwrap(api.GET("/inventory/movements", { params: { query: {
      ...filters, movement_type: filters.movement_type as never, stock_status: filters.stock_status as never,
      date_to: filters.date_to ? new Date(new Date(filters.date_to).getTime() + 86_400_000).toISOString().slice(0, 10) : undefined,
      limit: 500,
    } } })),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader eyebrow="انبار" title="دفتر گردش کالا" subtitle="هر ورود، خروج، اصلاح و انتقال — با سند، کاربر، دلیل و مرجع. مانده‌ی هر کالا همیشه برابر جمع گردش‌هایش است و هیچ گردشی ویرایش یا حذف نمی‌شود." />
      <Card>
        <div className="grid gap-3 border-b border-border p-4 md:grid-cols-3 xl:grid-cols-6">
          <Select value={params.get("product") ?? ""} onChange={e => setFilter("product", e.target.value)} aria-label="کالا">
            <option value="">همه کالاها</option>{products.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
          {me.role === "org_admin" ? (
            <Select value={params.get("warehouse") ?? ""} onChange={e => setFilter("warehouse", e.target.value)} aria-label="انبار">
              <option value="">همه انبارها</option>{warehouses.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          ) : <div className="hidden md:block" />}
          <Select value={params.get("type") ?? ""} onChange={e => setFilter("type", e.target.value)} data-testid="ledger-type" aria-label="نوع">
            <option value="">همه انواع گردش</option>
            {Object.entries(MOVEMENT_TYPES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
          <Select value={params.get("status") ?? ""} onChange={e => setFilter("status", e.target.value)} aria-label="وضعیت کیفی">
            <option value="">همه وضعیت‌های کیفی</option>
            {Object.entries(STOCK_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
          <DateField aria-label="از تاریخ" placeholder="از تاریخ" value={params.get("from") ?? ""} onChange={v => setFilter("from", v)} className="w-44" />
          <DateField aria-label="تا تاریخ" placeholder="تا تاریخ" value={params.get("to") ?? ""} onChange={v => setFilter("to", v)} className="w-44" />
        </div>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : movements!.length === 0 ? (
          <EmptyState icon={<BookOpen className="size-5" />} title="گردشی با این فیلترها نیست" />
        ) : (
          <Table testId="ledger-table">
            <thead><tr><th>زمان</th><th>سند</th><th>کالا</th><th>انبار</th><th>نوع</th><th>تغییر</th><th>مانده</th><th>کاربر</th><th>توضیح / مرجع</th></tr></thead>
            <tbody>
              {movements!.map(m => (
                <tr key={m.id}>
                  <td className="whitespace-nowrap text-xs text-text-2">{faDateTime(m.created_at)}</td>
                  <td>
                    {m.document_id ? <button type="button" className="font-mono text-xs text-brand ltr hover:underline" onClick={() => setDocId(m.document_id!)} data-testid="ledger-document">{m.document_code}</button> : "—"}
                    {m.document_status === "reversed" && <Badge tone="danger" className="ms-1">برگشت‌خورده</Badge>}
                  </td>
                  <td><div className="font-medium">{m.product_name}</div><div className="font-mono text-xs text-muted">{m.product_sku}</div></td>
                  <td className="text-text-2">{m.warehouse_name ?? "—"}
                    {m.stock_status !== "available" && <Badge tone={STOCK_STATUS[m.stock_status as StockStatus]?.tone ?? "muted"} className="ms-1">{STOCK_STATUS[m.stock_status as StockStatus]?.label ?? m.stock_status}</Badge>}</td>
                  <td><MovementBadge type={m.movement_type} /></td>
                  <td className={`tnum font-bold ltr text-end ${m.quantity_change > 0 ? "text-success" : "text-danger"}`}>
                    {m.quantity_change > 0 ? "+" : ""}{faNumber(m.quantity_change)}
                  </td>
                  <td className="tnum font-semibold">{faNumber(m.balance_after)}</td>
                  <td className="text-xs text-text-2">{m.created_by_name ?? "سیستم"}</td>
                  <td className="max-w-72 text-xs text-text-2">{m.reason}{m.reference_type === "order" && <Badge className="ms-1">سفارش #{faNumber(m.reference_id)}</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <DocumentModal id={docId} onClose={() => setDocId(null)} onOpen={setDocId} />
    </>
  );
}
