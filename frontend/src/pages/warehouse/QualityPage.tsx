/**
 * بازرسی کیفی و قرنطینه (فصل ۸): موجودی «در انتظار بازرسی»، قرنطینه، توقیف، مردود، معیوب و آسیب‌دیده
 * به تفکیک محل و بچ، با ثبت نتیجه بازرسی. وضعیت کیفی مستقل از محل است و کالای غیرتأییدشده هرگز به سفارش نمی‌رسد.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ClipboardCheck, ShieldCheck } from "lucide-react";
import { api, unwrap, type Schemas } from "@/api/client";
import { STOCK_STATUS, type StockStatus } from "@/lib/labels";
import { faDate, faDateTime, faNumber } from "@/lib/format";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, SegmentedControl, Table, TableSkeleton } from "@/ui/primitives";
import { InspectModal, StatusBadge, WarehousePicker, useWarehouseChoice } from "./shared";

type Balance = Schemas["StockBalanceOut"];
const HELD: StockStatus[] = ["pending", "quarantine", "blocked", "rejected", "defective", "damaged"];

export default function QualityPage() {
  const choice = useWarehouseChoice();
  const warehouseId = choice.value ? Number(choice.value) : null;
  const [status, setStatus] = useState<StockStatus>("pending");
  const [target, setTarget] = useState<Balance | null>(null);
  const { data: balances, isLoading, error, refetch } = useQuery({
    queryKey: ["balances", "quality", warehouseId, status],
    queryFn: () => unwrap(api.GET("/inventory/balances", { params: { query: { warehouse_id: warehouseId, stock_status: status } } })),
    enabled: !!warehouseId,
  });
  const { data: inspections = [] } = useQuery({
    queryKey: ["inspections", warehouseId],
    queryFn: () => unwrap(api.GET("/quality/inspections", { params: { query: { warehouse_id: warehouseId } } })),
    enabled: !!warehouseId,
  });

  return (
    <>
      <PageHeader eyebrow="انبار" title="بازرسی کیفی و قرنطینه"
        subtitle="فقط کالای «تأییدشده» قابل تخصیص به سفارش است؛ آزادسازی کالای توقیف یا مردود فقط با ادمین سازمان." />
      <Card className="mb-5">
        <div className="flex flex-wrap items-center gap-3 border-b border-border p-4">
          <div className="w-64"><WarehousePicker choice={choice} /></div>
          <div className="overflow-x-auto">
            <SegmentedControl value={status} onChange={setStatus} options={HELD.map(s => ({ value: s, label: STOCK_STATUS[s].label }))} />
          </div>
        </div>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : !balances?.length ? (
          <EmptyState icon={<ShieldCheck className="size-5" />} title={`کالای «${STOCK_STATUS[status].label}» در این انبار نیست`} text={STOCK_STATUS[status].hint} />
        ) : (
          <Table testId="quality-table">
            <thead><tr><th>کالا</th><th>وضعیت</th><th>محل</th><th>بچ / سریال</th><th>انقضا</th><th>مالک</th><th>مقدار</th><th className="w-1" /></tr></thead>
            <tbody>
              {balances.map(b => (
                <tr key={b.balance_id} data-testid="quality-row" data-sku={b.product_sku}>
                  <td><div className="font-medium">{b.product_name}</div><div className="font-mono text-xs text-muted">{b.product_sku}</div></td>
                  <td><StatusBadge status={b.stock_status} /></td>
                  <td className="font-mono text-xs ltr text-start">{b.location_code ?? "بدون محل"}</td>
                  <td className="font-mono text-xs ltr text-start">{[b.lot_number, b.serial_number].filter(Boolean).join(" / ") || "—"}</td>
                  <td className="text-xs">{b.expiry_date ? <span className={b.expired ? "text-danger" : ""}>{faDate(b.expiry_date)}</span> : "—"}</td>
                  <td className="text-xs">{b.owner_name ?? "سازمان"}</td>
                  <td className="tnum font-bold">{faNumber(b.quantity)}</td>
                  <td><Button size="sm" variant="soft" icon={<ClipboardCheck className="size-3.5" />} onClick={() => setTarget(b)} data-testid="quality-inspect">بازرسی</Button></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <Card>
        <CardHeader title="سوابق بازرسی" subtitle="هر بازرسی یک سند «بازرسی کیفی» (QI) با بازرس، زمان و نتیجه‌ها دارد." icon={<ClipboardCheck className="size-4" />} />
        {!inspections.length ? <EmptyState title="هنوز بازرسی ثبت نشده" /> : (
          <Table testId="inspections-table">
            <thead><tr><th>کد</th><th>کالا</th><th>از وضعیت</th><th>نتیجه</th><th>محل / بچ</th><th>بازرس</th><th>زمان</th></tr></thead>
            <tbody>
              {inspections.map(i => (
                <tr key={i.id} data-testid="inspection-row">
                  <td><div className="font-mono text-xs font-semibold ltr text-start">{i.code}</div><div className="font-mono text-[11px] text-muted ltr text-start">{i.document_code}</div></td>
                  <td>{i.product_name}</td>
                  <td><StatusBadge status={i.from_status} /></td>
                  <td><div className="flex flex-wrap gap-1">{i.results.map(r => (
                    <Badge key={r.status} tone={STOCK_STATUS[r.status as StockStatus]?.tone ?? "muted"}>{r.status_label} {faNumber(r.quantity)}</Badge>
                  ))}</div>{i.results.some(r => r.reason) && <div className="mt-1 text-xs text-muted">{i.results.map(r => r.reason).filter(Boolean).join("؛ ")}</div>}</td>
                  <td className="font-mono text-xs ltr text-start">{[i.location_code, i.lot_number].filter(Boolean).join(" · ") || "—"}</td>
                  <td className="text-xs">{i.inspector_name ?? "—"}</td>
                  <td className="whitespace-nowrap text-xs text-text-2">{faDateTime(i.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <InspectModal onClose={() => setTarget(null)} target={target && {
        product_id: target.product_id, product_name: target.product_name, warehouse_id: target.warehouse_id,
        from_status: target.stock_status, quantity: target.quantity, location_id: target.location_id ?? null,
        location_code: target.location_code ?? null, lot_number: target.lot_number ?? null,
      }} />
    </>
  );
}
