import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, FileText, PackageSearch, Plus, Truck, X, Zap } from "lucide-react";
import { ApiError, api, unwrap } from "@/api/client";
import { QueryFeedback } from "@/components/QueryFeedback";
import { useMe } from "@/auth/AuthContext";
import { OrderStatusBadge } from "@/components/StatusBadges";
import { useToast } from "@/components/Toast";
import { BulkActionModal, type BulkRequest } from "@/components/BulkActionModal";
import { useAsyncExport } from "@/hooks/data";
import { type OrderStatus } from "@/lib/labels";
import { faNumber, faShortDateTime } from "@/lib/format";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, Select, Table, TableSkeleton, cn, SortHeader, type SortState } from "@/ui/primitives";
import { UpdatedAt } from "@/components/UpdatedAt";
import { hasOrderDraft, OrderFormModal } from "./OrderFormModal";
import { OrderSearch, useOrderFilters } from "./OrderSearch";
import { OrderDetailModal } from "./OrderDetailModal";
import { useDeepLink } from "@/hooks/useDeepLink";

type OrderSort = "tracking_code" | "destination_city" | "delivery_window_start" | "status";

export default function OrdersPage() {
  const me = useMe();
  const toast = useToast();
  const [filters, setFilters] = useOrderFilters();
  const [params, setParams] = useSearchParams();
  const rawPage = Number(params.get("page") || 1);
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1;
  const pageSize = [25, 50, 100, 200].includes(Number(params.get("page_size"))) ? Number(params.get("page_size")) : 50;
  const sortKey = params.get("sort") as OrderSort | null;
  const sort: SortState<OrderSort> = sortKey && ["tracking_code", "destination_city", "delivery_window_start", "status"].includes(sortKey)
    ? { key: sortKey, dir: params.get("direction") === "asc" ? "asc" : "desc" } : null;
  const updatePage = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) value === null ? next.delete(key) : next.set(key, value);
    setParams(next);
  };
  const setSort = (next: SortState<OrderSort>) => updatePage({ sort: next?.key ?? null, direction: next?.dir ?? null, page: null });
  const [formOpen, setFormOpen] = useState(() => hasOrderDraft(me.id));
  const [detailId, setDetailId] = useState<number | null>(null);
  const queryClient = useQueryClient();
  // انتخاب چندتایی برای عملیات گروهی (با تغییر فیلتر پاک می‌شود)
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulk, setBulk] = useState<BulkRequest | null>(null);
  const filterKey = JSON.stringify([filters, page, pageSize, sort]);
  useEffect(() => setSelected(new Set()), [filterKey]);
  useEffect(() => {
    if (params.get("new") !== "1") return;
    setFormOpen(true);
    const next = new URLSearchParams(params);
    next.delete("new");
    setParams(next, { replace: true });
  }, [params, setParams]);
  // از اعلان (سفارش ناموفق/منقضی): جزئیات همان سفارش باز می‌شود
  const flash = useDeepLink("order", { onHit: setDetailId });
  const exporter = useAsyncExport(toast.error, () => toast.success("گزارش آماده و دانلود شد."));

  const { data, isPending, error, refetch, isFetching, isPlaceholderData, dataUpdatedAt } = useQuery({
    queryKey: ["orders", "page", filters, sort, page, pageSize],
    queryFn: () => unwrap(api.GET("/orders/page", { params: { query: {
      ...filters, order_status: filters.order_status as OrderStatus | undefined,
      priority: filters.priority === "true" ? true : undefined, view: filters.view as "late" | "today" | "needs_update" | undefined,
      skip: (page - 1) * pageSize, limit: pageSize, sort: sort?.key, direction: sort?.dir,
    } } })),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  });
  const forbidden = error instanceof ApiError && error.status === 403;
  const orders = forbidden ? undefined : data?.items;
  const total = forbidden ? 0 : data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const selectionReady = !isFetching && !isPlaceholderData && !error;
  const headerCheckbox = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!data || isPlaceholderData || error) return;
    setSelected(prev => new Set([...prev].filter(id => data.items.some(o => o.id === id))));
    if (page > pageCount) {
      const next = new URLSearchParams(params);
      next.set("page", String(pageCount));
      setParams(next, { replace: true });
    }
  }, [data, isPlaceholderData, error, page, pageCount, params, setParams]);

  const ids = [...selected];
  const toggle = (id: number) => setSelected(prev => { const next = new Set(prev); if (next.has(id)) next.delete(id); else if (next.size < 200) next.add(id); return next; });
  const allChecked = !!orders?.length && orders.every(o => selected.has(o.id));
  const toggleAll = () => setSelected(allChecked ? new Set() : new Set((orders ?? []).slice(0, 200).map(o => o.id)));
  useEffect(() => { if (headerCheckbox.current) headerCheckbox.current.indeterminate = selected.size > 0 && !allChecked; }, [selected, allChecked]);
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

      <div className="mb-2 flex justify-end"><UpdatedAt at={dataUpdatedAt} /></div>
      <Card aria-busy={isFetching}>
        <OrderSearch key={JSON.stringify(filters)} filters={filters} onChange={setFilters} />
        {ids.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-b border-border bg-brand-soft/40 px-4 py-2.5" data-testid="orders-bulk-bar">
            <span className="text-sm font-semibold">{label} انتخاب شده</span>
            <Button size="sm" variant="secondary" icon={<Truck className="size-4" />} data-testid="bulk-assign"
              disabled={!selectionReady} onClick={() => setBulk({ endpoint: "/orders/bulk", action: "assign", ids, title: `تخصیص خودکار خودرو به ${label}` })}>تخصیص خودکار خودرو</Button>
            {me.role === "org_admin" && <>
              <Button size="sm" variant="secondary" icon={<Zap className="size-4" />} data-testid="bulk-priority"
                disabled={!selectionReady} onClick={() => setBulk({ endpoint: "/orders/bulk", action: "priority", ids, params: { priority: true }, title: `فوری کردن ${label}` })}>فوری کردن</Button>
              <Button size="sm" variant="secondary"
                disabled={!selectionReady} onClick={() => setBulk({ endpoint: "/orders/bulk", action: "priority", ids, params: { priority: false }, title: `عادی کردن ${label}` })}>عادی کردن</Button>
            </>}
            <Button size="sm" variant="secondary" icon={<FileSpreadsheet className="size-4" />} loading={exporter.running === "selected"}
              disabled={!selectionReady} onClick={() => exporter.run("/reports/generate", "Pasineh_Orders.xlsx", { report: "orders", format: "excel", order_ids: ids }, "selected")}>اکسل انتخاب‌شده‌ها</Button>
            <Button size="sm" variant="ghost" icon={<X className="size-4" />} onClick={() => setSelected(new Set())}>لغو انتخاب</Button>
          </div>
        )}
        {orders && <div role="status" className="px-4 pt-3 text-xs text-muted" data-testid="orders-count">{faNumber(total)} سفارش{isFetching ? " · در حال به‌روزرسانی…" : ""}</div>}
        {orders && <QueryFeedback error={error} retry={refetch} updatedAt={dataUpdatedAt} />}

        {isPending ? <TableSkeleton /> : !orders ? <ErrorState error={error} onRetry={refetch} /> : orders.length === 0 ? (
          <EmptyState icon={<PackageSearch className="size-5" />} title={Object.keys(filters).length ? "سفارشی با این فیلترها یافت نشد" : "هنوز سفارشی ثبت نشده"}
            action={Object.keys(filters).length ? <Button variant="secondary" onClick={() => setFilters({})}>پاک کردن فیلترها</Button> : <Button onClick={() => setFormOpen(true)}>ثبت اولین سفارش</Button>} />
        ) : (
          <>
          <Table testId="orders-table">
            <thead><tr><th aria-sort={sort?.key === "tracking_code" ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}><span className="inline-flex items-center gap-3"><input ref={headerCheckbox} type="checkbox" checked={allChecked} disabled={!selectionReady} onChange={toggleAll} aria-label="انتخاب ردیف‌های این صفحه" data-testid="orders-select-all" className="size-4 accent-[var(--brand)]" /><button type="button" onClick={() => setSort(sort?.key === "tracking_code" ? (sort.dir === "asc" ? { key: "tracking_code", dir: "desc" } : null) : { key: "tracking_code", dir: "asc" })} data-testid="sort-tracking_code">کد پیگیری</button></span></th><th>مشتری</th><th>اقلام</th><SortHeader label="مقصد" column="destination_city" sort={sort} onSort={setSort} /><SortHeader label="زمان تحویل" column="delivery_window_start" sort={sort} onSort={setSort} /><SortHeader label="وضعیت" column="status" sort={sort} onSort={setSort} /></tr></thead>
            <tbody>
              {orders!.map(o => (
                <tr key={o.id} className={cn("clickable", flash === o.id && "focus-flash", selected.has(o.id) && "bg-brand-soft/30")} data-focus={`order-${o.id}`} onClick={() => setDetailId(o.id)}>
                  <td className="whitespace-nowrap">
                    {/* انتخاب برای عملیات گروهی؛ کلیک روی آن جزئیات را باز نمی‌کند */}
                    <input type="checkbox" disabled={!selectionReady} checked={selected.has(o.id)} onChange={() => toggle(o.id)} onClick={e => e.stopPropagation()}
                      aria-label={`انتخاب ${o.tracking_code}`} data-testid="order-select" className="me-3 size-4 align-middle accent-[var(--brand)]" />
                    <button type="button" className="font-mono font-semibold ltr hover:underline" onClick={e => { e.stopPropagation(); setDetailId(o.id); }}>{o.tracking_code}</button>
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
          </>
        )}
        {orders && total > 0 && <nav aria-label="صفحه‌های سفارش‌ها" className="flex flex-wrap items-center gap-3 border-t border-border px-5 py-3" data-testid="orders-pagination">
          <span className="text-sm" data-testid="orders-range">{faNumber(orders.length ? (page - 1) * pageSize + 1 : 0)} تا {faNumber(Math.min(page * pageSize, total))} از {faNumber(total)}</span>
          <Select aria-label="تعداد سفارش در هر صفحه" className="w-32" value={pageSize} disabled={isFetching} onChange={e => updatePage({ page_size: e.target.value, page: null })}>
            {[25, 50, 100, 200].map(size => <option key={size} value={size}>{faNumber(size)} در صفحه</option>)}
          </Select>
          <div className="ms-auto flex items-center gap-2">
            <Button variant="secondary" size="sm" disabled={page <= 1 || isFetching} onClick={() => updatePage({ page: String(page - 1) })}>صفحه قبل</Button>
            <span className="text-xs">صفحه {faNumber(page)} از {faNumber(pageCount)}</span>
            <Button variant="secondary" size="sm" disabled={page >= pageCount || isFetching} onClick={() => updatePage({ page: String(page + 1) })}>صفحه بعد</Button>
          </div>
        </nav>}
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
