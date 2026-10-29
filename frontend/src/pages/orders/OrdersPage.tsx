import { useEffect, useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, FileText, PackageSearch, Plus, Truck, X, Zap } from "lucide-react";
import { api, unwrap } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { OrderStatusBadge } from "@/components/StatusBadges";
import { useToast } from "@/components/Toast";
import { BulkActionModal, type BulkRequest } from "@/components/BulkActionModal";
import { useAsyncExport } from "@/hooks/data";
import { type OrderStatus } from "@/lib/labels";
import { faNumber, faShortDateTime } from "@/lib/format";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, Table, TableSkeleton, cn } from "@/ui/primitives";
import { OrderFormModal } from "./OrderFormModal";
import { OrderSearch, useOrderFilters } from "./OrderSearch";
import { OrderDetailModal } from "./OrderDetailModal";
import { useDeepLink } from "@/hooks/useDeepLink";

export default function OrdersPage() {
  const me = useMe();
  const toast = useToast();
  const [filters, setFilters] = useOrderFilters();
  const [formOpen, setFormOpen] = useState(false);
  const [detailId, setDetailId] = useState<number | null>(null);
  const queryClient = useQueryClient();
  // انتخاب چندتایی برای عملیات گروهی (با تغییر فیلتر پاک می‌شود)
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulk, setBulk] = useState<BulkRequest | null>(null);
  const filterKey = JSON.stringify(filters);
  useEffect(() => setSelected(new Set()), [filterKey]);
  // از اعلان (سفارش ناموفق/منقضی): جزئیات همان سفارش باز می‌شود
  const flash = useDeepLink("order", { onHit: setDetailId });
  const exporter = useAsyncExport(toast.error, () => toast.success("گزارش آماده و دانلود شد."));

  const { data: orders, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["orders", filters],
    queryFn: () => unwrap(api.GET("/orders/", { params: { query: {
      ...filters, order_status: filters.order_status as OrderStatus | undefined,
      priority: filters.priority === "true" ? true : undefined, view: filters.view as "late" | "today" | "needs_update" | undefined, limit: 300,
    } } })),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  });

  const ids = [...selected];
  const toggle = (id: number) => setSelected(prev => { const next = new Set(prev); if (next.has(id)) next.delete(id); else if (next.size < 200) next.add(id); return next; });
  const allChecked = !!orders?.length && orders.every(o => selected.has(o.id));
  const toggleAll = () => setSelected(allChecked ? new Set() : new Set((orders ?? []).slice(0, 200).map(o => o.id)));
  const label = `${faNumber(ids.length)} سفارش`;

  return (
    <>
      <PageHeader eyebrow="عملیات" title="سفارش‌ها"
        subtitle={me.role === "warehouse_manager" ? "سفارش‌های سازمان — ارسال از انبار شما را مدیریت کنید" : "ثبت، پیگیری و مدیریت سفارش‌ها"}
        actions={<>
          <Button variant="secondary" size="sm" loading={exporter.running === "/reports/export/orders/excel"} icon={<FileSpreadsheet className="size-4" />}
            onClick={() => exporter.run("/reports/export/orders/excel", "Pasineh_Orders.xlsx")}>اکسل</Button>
          <Button variant="secondary" size="sm" loading={exporter.running === "/reports/export/orders/pdf"} icon={<FileText className="size-4" />}
            onClick={() => exporter.run("/reports/export/orders/pdf", "Pasineh_Orders.pdf")}>PDF</Button>
          <Button icon={<Plus className="size-4" />} onClick={() => setFormOpen(true)} data-testid="new-order">ثبت سفارش</Button>
        </>} />

      <Card>
        <OrderSearch key={JSON.stringify(filters)} filters={filters} onChange={setFilters} />
        {ids.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-b border-border bg-brand-soft/40 px-4 py-2.5" data-testid="orders-bulk-bar">
            <span className="text-sm font-semibold">{label} انتخاب شده</span>
            <Button size="sm" variant="secondary" icon={<Truck className="size-4" />} data-testid="bulk-assign"
              onClick={() => setBulk({ endpoint: "/orders/bulk", action: "assign", ids, title: `تخصیص خودکار خودرو به ${label}` })}>تخصیص خودکار خودرو</Button>
            {me.role === "org_admin" && <>
              <Button size="sm" variant="secondary" icon={<Zap className="size-4" />} data-testid="bulk-priority"
                onClick={() => setBulk({ endpoint: "/orders/bulk", action: "priority", ids, params: { priority: true }, title: `فوری کردن ${label}` })}>فوری کردن</Button>
              <Button size="sm" variant="secondary"
                onClick={() => setBulk({ endpoint: "/orders/bulk", action: "priority", ids, params: { priority: false }, title: `عادی کردن ${label}` })}>عادی کردن</Button>
            </>}
            <Button size="sm" variant="secondary" icon={<FileSpreadsheet className="size-4" />} loading={exporter.running === "selected"}
              onClick={() => exporter.run("/reports/generate", "Pasineh_Orders.xlsx", { report: "orders", format: "excel", order_ids: ids }, "selected")}>اکسل انتخاب‌شده‌ها</Button>
            <Button size="sm" variant="ghost" icon={<X className="size-4" />} onClick={() => setSelected(new Set())}>لغو انتخاب</Button>
          </div>
        )}
        {orders && <div className="px-4 pt-3 text-xs text-muted" data-testid="orders-count">{orders.length.toLocaleString("fa-IR")} سفارش{isFetching ? " · در حال به‌روزرسانی…" : ""}</div>}

        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : orders!.length === 0 ? (
          <EmptyState icon={<PackageSearch className="size-5" />} title="سفارشی یافت نشد" text="فیلترها را تغییر دهید یا سفارش جدید ثبت کنید." />
        ) : (
          <Table testId="orders-table">
            <thead><tr><th><span className="inline-flex items-center gap-3"><input type="checkbox" checked={allChecked} onChange={toggleAll} aria-label="انتخاب همه" data-testid="orders-select-all" className="size-4 accent-[var(--brand)]" />کد پیگیری</span></th><th>مشتری</th><th>اقلام</th><th>مقصد</th><th>زمان تحویل</th><th>وضعیت</th></tr></thead>
            <tbody>
              {orders!.map(o => (
                <tr key={o.id} className={cn("clickable", flash === o.id && "focus-flash", selected.has(o.id) && "bg-brand-soft/30")} data-focus={`order-${o.id}`} onClick={() => setDetailId(o.id)}>
                  <td className="whitespace-nowrap">
                    {/* انتخاب برای عملیات گروهی؛ کلیک روی آن جزئیات را باز نمی‌کند */}
                    <input type="checkbox" checked={selected.has(o.id)} onChange={() => toggle(o.id)} onClick={e => e.stopPropagation()}
                      aria-label={`انتخاب ${o.tracking_code}`} data-testid="order-select" className="me-3 size-4 align-middle accent-[var(--brand)]" />
                    <span className="font-mono font-semibold ltr">{o.tracking_code}</span>
                    {o.priority && <Badge tone="danger" className="ms-2">فوری</Badge>}
                  </td>
                  <td><div className="font-medium">{o.customer?.name ?? o.recipient_name}</div><div className="font-mono text-xs text-muted ltr">{o.recipient_mobile}</div></td>
                  <td className="max-w-60 text-text-2">{o.items.map(i => `${i.product_name} ×${i.quantity}`).join("، ")}</td>
                  <td className="whitespace-nowrap">{o.destination_province} / {o.destination_city}</td>
                  <td className="whitespace-nowrap text-text-2">{faShortDateTime(o.delivery_window_start)}</td>
                  <td><OrderStatusBadge status={o.status} /></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <div className="flex flex-wrap justify-between gap-2 border-t border-border px-5 py-3 text-xs text-muted">
          <span>برای جزئیات، تاریخچه و تغییر وضعیت روی هر سفارش کلیک کنید.</span>
          <span className="inline-flex items-center gap-1.5"><span className={`size-1.5 rounded-full bg-success ${isFetching ? "live-dot" : ""}`} />به‌روزرسانی خودکار هر ۱۵ ثانیه</span>
        </div>
      </Card>

      <OrderFormModal open={formOpen} onClose={() => setFormOpen(false)} />
      <OrderDetailModal orderId={detailId} onClose={() => setDetailId(null)} />
      <BulkActionModal request={bulk} onClose={() => setBulk(null)} onDone={() => {
        setSelected(new Set());
        queryClient.invalidateQueries({ queryKey: ["orders"] });
        queryClient.invalidateQueries({ queryKey: ["action-center"] });
      }} />
    </>
  );
}
