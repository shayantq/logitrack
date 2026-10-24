import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Boxes, Download, FileSpreadsheet, FileText, History, Layers, PackagePlus, PackageSearch, Search, Trash2, Upload } from "lucide-react";
import { api, errorMessage, isServerError, newIdempotencyKey, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { StockBadge } from "@/components/StatusBadges";
import { useToast } from "@/components/Toast";
import { useAsyncExport, usePartners, useProducts, useWarehouses } from "@/hooks/data";
import { STOCK_STATUS, WAREHOUSE_TYPES, type StockStatus } from "@/lib/labels";
import { faNumber } from "@/lib/format";
import { Modal, Tooltip } from "@/ui/overlays";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, Select, Table, TableSkeleton, Textarea, cn } from "@/ui/primitives";
import { DateField } from "@/ui/datetime";
import { LocationSelect } from "../warehouse/shared";
import { PositionsModal } from "./PositionsModal";
import { useDeepLink } from "@/hooks/useDeepLink";
import { CatalogImportModal, ProductCatalogModal, UNITS, downloadFile } from "./CatalogModals";
import { confirmDialog } from "@/ui/dialogs";

type Product = Schemas["ProductResponse"];
const STATUSES = Object.keys(STOCK_STATUS) as StockStatus[];

function useInvalidateStock() {
  const queryClient = useQueryClient();
  return () => ["products", "movements", "documents", "stock-buckets", "stats", "notifications", "catalog-product"]
    .forEach(key => queryClient.invalidateQueries({ queryKey: [key] }));
}

function ProductModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const me = useMe();
  const toast = useToast();
  const invalidate = useInvalidateStock();
  const { data: warehouses = [] } = useWarehouses();
  const empty = { name: "", sku: "", barcode: "", price: "0", weight: "1", quantity: "0", warehouse: "", category: "", unit: "عدد",
    origin: "domestic" as "domestic" | "imported", country: "", subsidy: "" };
  const [form, setForm] = useState(empty);
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/inventory/products", { body: {
      name: form.name, sku: form.sku, barcode: form.barcode.trim() || null, price: Number(form.price), weight_kg: Number(form.weight),
      initial_quantity: Number(form.quantity), warehouse_id: form.warehouse ? Number(form.warehouse) : null,
      category: form.category || null, unit: form.unit, origin: form.origin, origin_country: form.origin === "imported" ? form.country || null : null,
      subsidy_percent: Number(form.subsidy) || 0, lot_tracked: false, serial_tracked: false, expiry_tracked: false, inspection_required: false,
    } })),
    onSuccess: () => { toast.success("کالا ثبت شد."); invalidate(); onClose(); setForm(empty); },
    onError: e => toast.error(errorMessage(e)),
  });
  const set = (k: keyof typeof empty) => (e: { target: { value: string } }) => setForm(f => ({ ...f, [k]: e.target.value }));
  return (
    <Modal open={open} onClose={onClose} title="تعریف کالای جدید" description="کد کالا (SKU) بعد از ثبت قابل تغییر نیست." footer={<>
      <Button variant="secondary" onClick={onClose}>انصراف</Button>
      <Button type="submit" form="product-form" loading={create.isPending}>ثبت کالا</Button>
    </>}>
      <form id="product-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
        <Field label="نام کالا *" className="sm:col-span-2"><Input required value={form.name} onChange={set("name")} /></Field>
        <Field label="کد کالا (SKU) *" hint="یکتا، بدون فاصله"><Input className="ltr" required pattern="\S+" value={form.sku} onChange={set("sku")} /></Field>
        <Field label="بارکد" hint="اختیاری — در کل سازمان یکتاست"><Input className="ltr" inputMode="numeric" value={form.barcode} onChange={set("barcode")} /></Field>
        <Field label="قیمت پایه (ریال)"><Input type="number" min={0} step="0.01" value={form.price} onChange={set("price")} /></Field>
        <Field label="درصد یارانه" hint="اختیاری — قیمت فروش = قیمت پایه × (۱ − درصد)"><Input type="number" min={0} max={99} step="0.1" value={form.subsidy} onChange={set("subsidy")} /></Field>
        <Field label="گروه کالا" hint="اختیاری"><Input value={form.category} onChange={set("category")} /></Field>
        <Field label="واحد پایه"><Select value={form.unit} onChange={set("unit")}>{UNITS.map(u => <option key={u} value={u}>{u}</option>)}</Select></Field>
        <Field label="مبدأ"><Select value={form.origin} onChange={set("origin")}><option value="domestic">داخلی</option><option value="imported">وارداتی</option></Select></Field>
        {form.origin === "imported" && <Field label="کشور مبدأ"><Input value={form.country} onChange={set("country")} /></Field>}
        <Field label="وزن ناخالص هر واحد (کیلوگرم)"><Input type="number" min={0.01} step="0.01" value={form.weight} onChange={set("weight")} /></Field>
        <Field label="موجودی اولیه"><Input type="number" min={0} value={form.quantity} onChange={set("quantity")} /></Field>
        {me.role === "org_admin" ? (
          <Field label="انبار" className="sm:col-span-2">
            <Select value={form.warehouse} onChange={set("warehouse")}><option value="">—</option>
              {warehouses.filter(w => w.holds_stock && w.is_active).map(w => <option key={w.id} value={w.id}>{w.name}</option>)}</Select>
          </Field>
        ) : <p className="text-xs text-muted sm:col-span-2">موجودی اولیه در انبار شما ثبت می‌شود.</p>}
      </form>
    </Modal>
  );
}

type MovementKind = "receipt" | "damage" | "adjustment" | "transfer" | "status";
const KINDS: { value: MovementKind; label: string; hint: string }[] = [
  { value: "receipt", label: "رسید ورود کالا", hint: "خرید یا تحویل از تأمین‌کننده" },
  { value: "damage", label: "ضایعات / کسری", hint: "از موجودی کم می‌شود — دلیل الزامی" },
  { value: "adjustment", label: "اصلاح موجودی", hint: "مثبت یا منفی — دلیل الزامی" },
  { value: "transfer", label: "انتقال", hint: "به انبار دیگر سازمان" },
  { value: "status", label: "تغییر وضعیت کیفی", hint: "مثلاً آزادسازی از قرنطینه" },
];

function MovementModal({ product, onClose, products }: { product: Product | null | undefined; onClose: () => void; products: Product[] }) {
  const me = useMe();
  const toast = useToast();
  const invalidate = useInvalidateStock();
  const { data: warehouses = [] } = useWarehouses();
  const isManager = me.role === "warehouse_manager";
  const [kind, setKind] = useState<MovementKind>("receipt");
  const [productId, setProductId] = useState("");
  const [warehouse, setWarehouse] = useState("");
  const [toWarehouse, setToWarehouse] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [uom, setUom] = useState("");
  const [reason, setReason] = useState("");
  const [status, setStatus] = useState<StockStatus | "">("");
  const [toStatus, setToStatus] = useState<StockStatus>("available");
  const [supplier, setSupplier] = useState("");
  const [externalRef, setExternalRef] = useState("");
  const [location, setLocation] = useState("");
  const [toLocation, setToLocation] = useState("");
  const [lot, setLot] = useState("");
  const [expiry, setExpiry] = useState("");
  const [serials, setSerials] = useState("");
  const [requestKey, setRequestKey] = useState(newIdempotencyKey);
  const { data: suppliers = [] } = usePartners("supplier", product !== undefined && kind === "receipt");
  const selectedProduct = productId || (product ? String(product.id) : "");
  const { data: detail } = useQuery({
    queryKey: ["catalog-product", Number(selectedProduct)],
    queryFn: () => unwrap(api.GET("/catalog/products/{product_id}", { params: { path: { product_id: Number(selectedProduct) } } })),
    enabled: !!selectedProduct,
  });
  const fromWarehouse = isManager ? String(me.warehouse_id ?? "") : warehouse;
  const reasonRequired = kind === "damage" || kind === "adjustment" || kind === "status";
  const stockWarehouses = warehouses.filter(w => w.holds_stock && (w.is_active || kind !== "receipt"));
  const chosenWarehouse = warehouses.find(w => String(w.id) === fromWarehouse);
  const receiptStatusHint = kind === "receipt" && chosenWarehouse && !status
    ? `پیش‌فرض این انبار: ${STOCK_STATUS[(chosenWarehouse.type === "quarantine" || chosenWarehouse.type === "returns") ? "quarantine" : "available"].label}` : undefined;

  function close() {
    setKind("receipt"); setProductId(""); setWarehouse(""); setToWarehouse(""); setQuantity("1"); setUom(""); setReason("");
    setStatus(""); setToStatus("available"); setSupplier(""); setExternalRef(""); setLocation(""); setToLocation(""); setLot("");
    setExpiry(""); setSerials(""); setRequestKey(newIdempotencyKey()); onClose();
  }
  const incoming = kind === "receipt" || (kind === "adjustment" && Number(quantity) > 0);
  const submit = useMutation({
    mutationFn: async () => {
      const header = { "Idempotency-Key": requestKey };
      const common = { product_id: Number(selectedProduct), quantity: Number(quantity), reason: reason || null, uom: uom || null };
      const where = { location_id: location ? Number(location) : null, lot_number: lot || null };
      if (kind === "transfer") {
        return unwrap(api.POST("/inventory/transfers", { params: { header }, body: {
          ...common, from_warehouse_id: Number(fromWarehouse), to_warehouse_id: Number(toWarehouse), stock_status: status || "available",
          from_location_id: where.location_id, to_location_id: toLocation ? Number(toLocation) : null, lot_number: where.lot_number } }));
      }
      if (kind === "status") {
        return unwrap(api.POST("/inventory/status-changes", { params: { header }, body: {
          ...common, ...where, reason: reason, warehouse_id: fromWarehouse ? Number(fromWarehouse) : null,
          from_status: status || "quarantine", to_status: toStatus } }));
      }
      return unwrap(api.POST("/inventory/movements", { params: { header }, body: {
        ...common, ...where, movement_type: kind, warehouse_id: fromWarehouse ? Number(fromWarehouse) : null, stock_status: status || null,
        partner_id: kind === "receipt" && supplier ? Number(supplier) : null, external_ref: kind === "receipt" ? externalRef || null : null,
        expiry_date: incoming && expiry ? expiry : null,
        serial_numbers: incoming ? serials.split(/[\s,،]+/).map(s => s.trim()).filter(Boolean) : [],
      } }));
    },
    onSuccess: () => { toast.success(kind === "status" ? "وضعیت کیفی تغییر کرد." : "گردش کالا ثبت شد."); invalidate(); close(); },
    onError: e => { toast.error(errorMessage(e)); if (isServerError(e)) setRequestKey(newIdempotencyKey()); },
  });
  const units = [detail?.unit ?? "", ...(detail?.uoms ?? []).map(u => u.name)].filter(Boolean);

  return (
    <Modal open={product !== undefined} onClose={close} title="ثبت سند انبار" size="lg" testId="movement-modal"
      description="هر تغییر موجودی یک سند قطعی با کاربر، زمان و دلیل است؛ اشتباه با «سند برگشت» اصلاح می‌شود، نه حذف."
      footer={<><Button variant="secondary" onClick={close}>انصراف</Button><Button type="submit" form="movement-form" loading={submit.isPending}>ثبت سند</Button></>}>
      <form id="movement-form" className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); submit.mutate(); }}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5" role="radiogroup" data-testid="movement-kind">
          {KINDS.map(k => (
            <button key={k.value} type="button" role="radio" aria-checked={kind === k.value} data-kind={k.value}
              onClick={() => { setKind(k.value); setStatus(k.value === "status" ? "quarantine" : ""); }}
              className={`rounded-xl border p-3 text-start transition ${kind === k.value ? "border-brand bg-brand-soft" : "border-border hover:bg-surface-2"}`}>
              <div className="text-sm font-semibold">{k.label}</div>
              <div className="mt-0.5 text-[11px] leading-4 text-muted">{k.hint}</div>
            </button>
          ))}
        </div>
        <Field label="کالا">
          <Select required value={selectedProduct} onChange={e => { setProductId(e.target.value); setUom(""); }} data-testid="movement-product">
            <option value="">انتخاب کالا...</option>
            {products.map(p => <option key={p.id} value={p.id}>{p.name} ({p.sku}) — موجودی: {faNumber(p.stock)}</option>)}
          </Select>
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={kind === "transfer" ? "انبار مبدأ" : "انبار"} hint={isManager ? "مدیر انبار فقط روی انبار خودش کار می‌کند." : receiptStatusHint}>
            <Select value={fromWarehouse} disabled={isManager} required={kind === "transfer"} onChange={e => setWarehouse(e.target.value)} data-testid="movement-warehouse">
              <option value="">{kind === "transfer" ? "انتخاب کنید..." : "خودکار (اگر کالا فقط در یک انبار است)"}</option>
              {stockWarehouses.map(w => <option key={w.id} value={w.id}>{w.name} — {WAREHOUSE_TYPES[w.type]?.label ?? w.type}</option>)}
            </Select>
          </Field>
          {kind === "transfer" ? (
            <Field label="انبار مقصد">
              <Select required value={toWarehouse} onChange={e => setToWarehouse(e.target.value)}>
                <option value="">انتخاب کنید...</option>
                {stockWarehouses.filter(w => String(w.id) !== fromWarehouse && w.is_active).map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
              </Select>
            </Field>
          ) : (
            <Field label={kind === "status" ? "از وضعیت" : "وضعیت کیفی"} hint={kind === "receipt" ? "خالی = بر اساس نوع انبار" : undefined}>
              <Select value={status} onChange={e => setStatus(e.target.value as StockStatus | "")} data-testid="movement-status">
                {kind !== "status" && <option value="">{kind === "receipt" ? "خودکار" : STOCK_STATUS.available.label}</option>}
                {STATUSES.filter(s => kind === "status" || kind === "receipt" || s !== "available").map(s => <option key={s} value={s}>{STOCK_STATUS[s].label}</option>)}
              </Select>
            </Field>
          )}
        </div>
        {kind === "status" && (
          <Field label="به وضعیت">
            <Select value={toStatus} onChange={e => setToStatus(e.target.value as StockStatus)} data-testid="movement-to-status">
              {STATUSES.filter(s => s !== (status || "quarantine")).map(s => <option key={s} value={s}>{STOCK_STATUS[s].label} — {STOCK_STATUS[s].hint}</option>)}
            </Select>
          </Field>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="تعداد" hint={kind === "adjustment" ? "مثبت = افزایش، منفی = کاهش" : undefined}>
            <Input type="number" required min={kind === "adjustment" ? undefined : 1} value={quantity} onChange={e => setQuantity(e.target.value)} data-testid="movement-qty" />
          </Field>
          {units.length > 1 ? (
            <Field label="واحد" hint={uom ? `هر ${uom} = ${faNumber(detail?.uoms.find(u => u.name === uom)?.factor ?? 1)} ${detail?.unit}` : "به واحد پایه ثبت می‌شود"}>
              <Select value={uom} onChange={e => setUom(e.target.value)} data-testid="movement-uom">
                {units.map((u, i) => <option key={u} value={i === 0 ? "" : u}>{u}</option>)}
              </Select>
            </Field>
          ) : <div className="hidden sm:block" />}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={kind === "transfer" ? "از محل" : "محل"} hint={incoming ? "خالی = بدون محل" : "خالی = برداشت خودکار (اول‌منقضی، اول‌خروج)"}>
            <LocationSelect warehouseId={fromWarehouse ? Number(fromWarehouse) : null} value={location} onChange={setLocation}
              empty={incoming ? "بدون محل" : "خودکار"} testId="movement-location" />
          </Field>
          {kind === "transfer" ? (
            <Field label="به محل" hint="در انبار مقصد — خالی = بدون محل">
              <LocationSelect warehouseId={toWarehouse ? Number(toWarehouse) : null} value={toLocation} onChange={setToLocation} />
            </Field>
          ) : (detail?.lot_tracked || lot) ? (
            <Field label={incoming && detail?.lot_tracked && kind === "receipt" ? "شماره بچ *" : "بچ"} hint={incoming ? undefined : "خالی = هر بچی (FEFO)"}>
              <Input className="ltr uppercase" required={kind === "receipt" && !!detail?.lot_tracked} maxLength={64} value={lot} onChange={e => setLot(e.target.value)} data-testid="movement-lot" />
            </Field>
          ) : <div className="hidden sm:block" />}
          {incoming && detail?.expiry_tracked && (
            <Field label="تاریخ انقضا *"><DateField required={kind === "receipt"} value={expiry} onChange={setExpiry} testId="movement-expiry" /></Field>
          )}
          {incoming && detail?.serial_tracked && (
            <Field label="شماره سریال‌ها *" hint="به تعداد واحدها؛ با فاصله یا خط جدید" className="sm:col-span-2">
              <Textarea required={kind === "receipt"} className="ltr font-mono" rows={2} value={serials} onChange={e => setSerials(e.target.value)} />
            </Field>
          )}
        </div>
        {kind === "receipt" && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="تأمین‌کننده" hint="اختیاری">
              <Select value={supplier} onChange={e => setSupplier(e.target.value)} data-testid="movement-supplier">
                <option value="">—</option>{suppliers.map(s => <option key={s.id} value={s.id}>{s.name} ({s.code})</option>)}
              </Select>
            </Field>
            <Field label="شماره فاکتور / بارنامه" hint="اختیاری"><Input className="ltr" maxLength={64} value={externalRef} onChange={e => setExternalRef(e.target.value)} /></Field>
          </div>
        )}
        <Field label={reasonRequired ? "دلیل (الزامی)" : "توضیح (اختیاری)"}>
          <Input required={reasonRequired} minLength={reasonRequired ? 3 : undefined} maxLength={500}
            placeholder={kind === "status" ? "مثلاً بازرسی کیفی تأیید شد" : "مثلاً علت کسری"} value={reason} onChange={e => setReason(e.target.value)} />
        </Field>
      </form>
    </Modal>
  );
}

function StockCell({ p }: { p: Product }) {
  const held = Object.entries(p.held_stock ?? {}).filter(([, q]) => q > 0);
  return (
    <div className="flex flex-wrap items-center gap-1" data-testid="product-stock" data-free={p.free_stock} data-reserved={p.reserved}>
      <StockBadge stock={p.stock ?? 0} />
      {p.reserved > 0 && <Tooltip content={`موجودی آزاد: ${faNumber(p.free_stock)}`}><Badge tone="info">رزرو {faNumber(p.reserved)}</Badge></Tooltip>}
      {held.map(([s, q]) => <Badge key={s} tone={STOCK_STATUS[s as StockStatus]?.tone ?? "muted"}>{STOCK_STATUS[s as StockStatus]?.label ?? s} {faNumber(q)}</Badge>)}
    </div>
  );
}

export default function InventoryPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const invalidate = useInvalidateStock();
  const { data: products, isLoading, error, refetch } = useProducts();
  const [productModal, setProductModal] = useState(false);
  const [movementFor, setMovementFor] = useState<Product | null | undefined>(undefined);
  const [search, setSearch] = useState("");
  const [catalogId, setCatalogId] = useState<number | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [positionsFor, setPositionsFor] = useState<Product | null>(null);
  const exporter = useAsyncExport(toast.error, () => toast.success("گزارش آماده و دانلود شد."));
  // از اعلان «رسیدن به نقطه سفارش»: ردیف همان کالا برجسته می‌شود (جستجو پاک می‌شود تا ردیف دیده شود)
  const flash = useDeepLink("product", { ready: !!products, onHit: () => setSearch("") });
  const remove = useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE("/inventory/products/{product_id}", { params: { path: { product_id: id } } })),
    onSuccess: () => { toast.success("کالا حذف شد."); invalidate(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const term = search.trim();
  const visible = (products ?? []).filter(p => !term || p.name.includes(term) || p.sku.toLowerCase().includes(term.toLowerCase())
    || (p.category ?? "").includes(term) || (p.barcode ?? "") === term);

  return (
    <>
      <PageHeader eyebrow="انبار" title="انبار و کالاها" subtitle="کاتالوگ کالا و موجودی انبارها — موجودی سالم، رزرو سفارش‌ها و کالای قرنطینه/توقیف جدا"
        actions={<>
          <Button variant="secondary" size="sm" icon={<FileSpreadsheet className="size-4" />} loading={exporter.running === "/reports/export/inventory/excel"}
            onClick={() => exporter.run("/reports/export/inventory/excel", "Pasineh_Inventory.xlsx")}>اکسل</Button>
          <Button variant="secondary" size="sm" icon={<FileText className="size-4" />} loading={exporter.running === "/reports/export/inventory/pdf"}
            onClick={() => exporter.run("/reports/export/inventory/pdf", "Pasineh_Inventory.pdf")}>PDF</Button>
          <Button variant="secondary" size="sm" icon={<Download className="size-4" />} data-testid="catalog-export"
            onClick={() => downloadFile("/catalog/export", "Pasineh_Catalog.xlsx").catch(e => toast.error(errorMessage(e)))}>خروجی کاتالوگ</Button>
          <Button variant="secondary" size="sm" icon={<Upload className="size-4" />} onClick={() => setImportOpen(true)} data-testid="catalog-import-open">ورود از اکسل</Button>
          <Button variant="soft" icon={<ArrowLeftRight className="size-4" />} onClick={() => setMovementFor(null)} data-testid="new-movement">ثبت سند انبار</Button>
          <Button icon={<PackagePlus className="size-4" />} onClick={() => setProductModal(true)}>کالای جدید</Button>
        </>} />
      <Card>
        <div className="border-b border-border p-4">
          <div className="relative max-w-sm">
            <Search className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" />
            <Input className="pr-10" placeholder="جستجوی نام، کد یا بارکد کالا" value={search} onChange={e => setSearch(e.target.value)} />
          </div>
        </div>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : visible.length === 0 ? (
          <EmptyState icon={<PackageSearch className="size-5" />} title={term ? "کالایی با این مشخصات نیست" : "هنوز کالایی ثبت نشده"}
            action={!term && <Button size="sm" onClick={() => setProductModal(true)}>تعریف اولین کالا</Button>} />
        ) : (
          <Table testId="products-table">
            <thead><tr><th>کالا</th><th>SKU</th><th>گروه / مبدأ</th><th>موجودی</th><th>وزن</th><th>قیمت فروش (ریال)</th><th className="w-1" /></tr></thead>
            <tbody>
              {visible.map(p => (
                <tr key={p.id} data-testid="product-row" data-sku={p.sku} data-focus={`product-${p.id}`} className={cn(flash === p.id && "focus-flash", !p.is_active && "opacity-60")}>
                  <td>
                    <button type="button" className="text-start font-medium decoration-dotted underline-offset-4 hover:text-brand hover:underline" onClick={() => setCatalogId(p.id)} data-testid="product-open">{p.name}</button>
                    {p.variant_label && <Badge tone="violet" className="ms-1.5"><Layers className="size-3" />{p.variant_label}</Badge>}
                    {!p.is_active && <Badge className="ms-1.5">بایگانی</Badge>}
                  </td>
                  <td className="font-mono text-xs text-muted">{p.sku}</td>
                  <td className="text-xs text-text-2">{p.category ?? "—"}{p.origin === "imported" && <span className="ms-1 text-muted">· وارداتی{p.origin_country ? ` (${p.origin_country})` : ""}</span>}</td>
                  <td><StockCell p={p} /></td>
                  <td className="whitespace-nowrap tnum text-text-2">{faNumber(p.weight_kg)} کیلوگرم</td>
                  <td className="tnum">{faNumber(p.price)}{p.subsidy_percent > 0 && <Badge tone="success" className="ms-1.5">یارانه {faNumber(p.subsidy_percent)}٪</Badge>}</td>
                  <td>
                    <div className="flex gap-1">
                      <Tooltip content="موجودی ریز و وضعیت مقدار"><Button variant="ghost" size="icon" onClick={() => setPositionsFor(p)} data-testid="product-positions"><Boxes className="size-4" /></Button></Tooltip>
                      <Tooltip content="کاردکس"><Button variant="ghost" size="icon" onClick={() => navigate(`/app/stock-card?product=${p.id}`)}><History className="size-4" /></Button></Tooltip>
                      <Tooltip content="ثبت سند"><Button variant="ghost" size="icon" onClick={() => setMovementFor(p)}><ArrowLeftRight className="size-4" /></Button></Tooltip>
                      <Tooltip content="حذف (فقط کالای بی‌سابقه)"><Button variant="ghost" size="icon" className="hover:text-danger" onClick={() => confirmDialog({ title: `کالای «${p.name}» حذف شود؟`, text: "کالایی که گردش یا سفارش دارد حذف نمی‌شود؛ آن را در مشخصات کالا غیرفعال کنید.", confirmLabel: "حذف کالا", danger: true }).then(ok => ok && remove.mutate(p.id))}><Trash2 className="size-4" /></Button></Tooltip>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <ProductModal open={productModal} onClose={() => setProductModal(false)} />
      <ProductCatalogModal productId={catalogId} onClose={() => setCatalogId(null)} onOpen={setCatalogId} />
      <CatalogImportModal open={importOpen} onClose={() => setImportOpen(false)} />
      <MovementModal product={movementFor} products={products ?? []} onClose={() => setMovementFor(undefined)} />
      <PositionsModal product={positionsFor} onClose={() => setPositionsFor(null)} />
    </>
  );
}
