import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Download, FileSpreadsheet, FileText, History, Layers, PackagePlus, PackageSearch, Search, Trash2, Upload } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { StockBadge } from "@/components/StatusBadges";
import { useToast } from "@/components/Toast";
import { useAsyncExport, useProducts, useWarehouses } from "@/hooks/data";
import { faNumber } from "@/lib/format";
import { Modal, Tooltip } from "@/ui/overlays";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, Select, Table, TableSkeleton, cn } from "@/ui/primitives";
import { useDeepLink } from "@/hooks/useDeepLink";
import { CatalogImportModal, ProductCatalogModal, UNITS, downloadFile } from "./CatalogModals";
import { confirmDialog } from "@/ui/dialogs";

type Product = Schemas["ProductResponse"];

function useInvalidateStock() {
  const queryClient = useQueryClient();
  return () => ["products", "movements", "stats", "notifications"].forEach(key => queryClient.invalidateQueries({ queryKey: [key] }));
}

function ProductModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const me = useMe();
  const toast = useToast();
  const invalidate = useInvalidateStock();
  const { data: warehouses = [] } = useWarehouses();
  const empty = { name: "", sku: "", price: "0", weight: "1", quantity: "0", warehouse: "", category: "", unit: "عدد",
    origin: "domestic" as "domestic" | "imported", country: "", subsidy: "" };
  const [form, setForm] = useState(empty);
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/inventory/products", { body: {
      name: form.name, sku: form.sku, price: Number(form.price), weight_kg: Number(form.weight),
      initial_quantity: Number(form.quantity), warehouse_id: form.warehouse ? Number(form.warehouse) : null,
      category: form.category || null, unit: form.unit, origin: form.origin, origin_country: form.origin === "imported" ? form.country || null : null,
      subsidy_percent: Number(form.subsidy) || 0,
    } })),
    onSuccess: () => { toast.success("کالا ثبت شد."); invalidate(); onClose(); setForm(empty); },
    onError: e => toast.error(errorMessage(e)),
  });
  const set = (k: keyof typeof empty) => (e: { target: { value: string } }) => setForm(f => ({ ...f, [k]: e.target.value }));
  return (
    <Modal open={open} onClose={onClose} title="تعریف کالای جدید" footer={<>
      <Button variant="secondary" onClick={onClose}>انصراف</Button>
      <Button type="submit" form="product-form" loading={create.isPending}>ثبت کالا</Button>
    </>}>
      <form id="product-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
        <Field label="نام کالا *" className="sm:col-span-2"><Input required value={form.name} onChange={set("name")} /></Field>
        <Field label="کد کالا (SKU) *"><Input className="ltr" required value={form.sku} onChange={set("sku")} /></Field>
        <Field label="قیمت پایه (ریال)"><Input type="number" min={0} step="0.01" value={form.price} onChange={set("price")} /></Field>
        <Field label="درصد یارانه" hint="اختیاری — قیمت فروش = قیمت پایه × (۱ − درصد)"><Input type="number" min={0} max={99} step="0.1" value={form.subsidy} onChange={set("subsidy")} /></Field>
        <Field label="گروه کالا" hint="اختیاری"><Input value={form.category} onChange={set("category")} /></Field>
        <Field label="واحد"><Select value={form.unit} onChange={set("unit")}>{UNITS.map(u => <option key={u} value={u}>{u}</option>)}</Select></Field>
        <Field label="مبدأ"><Select value={form.origin} onChange={set("origin")}><option value="domestic">داخلی</option><option value="imported">وارداتی</option></Select></Field>
        {form.origin === "imported" && <Field label="کشور مبدأ"><Input value={form.country} onChange={set("country")} /></Field>}
        <Field label="وزن هر واحد (کیلوگرم)"><Input type="number" min={0.01} step="0.01" value={form.weight} onChange={set("weight")} /></Field>
        <Field label="موجودی اولیه"><Input type="number" min={0} value={form.quantity} onChange={set("quantity")} /></Field>
        {me.role === "org_admin" ? (
          <Field label="انبار" className="sm:col-span-2">
            <Select value={form.warehouse} onChange={set("warehouse")}><option value="">—</option>{warehouses.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}</Select>
          </Field>
        ) : <p className="text-xs text-muted sm:col-span-2">موجودی اولیه در انبار شما ثبت می‌شود.</p>}
      </form>
    </Modal>
  );
}

type MovementKind = "receipt" | "damage" | "adjustment" | "transfer";
const KINDS: { value: MovementKind; label: string; hint: string }[] = [
  { value: "receipt", label: "ورود کالا", hint: "خرید یا تحویل از تأمین‌کننده" },
  { value: "damage", label: "ضایعات / کسری", hint: "از موجودی کم می‌شود — دلیل الزامی" },
  { value: "adjustment", label: "اصلاح موجودی", hint: "مثبت یا منفی — دلیل الزامی" },
  { value: "transfer", label: "انتقال", hint: "به انبار دیگر سازمان" },
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
  const [reason, setReason] = useState("");
  const selectedProduct = productId || (product ? String(product.id) : "");
  const fromWarehouse = isManager ? String(me.warehouse_id ?? "") : warehouse;
  const reasonRequired = kind === "damage" || kind === "adjustment";

  function close() { setKind("receipt"); setProductId(""); setWarehouse(""); setToWarehouse(""); setQuantity("1"); setReason(""); onClose(); }
  const submit = useMutation({
    mutationFn: async () => {
      const common = { product_id: Number(selectedProduct), quantity: Number(quantity), reason: reason || null };
      if (kind === "transfer") {
        return unwrap(api.POST("/inventory/transfers", { body: { ...common, from_warehouse_id: Number(fromWarehouse), to_warehouse_id: Number(toWarehouse) } }));
      }
      return unwrap(api.POST("/inventory/movements", { body: { ...common, movement_type: kind, warehouse_id: fromWarehouse ? Number(fromWarehouse) : null } }));
    },
    onSuccess: () => { toast.success("گردش کالا ثبت شد."); invalidate(); close(); },
    onError: e => toast.error(errorMessage(e)),
  });

  return (
    <Modal open={product !== undefined} onClose={close} title="ثبت گردش کالا" description="هر تغییر موجودی با کاربر، زمان و دلیل در دفتر ثبت می‌شود." testId="movement-modal"
      footer={<><Button variant="secondary" onClick={close}>انصراف</Button><Button type="submit" form="movement-form" loading={submit.isPending}>ثبت گردش</Button></>}>
      <form id="movement-form" className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); submit.mutate(); }}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" role="radiogroup" data-testid="movement-kind">
          {KINDS.map(k => (
            <button key={k.value} type="button" role="radio" aria-checked={kind === k.value} onClick={() => setKind(k.value)}
              className={`rounded-xl border p-3 text-start transition ${kind === k.value ? "border-brand bg-brand-soft" : "border-border hover:bg-surface-2"}`}>
              <div className="text-sm font-semibold">{k.label}</div>
              <div className="mt-0.5 text-[11px] leading-4 text-muted">{k.hint}</div>
            </button>
          ))}
        </div>
        <Field label="کالا">
          <Select required value={selectedProduct} onChange={e => setProductId(e.target.value)} data-testid="movement-product">
            <option value="">انتخاب کالا...</option>
            {products.map(p => <option key={p.id} value={p.id}>{p.name} ({p.sku}) — موجودی: {faNumber(p.stock)}</option>)}
          </Select>
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={kind === "transfer" ? "انبار مبدأ" : "انبار"} hint={isManager ? "مدیر انبار فقط روی انبار خودش کار می‌کند." : undefined}>
            <Select value={fromWarehouse} disabled={isManager} required={kind === "transfer"} onChange={e => setWarehouse(e.target.value)} data-testid="movement-warehouse">
              <option value="">{kind === "transfer" ? "انتخاب کنید..." : "خودکار (اگر کالا فقط در یک انبار است)"}</option>
              {warehouses.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          </Field>
          {kind === "transfer" ? (
            <Field label="انبار مقصد">
              <Select required value={toWarehouse} onChange={e => setToWarehouse(e.target.value)}>
                <option value="">انتخاب کنید...</option>
                {warehouses.filter(w => String(w.id) !== fromWarehouse).map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
              </Select>
            </Field>
          ) : (
            <Field label="تعداد" hint={kind === "adjustment" ? "مثبت = افزایش، منفی = کاهش" : undefined}>
              <Input type="number" required min={kind === "adjustment" ? undefined : 1} value={quantity} onChange={e => setQuantity(e.target.value)} data-testid="movement-qty" />
            </Field>
          )}
        </div>
        {kind === "transfer" && <Field label="تعداد"><Input type="number" required min={1} value={quantity} onChange={e => setQuantity(e.target.value)} /></Field>}
        <Field label={reasonRequired ? "دلیل (الزامی)" : "توضیح (اختیاری)"}>
          <Input required={reasonRequired} minLength={reasonRequired ? 3 : undefined} maxLength={500}
            placeholder="مثلاً شماره فاکتور خرید یا علت کسری" value={reason} onChange={e => setReason(e.target.value)} />
        </Field>
      </form>
    </Modal>
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
    || (p.category ?? "").includes(term));

  return (
    <>
      <PageHeader eyebrow="انبار" title="انبار و کالاها" subtitle="کاتالوگ کالا و موجودی انبارها"
        actions={<>
          <Button variant="secondary" size="sm" icon={<FileSpreadsheet className="size-4" />} loading={exporter.running === "/reports/export/inventory/excel"}
            onClick={() => exporter.run("/reports/export/inventory/excel", "Pasineh_Inventory.xlsx")}>اکسل</Button>
          <Button variant="secondary" size="sm" icon={<FileText className="size-4" />} loading={exporter.running === "/reports/export/inventory/pdf"}
            onClick={() => exporter.run("/reports/export/inventory/pdf", "Pasineh_Inventory.pdf")}>PDF</Button>
          <Button variant="secondary" size="sm" icon={<Download className="size-4" />} data-testid="catalog-export"
            onClick={() => downloadFile("/catalog/export", "Pasineh_Catalog.xlsx").catch(e => toast.error(errorMessage(e)))}>خروجی کاتالوگ</Button>
          <Button variant="secondary" size="sm" icon={<Upload className="size-4" />} onClick={() => setImportOpen(true)} data-testid="catalog-import-open">ورود از اکسل</Button>
          <Button variant="soft" icon={<ArrowLeftRight className="size-4" />} onClick={() => setMovementFor(null)} data-testid="new-movement">ثبت گردش / انتقال</Button>
          <Button icon={<PackagePlus className="size-4" />} onClick={() => setProductModal(true)}>کالای جدید</Button>
        </>} />
      <Card>
        <div className="border-b border-border p-4">
          <div className="relative max-w-sm">
            <Search className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" />
            <Input className="pr-10" placeholder="جستجوی نام یا کد کالا" value={search} onChange={e => setSearch(e.target.value)} />
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
                <tr key={p.id} data-testid="product-row" data-sku={p.sku} data-focus={`product-${p.id}`} className={cn(flash === p.id && "focus-flash")}>
                  <td>
                    <button type="button" className="text-start font-medium decoration-dotted underline-offset-4 hover:text-brand hover:underline" onClick={() => setCatalogId(p.id)} data-testid="product-open">{p.name}</button>
                    {p.variant_label && <Badge tone="violet" className="ms-1.5"><Layers className="size-3" />{p.variant_label}</Badge>}
                  </td>
                  <td className="font-mono text-xs text-muted">{p.sku}</td>
                  <td className="text-xs text-text-2">{p.category ?? "—"}{p.origin === "imported" && <span className="ms-1 text-muted">· وارداتی{p.origin_country ? ` (${p.origin_country})` : ""}</span>}</td>
                  <td><StockBadge stock={p.stock ?? 0} /></td>
                  <td className="whitespace-nowrap tnum text-text-2">{faNumber(p.weight_kg)} کیلوگرم</td>
                  <td className="tnum">{faNumber(p.price)}{p.subsidy_percent > 0 && <Badge tone="success" className="ms-1.5">یارانه {faNumber(p.subsidy_percent)}٪</Badge>}</td>
                  <td>
                    <div className="flex gap-1">
                      <Tooltip content="تاریخچه گردش"><Button variant="ghost" size="icon" onClick={() => navigate(`/app/ledger?product=${p.id}`)}><History className="size-4" /></Button></Tooltip>
                      <Tooltip content="ثبت گردش"><Button variant="ghost" size="icon" onClick={() => setMovementFor(p)}><ArrowLeftRight className="size-4" /></Button></Tooltip>
                      <Tooltip content="حذف"><Button variant="ghost" size="icon" className="hover:text-danger" onClick={() => confirmDialog({ title: `کالای «${p.name}» حذف شود؟`, confirmLabel: "حذف کالا", danger: true }).then(ok => ok && remove.mutate(p.id))}><Trash2 className="size-4" /></Button></Tooltip>
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
    </>
  );
}
