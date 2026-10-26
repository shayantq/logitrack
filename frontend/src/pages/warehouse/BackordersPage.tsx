/**
 * سفارش‌های معوق (فصل ۱۱): مقدار تأمین‌نشده سفارش‌ها به ترتیب اولویت تخصیص (فوری، تاریخ تحویل، زمان ثبت).
 * «تخصیص» موجودی قابل وعده را به صف رزرو می‌کند؛ «سفارش تکمیلی» معوق‌های تخصیص‌یافته یک سفارش را ارسال می‌کند.
 */
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Hourglass, Send, Zap } from "lucide-react";
import { api, errorMessage, unwrap } from "@/api/client";
import { useToast } from "@/components/Toast";
import { BACKORDER_STATUS } from "@/lib/labels";
import { faDateTime, faNumber, localToIso, tomorrowIsoDate } from "@/lib/format";
import { promptDialog } from "@/ui/dialogs";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, SegmentedControl, Table, TableSkeleton } from "@/ui/primitives";
import { useInvalidateOperations } from "./shared";

export default function BackordersPage() {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const [status, setStatus] = useState<"active" | "fulfilled" | "canceled">("active");
  const { data: rows, isLoading, error, refetch } = useQuery({
    queryKey: ["backorders", status], queryFn: () => unwrap(api.GET("/backorders/", { params: { query: { status } } })),
  });
  const allocate = useMutation({
    mutationFn: () => unwrap(api.POST("/backorders/allocate", { body: {} })),
    onSuccess: r => { toast.success(r.allocated_quantity ? `${faNumber(r.allocated_quantity)} عدد به سفارش‌های معوق تخصیص یافت.` : "موجودی قابل وعده‌ای برای تخصیص نیست."); invalidate(); refetch(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const fulfill = useMutation({
    mutationFn: (orderId: number) => {
      const day = tomorrowIsoDate();
      return unwrap(api.POST("/backorders/orders/{order_id}/fulfill", { params: { path: { order_id: orderId } },
        body: { delivery_window_start: localToIso(day, "09:00"), delivery_window_end: localToIso(day, "17:00") } }));
    },
    onSuccess: o => { toast.success(`سفارش تکمیلی ${o.tracking_code} ثبت شد.`); invalidate(); refetch(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const cancel = useMutation({
    mutationFn: (args: { id: number; reason: string }) => unwrap(api.POST("/backorders/{backorder_id}/cancel", {
      params: { path: { backorder_id: args.id } }, body: { reason: args.reason } })),
    onSuccess: () => { toast.success("سفارش معوق لغو شد."); refetch(); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <>
      <PageHeader eyebrow="عملیات" title="سفارش‌های معوق"
        subtitle="کمبود موجودی سفارش‌ها دور ریخته نمی‌شود؛ به ترتیب فوری بودن، تاریخ تحویل و زمان ثبت به موجودی تازه تخصیص می‌یابد."
        actions={<Button icon={<Zap className="size-4" />} loading={allocate.isPending} onClick={() => allocate.mutate()} data-testid="backorders-allocate">تخصیص با اولویت</Button>} />
      <Card>
        <div className="border-b border-border p-4">
          <SegmentedControl value={status} onChange={setStatus} options={[
            { value: "active", label: "باز و تخصیص‌یافته" }, { value: "fulfilled", label: "ارسال‌شده" }, { value: "canceled", label: "لغوشده" }]} />
        </div>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : !rows?.length ? (
          <EmptyState icon={<Hourglass className="size-5" />} title="سفارش معوقی نیست" />
        ) : (
          <Table testId="backorders-table">
            <thead><tr><th>اولویت</th><th>سفارش</th><th>کالا</th><th>مقدار</th><th>وضعیت</th><th>سررسید</th><th className="w-1" /></tr></thead>
            <tbody>
              {rows.map((b, i) => (
                <tr key={b.id} data-testid="backorder-row" data-status={b.status} data-order={b.order_tracking_code ?? ""}>
                  <td className="tnum text-xs">{faNumber(i + 1)}{b.priority && <Badge tone="danger" className="ms-1">فوری</Badge>}</td>
                  <td><div className="font-mono text-xs font-semibold ltr text-start">{b.order_tracking_code}</div><div className="text-xs text-muted">{b.customer_name}</div></td>
                  <td>{b.product_name}<div className="font-mono text-xs text-muted">{b.product_sku}</div></td>
                  <td className="tnum font-bold">{faNumber(b.quantity)}</td>
                  <td><Badge tone={BACKORDER_STATUS[b.status]?.tone ?? "muted"} dot>{b.status_label}</Badge></td>
                  <td className="whitespace-nowrap text-xs text-text-2">{faDateTime(b.due_at)}</td>
                  <td>
                    <div className="flex gap-1">
                      {b.status === "allocated" && <Button size="sm" icon={<Send className="size-3.5" />} loading={fulfill.isPending && fulfill.variables === b.order_id}
                        onClick={() => fulfill.mutate(b.order_id)} data-testid="backorder-fulfill">سفارش تکمیلی</Button>}
                      {(b.status === "open" || b.status === "allocated") && <Button size="sm" variant="ghost"
                        onClick={() => promptDialog({ title: "لغو سفارش معوق", label: "دلیل", required: true, minLength: 3, maxLength: 300, danger: true })
                          .then(reason => reason && cancel.mutate({ id: b.id, reason }))}>لغو</Button>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}
