/**
 * کاردکس (کارت گردش کالا — فصل ۱۰): مانده اول دوره، ورود، خروج و مانده پس از هر سند برای یک کالا،
 * با محدود کردن به انبار، محل، بچ، وضعیت کیفی و بازه تاریخ. جابه‌جایی‌های داخلی که در محدوده خالص صفرند
 * (مثلاً جانمایی در کاردکس کل انبار) پنهان‌اند، مگر «نمایش جابه‌جایی‌های داخلی» روشن باشد.
 */
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ClipboardList, Printer } from "lucide-react";
import { api, unwrap } from "@/api/client";
import { useProducts } from "@/hooks/data";
import { STOCK_STATUS } from "@/lib/labels";
import { faDateTime, faNumber } from "@/lib/format";
import { DateField } from "@/ui/datetime";
import { Button, Card, Checkbox, EmptyState, ErrorState, Field, Input, PageHeader, Select, StatCard, Table, TableSkeleton } from "@/ui/primitives";
import { DocTypeBadge } from "./DocumentsPage";
import { LocationSelect, STATUS_KEYS, WarehousePicker, useWarehouseChoice } from "../warehouse/shared";

export default function StockCardPage() {
  const [params, setParams] = useSearchParams();
  const { data: products = [] } = useProducts();
  const choice = useWarehouseChoice(params.get("warehouse") ?? "", false);
  const productId = params.get("product") ? Number(params.get("product")) : null;
  const [location, setLocation] = useState("");
  const [lot, setLot] = useState("");
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [internal, setInternal] = useState(false);
  const warehouseId = choice.value ? Number(choice.value) : null;
  const query = {
    product_id: productId!, warehouse_id: warehouseId, location_id: location ? Number(location) : null, lot_number: lot || null,
    stock_status: (status || null) as never, date_from: from || null, date_to: to || null, include_internal: internal,
  };
  const { data: card, isLoading, error, refetch } = useQuery({
    queryKey: ["stock-card", query],
    queryFn: () => unwrap(api.GET("/inventory/stock-card", { params: { query } })),
    enabled: productId != null,
    placeholderData: keepPreviousData,
  });
  const setProduct = (v: string) => { const next = new URLSearchParams(params); if (v) next.set("product", v); else next.delete("product"); setParams(next, { replace: true }); };

  return (
    <>
      <PageHeader eyebrow="انبار" title="کاردکس کالا"
        subtitle="کارت گردش کالا از دفتر غیرقابل‌تغییر: هر ردیف یک سند قطعی با ورود، خروج و مانده پس از آن."
        actions={card && <Button variant="secondary" icon={<Printer className="size-4" />} onClick={() => window.print()}>چاپ</Button>} />
      <Card className="mb-5">
        <div className="grid gap-3 p-4 md:grid-cols-4">
          <Field label="کالا" className="md:col-span-2">
            <Select value={productId ? String(productId) : ""} onChange={e => setProduct(e.target.value)} searchable data-testid="card-product">
              <option value="">انتخاب کالا...</option>{products.map(p => <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>)}
            </Select>
          </Field>
          <Field label="انبار"><WarehousePicker choice={choice} allowAll={!choice.isManager} testId="card-warehouse" /></Field>
          <Field label="محل"><LocationSelect warehouseId={warehouseId} value={location} onChange={setLocation} empty="همه محل‌ها" testId="card-location" /></Field>
          <Field label="بچ"><Input className="ltr uppercase" maxLength={64} value={lot} onChange={e => setLot(e.target.value.toUpperCase())} /></Field>
          <Field label="وضعیت کیفی">
            <Select value={status} onChange={e => setStatus(e.target.value)}><option value="">همه وضعیت‌ها</option>
              {STATUS_KEYS.map(s => <option key={s} value={s}>{STOCK_STATUS[s].label}</option>)}</Select>
          </Field>
          <Field label="از تاریخ"><DateField value={from} onChange={setFrom} /></Field>
          <Field label="تا تاریخ (بدون شامل)"><DateField value={to} onChange={setTo} /></Field>
          <div className="md:col-span-4"><Checkbox label="نمایش جابه‌جایی‌های داخلی (جانمایی، تغییر وضعیت) که در این محدوده خالص صفرند" checked={internal} onChange={e => setInternal(e.target.checked)} /></div>
        </div>
      </Card>
      {productId == null ? (
        <Card><EmptyState icon={<ClipboardList className="size-5" />} title="کالا را انتخاب کنید" text="کاردکس هر کالا از دفتر گردش ساخته می‌شود." /></Card>
      ) : isLoading ? <Card><TableSkeleton /></Card> : error ? <Card><ErrorState error={error} onRetry={refetch} /></Card> : card && (
        <>
          <div className="mb-5 grid grid-cols-2 gap-4 lg:grid-cols-4" data-testid="card-totals">
            <StatCard label="مانده اول دوره" value={faNumber(card.opening_balance)} tone="muted" />
            <StatCard label="جمع ورود" value={faNumber(card.total_in)} tone="success" />
            <StatCard label="جمع خروج" value={faNumber(card.total_out)} tone="danger" />
            <StatCard label="مانده پایان دوره" value={<span data-testid="card-closing">{faNumber(card.closing_balance)}</span>} tone="brand" hint={card.unit} />
          </div>
          <Card>
            {!card.rows.length ? <EmptyState title="در این بازه گردشی نیست" /> : (
              <Table testId="stock-card-table">
                <thead><tr><th>زمان</th><th>سند</th><th>نوع</th><th>شرح</th><th>محل / بچ</th><th>ورود</th><th>خروج</th><th>مانده</th></tr></thead>
                <tbody>
                  {card.truncated && <tr><td colSpan={8} className="text-center text-xs text-warning">فقط آخرین ردیف‌ها نمایش داده شده‌اند؛ بازه تاریخ را کوتاه‌تر کنید.</td></tr>}
                  {card.rows.map(r => (
                    <tr key={r.document_id} data-testid="card-row" data-type={r.doc_type ?? ""}>
                      <td className="whitespace-nowrap text-xs text-text-2">{faDateTime(r.date)}</td>
                      <td className="font-mono text-xs font-semibold ltr text-start">{r.document_code}</td>
                      <td>{r.doc_type && <DocTypeBadge type={r.doc_type} />}</td>
                      <td className="max-w-64 text-xs text-text-2">{r.partner_name ? `${r.partner_name} · ` : ""}{r.description}</td>
                      <td className="font-mono text-[11px] ltr text-start">{[...r.locations, ...r.lots].join(" · ") || "—"}</td>
                      <td className="tnum text-success">{r.quantity_in ? `+${faNumber(r.quantity_in)}` : ""}</td>
                      <td className="tnum text-danger">{r.quantity_out ? `−${faNumber(r.quantity_out)}` : ""}</td>
                      <td className="tnum font-bold">{faNumber(r.balance)}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </>
      )}
    </>
  );
}
