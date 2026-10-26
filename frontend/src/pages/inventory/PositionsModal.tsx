/**
 * وضعیت مقدار یک کالا در هر انبار (فیزیکی، قابل تخصیص، رزرو، قابل وعده، در انتظار بازرسی، قرنطینه، در راه)
 * و موجودی ریز آن به تفکیک محل × بچ × سریال × مالک × انقضا.
 */
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { faDate, faNumber } from "@/lib/format";
import { Modal, Tooltip } from "@/ui/overlays";
import { Badge, EmptyState } from "@/ui/primitives";
import { StatusBadge } from "../warehouse/shared";

const COLUMNS: [string, string, string][] = [
  ["on_hand", "فیزیکی", "همه وضعیت‌ها، شامل رزروشده"],
  ["allocatable", "قابل تخصیص", "تأییدشده در محل نگهداری/برداشت، منقضی‌نشده، مال سازمان"],
  ["reserved", "رزرو", "سفارش‌های باز"],
  ["available", "قابل وعده", "قابل تخصیص منهای رزرو"],
  ["pending_inspection", "در انتظار بازرسی", "هنوز بازرسی نشده"],
  ["quarantine", "قرنطینه / نگه‌داشته", "قرنطینه، توقیف، مردود، معیوب، آسیب‌دیده"],
  ["not_put_away", "در انتظار جانمایی", "تأییدشده در محل تخلیه/آماده‌سازی"],
  ["picked", "برداشت‌شده", "در محل آماده‌سازی، منتظر ارسال سفارش خودش"],
  ["in_transit", "در راه", "انبار در راه یا رسید انتقال باز"],
];

export function PositionsModal({ product, onClose }: { product: { id: number; name: string; sku: string } | null; onClose: () => void }) {
  const { data: positions = [], isLoading } = useQuery({
    queryKey: ["positions", product?.id],
    queryFn: () => unwrap(api.GET("/inventory/positions", { params: { query: { product_id: product!.id } } })),
    enabled: product != null,
  });
  const { data: balances = [] } = useQuery({
    queryKey: ["balances", "product", product?.id],
    queryFn: () => unwrap(api.GET("/inventory/balances", { params: { query: { product_id: product!.id } } })),
    enabled: product != null,
  });
  return (
    <Modal open={product != null} onClose={onClose} size="xl" testId="positions-modal" title={product ? `موجودی ${product.name}` : "موجودی"}
      description="همه اعداد از دفتر گردش کالا؛ فقط «قابل وعده» به سفارش جدید می‌رسد.">
      {isLoading ? <div className="h-40 animate-pulse rounded-xl bg-surface-2" /> : !positions.length ? <EmptyState title="این کالا در هیچ انباری موجودی ندارد" /> : (
        <div className="space-y-5">
          <div className="overflow-x-auto">
            <table className="table-base" data-testid="positions-table">
              <thead><tr><th>انبار</th>{COLUMNS.map(([k, label, hint]) => <th key={k}><Tooltip content={hint}><span>{label}</span></Tooltip></th>)}</tr></thead>
              <tbody>
                {positions.map(p => (
                  <tr key={p.warehouse_id} data-testid="position-row" data-allocatable={p.allocatable} data-available={p.available}>
                    <td className="font-medium">{p.warehouse_name}{p.warehouse_type === "transit" && <Badge tone="violet" className="ms-1">در راه</Badge>}</td>
                    {COLUMNS.map(([k]) => {
                      const value = (p as unknown as Record<string, number>)[k];
                      return <td key={k} className={`tnum ${k === "available" ? "font-bold text-success" : ""}`}>{value ? faNumber(value) : "—"}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <div className="mb-2 text-sm font-semibold">موجودی ریز</div>
            <div className="overflow-x-auto">
              <table className="table-base" data-testid="balances-table">
                <thead><tr><th>انبار</th><th>محل</th><th>وضعیت</th><th>بچ / سریال</th><th>انقضا</th><th>مالک</th><th>مقدار</th><th /></tr></thead>
                <tbody>
                  {balances.map(b => (
                    <tr key={b.balance_id} data-testid="balance-row">
                      <td className="text-xs">{b.warehouse_name}</td>
                      <td className="font-mono text-xs ltr text-start">{b.location_code ?? "بدون محل"}</td>
                      <td><StatusBadge status={b.stock_status} /></td>
                      <td className="font-mono text-xs ltr text-start">{[b.lot_number, b.serial_number].filter(Boolean).join(" / ") || "—"}</td>
                      <td className={`text-xs ${b.expired ? "text-danger" : ""}`}>{b.expiry_date ? faDate(b.expiry_date) : "—"}</td>
                      <td className="text-xs">{b.owner_name ?? "سازمان"}</td>
                      <td className="tnum font-bold">{faNumber(b.quantity)}</td>
                      <td>{b.allocatable ? <Badge tone="success">قابل تخصیص</Badge> : b.expired ? <Badge tone="danger">منقضی</Badge> : null}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
