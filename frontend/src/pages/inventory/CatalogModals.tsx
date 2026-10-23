/**
 * کاتالوگ کالا (مرحله ۱۳): پرونده کامل کالا (مشخصات، قیمت تاریخ‌دار با یارانه، تنوع‌ها، موجودی)
 * و ورود/خروج اکسل با پیش‌نمایش خطاها.
 */
import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, Layers, Minus, Plus, Trash2, Upload } from "lucide-react";
import { api, authFetch, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useToast } from "@/components/Toast";
import { usePartners } from "@/hooks/data";
import { STOCK_STATUS, type StockStatus } from "@/lib/labels";
import { faNumber } from "@/lib/format";
import { postForm } from "@/lib/tickets";
import { DateField, formatJalali } from "@/ui/datetime";
import { confirmDialog } from "@/ui/dialogs";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Checkbox, Field, Input, SegmentedControl, Select, Skeleton, Textarea, cn } from "@/ui/primitives";
import { FileField } from "@/ui/file";

type Detail = Schemas["ProductDetail"];
export const UNITS = ["عدد", "کیلوگرم", "گرم", "لیتر", "متر", "بسته", "کارتن", "کیسه", "جفت", "دستگاه"];
const toNumber = (v: string) => Number(v.replace(/[۰-۹]/g, d => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))).replace(/[,٬\s]/g, ""));
const isoToday = () => new Date(Date.now() + 3.5 * 3600_000).toISOString().slice(0, 10);
const optNumber = (v: string) => (v.trim() === "" ? null : toNumber(v));

export async function downloadFile(url: string, filename: string) {
  const res = await authFetch(url);
  if (!res.ok) throw new Error("دریافت فایل ناموفق بود.");
  const href = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href, download: filename });
  a.click();
  setTimeout(() => URL.revokeObjectURL(href), 2000);
}

// ---------------------------------------------------------------------------
// پرونده کالا
// ---------------------------------------------------------------------------
export function ProductCatalogModal({ productId, onClose, onOpen }: { productId: number | null; onClose: () => void; onOpen: (id: number) => void }) {
  const [tab, setTab] = useState<"info" | "prices" | "variants" | "stock" | "units">("info");
  const { data: p, isLoading } = useQuery({
    queryKey: ["catalog-product", productId],
    queryFn: () => unwrap(api.GET("/catalog/products/{product_id}", { params: { path: { product_id: productId! } } })),
    enabled: productId != null,
  });
  useEffect(() => { setTab("info"); }, [productId]);

  return (
    <Modal open={productId != null} onClose={onClose} size="lg" testId="catalog-product"
      title={p ? <span className="flex flex-wrap items-center gap-2">{p.name}{p.variant_label && <Badge tone="violet">{p.variant_label}</Badge>}</span> : "کالا"}
      description={p && <span className="font-mono ltr">{p.sku}</span>}>
      {isLoading || !p ? <Skeleton className="h-80" /> : (
        <div className="space-y-5">
          <SegmentedControl value={tab} onChange={setTab} options={[
            { value: "info", label: "مشخصات" }, { value: "prices", label: `قیمت‌ها (${faNumber(p.prices.length)})` },
            { value: "variants", label: `تنوع‌ها (${faNumber(p.variants.length)})` }, { value: "stock", label: "موجودی" },
            { value: "units", label: "واحد و تأمین" },
          ]} />
          <div key={tab} className="animate-fade">
            {tab === "info" && <InfoTab p={p} />}
            {tab === "prices" && <PricesTab p={p} />}
            {tab === "variants" && <VariantsTab p={p} onOpen={onOpen} />}
            {tab === "stock" && (
              <table className="table-base" data-testid="catalog-stock">
                <thead><tr><th>انبار</th><th>وضعیت کیفی</th><th>موجودی</th><th>رزرو</th><th>آزاد</th><th>نقطه سفارش</th></tr></thead>
                <tbody>{p.stock.map(s => <tr key={`${s.warehouse_id}-${s.stock_status}`}>
                  <td>{s.warehouse_name}</td>
                  <td><Badge tone={STOCK_STATUS[s.stock_status as StockStatus]?.tone ?? "muted"}>{STOCK_STATUS[s.stock_status as StockStatus]?.label ?? s.stock_status}</Badge></td>
                  <td className="tnum font-semibold">{faNumber(s.quantity)} {p.unit}</td>
                  <td className="tnum text-text-2">{s.reserved ? faNumber(s.reserved) : "—"}</td>
                  <td className="tnum">{s.stock_status === "available" ? faNumber(s.free) : "—"}</td>
                  <td className="tnum text-text-2">{s.reorder_point != null ? faNumber(s.reorder_point) : "—"}</td></tr>)}</tbody>
              </table>
            )}
            {tab === "units" && <UnitsTab p={p} />}
          </div>
        </div>
      )}
    </Modal>
  );
}

function useSave(id: number) {
  const queryClient = useQueryClient();
  const toast = useToast();
  return (d: Detail, message?: string) => {
    queryClient.setQueryData(["catalog-product", id], d);
    queryClient.invalidateQueries({ queryKey: ["products"] });
    if (message) toast.success(message);
  };
}

function InfoTab({ p }: { p: Detail }) {
  const toast = useToast();
  const save = useSave(p.id);
  const num = (v?: number | null) => (v == null ? "" : String(v));
  const [f, setF] = useState(() => ({
    name: p.name, short_name: p.short_name ?? "", category: p.category ?? "", brand: p.brand ?? "", unit: p.unit, barcode: p.barcode ?? "",
    weight: String(p.weight_kg ?? 1), net_weight: num(p.net_weight_kg), length: num(p.length_cm), width: num(p.width_cm), height: num(p.height_cm),
    lot: p.lot_tracked, serial: p.serial_tracked, expiry: p.expiry_tracked, shelf_life: num(p.shelf_life_days),
    min_stock: num(p.min_stock), max_stock: num(p.max_stock), reorder_point: num(p.reorder_point), active: p.is_active,
    origin: p.origin as "domestic" | "imported", origin_country: p.origin_country ?? "",
    export_eligible: p.export_eligible, hs_code: p.hs_code ?? "", description: p.description ?? "", variant_label: p.variant_label ?? "",
    specs: (p.specs.length ? p.specs : [["", ""]]) as string[][],
  }));
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF(x => ({ ...x, [k]: v }));
  const update = useMutation({
    mutationFn: () => unwrap(api.PUT("/catalog/products/{product_id}", { params: { path: { product_id: p.id } }, body: {
      name: f.name, short_name: f.short_name || null, category: f.category || null, brand: f.brand || null, unit: f.unit,
      barcode: f.barcode.trim() || null, weight_kg: toNumber(f.weight) || 1,
      net_weight_kg: optNumber(f.net_weight), length_cm: optNumber(f.length), width_cm: optNumber(f.width), height_cm: optNumber(f.height),
      lot_tracked: f.lot || f.expiry, serial_tracked: f.serial, expiry_tracked: f.expiry, shelf_life_days: f.expiry ? optNumber(f.shelf_life) : null,
      min_stock: optNumber(f.min_stock), max_stock: optNumber(f.max_stock), reorder_point: optNumber(f.reorder_point), is_active: f.active,
      origin: f.origin, origin_country: f.origin === "imported" ? f.origin_country || null : null,
      export_eligible: f.export_eligible, hs_code: f.hs_code || null, description: f.description || null,
      variant_label: p.parent ? f.variant_label || null : undefined,
      specs: f.specs.filter(([k]) => k.trim()).map(([k, v]) => [k.trim(), (v ?? "").trim()]),
    } })),
    onSuccess: d => save(d, "مشخصات کالا ذخیره شد."),
    onError: e => toast.error(errorMessage(e)),
  });

  return (
    <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); update.mutate(); }} data-testid="catalog-info">
      <Field label="نام کامل کالا *" className="sm:col-span-2"><Input required value={f.name} onChange={e => set("name", e.target.value)} /></Field>
      <Field label="کد کالا (SKU)" hint="تغییرناپذیر — برای کد جدید، کالای تازه تعریف کنید"><Input readOnly disabled className="ltr" value={p.sku} data-testid="catalog-sku" /></Field>
      <Field label="نام کوتاه" hint="برای برچسب و اسناد"><Input maxLength={60} value={f.short_name} onChange={e => set("short_name", e.target.value)} /></Field>
      {p.parent ? <Field label="عنوان تنوع"><Input value={f.variant_label} onChange={e => set("variant_label", e.target.value)} /></Field>
        : <Field label="بارکد"><Input className="ltr" value={f.barcode} onChange={e => set("barcode", e.target.value)} /></Field>}
      <Field label="گروه کالا"><Input value={f.category} onChange={e => set("category", e.target.value)} placeholder="مثلاً لوازم برقی" /></Field>
      <Field label="برند"><Input value={f.brand} onChange={e => set("brand", e.target.value)} /></Field>
      <Field label="واحد پایه" hint="کوچک‌ترین واحد شمارش"><Select value={f.unit} onChange={e => set("unit", e.target.value)}>{[...new Set([...UNITS, f.unit])].map(u => <option key={u} value={u}>{u}</option>)}</Select></Field>
      <Field label="وزن ناخالص هر واحد (کیلوگرم)"><Input inputMode="decimal" value={f.weight} onChange={e => set("weight", e.target.value)} /></Field>
      <Field label="وزن خالص (کیلوگرم)" hint="اختیاری — بیشتر از ناخالص نیست"><Input inputMode="decimal" value={f.net_weight} onChange={e => set("net_weight", e.target.value)} data-testid="catalog-net-weight" /></Field>
      <Field label="ابعاد (سانتی‌متر)" hint="طول × عرض × ارتفاع">
        <div className="grid grid-cols-3 gap-2" dir="ltr">
          <Input inputMode="decimal" placeholder="L" aria-label="طول" value={f.length} onChange={e => set("length", e.target.value)} />
          <Input inputMode="decimal" placeholder="W" aria-label="عرض" value={f.width} onChange={e => set("width", e.target.value)} />
          <Input inputMode="decimal" placeholder="H" aria-label="ارتفاع" value={f.height} onChange={e => set("height", e.target.value)} />
        </div>
      </Field>
      <div className="rounded-xl border border-border p-3 sm:col-span-2" data-testid="catalog-tracking">
        <div className="mb-2 text-sm font-medium text-text-2">ردیابی</div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <Checkbox label="بچ / سری ساخت" checked={f.lot || f.expiry} disabled={f.expiry} onChange={e => set("lot", e.target.checked)} />
          <Checkbox label="شماره سریال" checked={f.serial} onChange={e => set("serial", e.target.checked)} />
          <Checkbox label="تاریخ انقضا" checked={f.expiry} onChange={e => set("expiry", e.target.checked)} data-testid="catalog-expiry" />
          {f.expiry && <div className="flex items-center gap-2 animate-fade"><Input inputMode="numeric" className="w-24 text-center" aria-label="ماندگاری (روز)"
            value={f.shelf_life} onChange={e => set("shelf_life", e.target.value)} /><span className="text-sm text-muted">روز ماندگاری</span></div>}
        </div>
        <p className="mt-2 text-xs text-muted">ردیابی تاریخ انقضا بدون بچ ممکن نیست؛ با فعال کردن انقضا، بچ هم فعال می‌شود.</p>
      </div>
      <Field label="حداقل / حداکثر موجودی" hint="پیش‌فرض کالا؛ هر انبار نقطه سفارش خودش را هم دارد">
        <div className="grid grid-cols-2 gap-2">
          <Input inputMode="numeric" placeholder="حداقل" aria-label="حداقل موجودی" value={f.min_stock} onChange={e => set("min_stock", e.target.value)} />
          <Input inputMode="numeric" placeholder="حداکثر" aria-label="حداکثر موجودی" value={f.max_stock} onChange={e => set("max_stock", e.target.value)} />
        </div>
      </Field>
      <Field label="نقطه سفارش پیش‌فرض" hint="برای انبارهای جدید این کالا"><Input inputMode="numeric" value={f.reorder_point} onChange={e => set("reorder_point", e.target.value)} /></Field>
      <Field label="مبدأ">
        <SegmentedControl value={f.origin} onChange={v => set("origin", v)} options={[{ value: "domestic", label: "داخلی" }, { value: "imported", label: "وارداتی" }]} />
      </Field>
      {f.origin === "imported" ? <Field label="کشور مبدأ"><Input value={f.origin_country} onChange={e => set("origin_country", e.target.value)} placeholder="مثلاً امارات" data-testid="catalog-country" /></Field> : <div />}
      <Field label="کد تعرفه گمرکی" hint="اختیاری"><Input className="ltr" value={f.hs_code} onChange={e => set("hs_code", e.target.value)} /></Field>
      <div className="flex items-end pb-2"><Checkbox label="قابل صادرات" checked={f.export_eligible} onChange={e => set("export_eligible", e.target.checked)} /></div>
      <Field label="توضیحات" className="sm:col-span-2"><Textarea rows={2} value={f.description} onChange={e => set("description", e.target.value)} /></Field>
      <div className="sm:col-span-2">
        <div className="mb-2 text-sm font-medium text-text-2">مشخصات فنی</div>
        <div className="space-y-2" data-testid="catalog-specs">
          {f.specs.map(([k, v], i) => (
            <div key={i} className="grid grid-cols-[1fr_1.4fr_auto] gap-2">
              <Input placeholder="ویژگی (مثلاً رنگ)" value={k} onChange={e => set("specs", f.specs.map((s, j) => j === i ? [e.target.value, s[1]] : s))} />
              <Input placeholder="مقدار" value={v} onChange={e => set("specs", f.specs.map((s, j) => j === i ? [s[0], e.target.value] : s))} />
              <Button type="button" variant="ghost" size="icon" aria-label="حذف ویژگی" onClick={() => set("specs", f.specs.length > 1 ? f.specs.filter((_, j) => j !== i) : [["", ""]])}><Minus className="size-4" /></Button>
            </div>
          ))}
        </div>
        <Button type="button" variant="ghost" size="sm" className="mt-2" icon={<Plus className="size-4" />} onClick={() => set("specs", [...f.specs, ["", ""]])}>ویژگی جدید</Button>
      </div>
      <div className="flex items-center justify-between gap-3 sm:col-span-2">
        <Checkbox label="فعال (غیرفعال = بایگانی؛ سوابق می‌ماند)" checked={f.active} onChange={e => set("active", e.target.checked)} data-testid="catalog-active" />
        <Button type="submit" loading={update.isPending} data-testid="catalog-save">ذخیره مشخصات</Button>
      </div>
    </form>
  );
}

function PricesTab({ p }: { p: Detail }) {
  const toast = useToast();
  const save = useSave(p.id);
  const [f, setF] = useState({ date: isoToday(), base: String(p.current_base_price), subsidized: p.current_subsidy_percent > 0,
    subsidy: String(p.current_subsidy_percent || 0), cost: "", note: "" });
  const base = toNumber(f.base) || 0;
  const subsidy = f.subsidized ? Math.min(99, toNumber(f.subsidy) || 0) : 0;
  const final = Math.round(base * (1 - subsidy / 100));
  const add = useMutation({
    mutationFn: () => unwrap(api.POST("/catalog/products/{product_id}/prices", { params: { path: { product_id: p.id } }, body: {
      effective_from: f.date, base_price: base, subsidy_percent: subsidy, cost_price: f.cost ? toNumber(f.cost) : null, note: f.note || null,
    } })),
    onSuccess: d => save(d, "قیمت ثبت شد."),
    onError: e => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE("/catalog/prices/{price_id}", { params: { path: { price_id: id } } })),
    onSuccess: d => save(d, "قیمت حذف شد."),
    onError: e => toast.error(errorMessage(e)),
  });

  return (
    <div className="space-y-5" data-testid="catalog-prices">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl bg-surface-2 p-4"><div className="text-xs text-muted">قیمت پایه فعلی</div><div className="mt-1 text-lg font-bold tnum">{faNumber(p.current_base_price)}</div></div>
        <div className="rounded-xl bg-surface-2 p-4"><div className="text-xs text-muted">یارانه</div><div className="mt-1 text-lg font-bold tnum">{p.current_subsidy_percent ? `${faNumber(p.current_subsidy_percent)}٪` : "ندارد"}</div></div>
        <div className="rounded-xl bg-brand-soft p-4"><div className="text-xs text-brand">قیمت فروش امروز</div><div className="mt-1 text-lg font-black text-brand-strong tnum" data-testid="catalog-current-price">{faNumber(p.current_price)} ریال</div></div>
      </div>

      <form className="grid gap-3 rounded-xl border border-border p-4 sm:grid-cols-3" onSubmit={(e: FormEvent) => { e.preventDefault(); add.mutate(); }} data-testid="catalog-price-form">
        <div className="text-sm font-bold sm:col-span-3">قیمت جدید</div>
        <Field label="از تاریخ *"><DateField required value={f.date} onChange={v => setF(x => ({ ...x, date: v }))} testId="price-date" /></Field>
        <Field label="قیمت پایه (ریال) *"><Input required inputMode="numeric" value={f.base} onChange={e => setF(x => ({ ...x, base: e.target.value }))} data-testid="price-base" /></Field>
        <Field label="بهای تمام‌شده (ریال)" hint="اختیاری"><Input inputMode="numeric" value={f.cost} onChange={e => setF(x => ({ ...x, cost: e.target.value }))} /></Field>
        <div className="flex items-end gap-3 sm:col-span-2">
          <Checkbox label="یارانه دارد" checked={f.subsidized} onChange={e => setF(x => ({ ...x, subsidized: e.target.checked }))} data-testid="price-subsidized" />
          {f.subsidized && <div className="flex items-center gap-2 animate-fade"><Input inputMode="decimal" className="w-20 text-center" value={f.subsidy}
            onChange={e => setF(x => ({ ...x, subsidy: e.target.value }))} aria-label="درصد یارانه" data-testid="price-subsidy" /><span className="text-sm text-muted">درصد</span></div>}
        </div>
        <div className="rounded-xl bg-surface-2 px-3 py-2 text-sm" data-testid="price-preview">قیمت فروش: <b className="tnum">{faNumber(final)}</b> ریال</div>
        <Field label="توضیح" className="sm:col-span-2"><Input value={f.note} onChange={e => setF(x => ({ ...x, note: e.target.value }))} placeholder="مثلاً افزایش نرخ ارز" /></Field>
        <div className="flex items-end justify-end"><Button type="submit" loading={add.isPending} data-testid="price-submit">ثبت قیمت</Button></div>
        <p className="text-xs text-muted sm:col-span-3">سفارش‌هایی که قبلاً ثبت شده‌اند قیمت خودشان را نگه می‌دارند؛ سفارش جدید قیمتِ «روز تحویل» خود را می‌گیرد.</p>
      </form>

      <div className="overflow-x-auto">
        <table className="table-base" data-testid="catalog-price-history">
          <thead><tr><th>از تاریخ</th><th>پایه</th><th>یارانه</th><th>فروش</th><th>سود</th><th>توضیح</th><th /></tr></thead>
          <tbody>
            {p.prices.map(pr => (
              <tr key={pr.id} className={cn(pr.is_current && "bg-brand-soft/40")} data-testid="price-row" data-current={pr.is_current} data-future={pr.is_future}>
                <td className="whitespace-nowrap">{formatJalali(pr.effective_from)}
                  {pr.is_current && <Badge tone="brand" className="ms-1.5">فعلی</Badge>}{pr.is_future && <Badge tone="info" className="ms-1.5">آینده</Badge>}</td>
                <td className="tnum">{faNumber(pr.base_price)}</td>
                <td className="tnum">{pr.subsidy_percent ? `${faNumber(pr.subsidy_percent)}٪` : "—"}</td>
                <td className="tnum font-semibold">{faNumber(pr.final_price)}</td>
                <td className="tnum text-xs">{pr.cost_price ? `${faNumber(Math.round(((pr.final_price - pr.cost_price) / (pr.final_price || 1)) * 100))}٪` : "—"}</td>
                <td className="text-xs text-muted">{pr.note ?? ""}{pr.created_by ? ` · ${pr.created_by}` : ""}</td>
                <td>{p.prices.length > 1 && <Button variant="ghost" size="icon" className="hover:text-danger" aria-label="حذف قیمت"
                  onClick={() => confirmDialog({ title: "این قیمت حذف شود؟", danger: true, confirmLabel: "حذف" }).then(ok => ok && remove.mutate(pr.id))}><Trash2 className="size-4" /></Button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

type UomRow = { name: string; factor: string; barcode: string; purchase: boolean; sales: boolean };
type SupplierRow = { partner: string; sku: string; lead: string; moq: string; price: string; preferred: boolean };

/** واحدهای فرعی (کارتن = ۱۲ عدد و …) و تأمین‌کننده‌های کالا */
function UnitsTab({ p }: { p: Detail }) {
  const toast = useToast();
  const save = useSave(p.id);
  const { data: suppliers = [] } = usePartners("supplier");
  const [uoms, setUoms] = useState<UomRow[]>(() => p.uoms.map(u => ({ name: u.name, factor: String(u.factor), barcode: u.barcode ?? "",
    purchase: u.is_purchase_default, sales: u.is_sales_default })));
  const [links, setLinks] = useState<SupplierRow[]>(() => p.suppliers.map(s => ({ partner: String(s.partner_id), sku: s.supplier_sku ?? "",
    lead: s.lead_time_days != null ? String(s.lead_time_days) : "", moq: s.min_order_qty != null ? String(s.min_order_qty) : "",
    price: s.last_price != null ? String(s.last_price) : "", preferred: s.is_preferred })));
  const saveUoms = useMutation({
    mutationFn: () => unwrap(api.PUT("/catalog/products/{product_id}/uoms", { params: { path: { product_id: p.id } },
      body: uoms.filter(u => u.name.trim()).map(u => ({ name: u.name.trim(), factor: toNumber(u.factor), barcode: u.barcode.trim() || null,
        is_purchase_default: u.purchase, is_sales_default: u.sales })) })),
    onSuccess: d => save(d, "واحدهای کالا ذخیره شد."),
    onError: e => toast.error(errorMessage(e)),
  });
  const saveLinks = useMutation({
    mutationFn: () => unwrap(api.PUT("/catalog/products/{product_id}/suppliers", { params: { path: { product_id: p.id } },
      body: links.filter(l => l.partner).map(l => ({ partner_id: Number(l.partner), supplier_sku: l.sku.trim() || null,
        lead_time_days: optNumber(l.lead), min_order_qty: optNumber(l.moq), last_price: optNumber(l.price), is_preferred: l.preferred })) })),
    onSuccess: d => save(d, "تأمین‌کننده‌های کالا ذخیره شد."),
    onError: e => toast.error(errorMessage(e)),
  });
  const setUom = (i: number, patch: Partial<UomRow>) => setUoms(list => list.map((u, j) => j === i ? { ...u, ...patch } : u));
  const setLink = (i: number, patch: Partial<SupplierRow>) => setLinks(list => list.map((l, j) => j === i ? { ...l, ...patch } : l));

  return (
    <div className="space-y-6">
      <section data-testid="catalog-uoms">
        <div className="mb-1 font-bold">واحدهای فرعی</div>
        <p className="mb-3 text-xs text-muted">هر واحد فرعی عدد صحیحی از واحد پایه («{p.unit}») است؛ موجودی همیشه به واحد پایه ثبت می‌شود و تبدیل همیشه دقیق است.</p>
        <div className="space-y-2">
          {uoms.map((u, i) => (
            <div key={i} className="grid grid-cols-2 items-center gap-2 sm:grid-cols-[1fr_7rem_1.2fr_auto_auto_auto]">
              <Input placeholder="نام واحد (مثلاً کارتن)" value={u.name} onChange={e => setUom(i, { name: e.target.value })} data-testid="uom-name" />
              <Input inputMode="numeric" placeholder={`چند ${p.unit}`} aria-label="ضریب" value={u.factor} onChange={e => setUom(i, { factor: e.target.value })} data-testid="uom-factor" />
              <Input className="ltr" placeholder="بارکد (اختیاری)" value={u.barcode} onChange={e => setUom(i, { barcode: e.target.value })} />
              <Checkbox label="خرید" checked={u.purchase} onChange={e => setUoms(list => list.map((x, j) => ({ ...x, purchase: j === i ? e.target.checked : false })))} />
              <Checkbox label="فروش" checked={u.sales} onChange={e => setUoms(list => list.map((x, j) => ({ ...x, sales: j === i ? e.target.checked : false })))} />
              <Button type="button" variant="ghost" size="icon" aria-label="حذف واحد" onClick={() => setUoms(list => list.filter((_, j) => j !== i))}><Minus className="size-4" /></Button>
            </div>
          ))}
        </div>
        <div className="mt-2 flex justify-between gap-2">
          <Button type="button" variant="ghost" size="sm" icon={<Plus className="size-4" />}
            onClick={() => setUoms(list => [...list, { name: "", factor: "", barcode: "", purchase: false, sales: false }])} data-testid="uom-add">واحد جدید</Button>
          <Button size="sm" loading={saveUoms.isPending} onClick={() => saveUoms.mutate()} data-testid="uom-save">ذخیره واحدها</Button>
        </div>
      </section>

      <section className="border-t border-border pt-5" data-testid="catalog-suppliers">
        <div className="mb-1 font-bold">تأمین‌کننده‌ها</div>
        <p className="mb-3 text-xs text-muted">کد کالا نزد تأمین‌کننده، زمان تأمین و حداقل سفارش؛ تأمین‌کننده‌ها در «طرف‌های تجاری» تعریف می‌شوند.</p>
        {!suppliers.length && !links.length ? <p className="text-sm text-muted">هنوز تأمین‌کننده فعالی تعریف نشده است.</p> : (
          <div className="space-y-2">
            {links.map((l, i) => (
              <div key={i} className="grid grid-cols-2 items-center gap-2 sm:grid-cols-[1.4fr_1fr_5rem_5rem_7rem_auto_auto]">
                <Select value={l.partner} onChange={e => setLink(i, { partner: e.target.value })} aria-label="تأمین‌کننده" data-testid="supplier-select">
                  <option value="">انتخاب تأمین‌کننده…</option>
                  {suppliers.map(s => <option key={s.id} value={s.id}>{s.name} ({s.code})</option>)}
                </Select>
                <Input className="ltr" placeholder="کد نزد تأمین‌کننده" value={l.sku} onChange={e => setLink(i, { sku: e.target.value })} />
                <Input inputMode="numeric" placeholder="روز" aria-label="زمان تأمین (روز)" value={l.lead} onChange={e => setLink(i, { lead: e.target.value })} />
                <Input inputMode="numeric" placeholder="حداقل" aria-label="حداقل سفارش" value={l.moq} onChange={e => setLink(i, { moq: e.target.value })} />
                <Input inputMode="numeric" placeholder="آخرین قیمت" aria-label="آخرین قیمت (ریال)" value={l.price} onChange={e => setLink(i, { price: e.target.value })} />
                <Checkbox label="اصلی" checked={l.preferred} onChange={e => setLinks(list => list.map((x, j) => ({ ...x, preferred: j === i ? e.target.checked : false })))} />
                <Button type="button" variant="ghost" size="icon" aria-label="حذف تأمین‌کننده" onClick={() => setLinks(list => list.filter((_, j) => j !== i))}><Minus className="size-4" /></Button>
              </div>
            ))}
          </div>
        )}
        <div className="mt-2 flex justify-between gap-2">
          <Button type="button" variant="ghost" size="sm" icon={<Plus className="size-4" />} disabled={!suppliers.length}
            onClick={() => setLinks(list => [...list, { partner: "", sku: "", lead: "", moq: "", price: "", preferred: !list.length }])}>تأمین‌کننده جدید</Button>
          <Button size="sm" loading={saveLinks.isPending} onClick={() => saveLinks.mutate()} data-testid="supplier-save">ذخیره تأمین‌کننده‌ها</Button>
        </div>
      </section>
    </div>
  );
}

function VariantsTab({ p, onOpen }: { p: Detail; onOpen: (id: number) => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [f, setF] = useState({ sku: "", label: "", origin: p.origin as "domestic" | "imported", country: "", base: String(p.current_base_price), subsidy: "0" });
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/catalog/products/{product_id}/variants", { params: { path: { product_id: p.id } }, body: {
      sku: f.sku, variant_label: f.label, origin: f.origin, origin_country: f.origin === "imported" ? f.country || null : null,
      base_price: toNumber(f.base) || 0, subsidy_percent: toNumber(f.subsidy) || 0,
    } })),
    onSuccess: d => { toast.success(`تنوع «${d.variant_label}» ساخته شد.`); queryClient.invalidateQueries({ queryKey: ["products"] });
      queryClient.invalidateQueries({ queryKey: ["catalog-product", p.id] }); onOpen(d.id); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <div className="space-y-5" data-testid="catalog-variants">
      <p className="text-sm leading-7 text-text-2">تنوع، همان کالا با کد، مبدأ یا مشخصات متفاوت است — مثلاً «PS5 واردات امارات» و «PS5 واردات چین». هر تنوع قیمت، موجودی و تاریخچه جدا دارد.</p>
      {p.variants.length > 0 && (
        <div className="divide-y divide-border rounded-xl border border-border">
          {p.variants.map(v => (
            <button key={v.id} type="button" onClick={() => onOpen(v.id)} className="flex w-full items-center gap-3 px-4 py-3 text-start text-sm transition hover:bg-surface-2" data-testid="variant-row">
              <Layers className="size-4 text-violet" />
              <span className="flex-1"><b>{v.variant_label ?? v.name}</b> <span className="font-mono text-xs text-muted">{v.sku}</span></span>
              <span className="text-xs text-muted">{v.origin === "imported" ? `وارداتی${v.origin_country ? ` (${v.origin_country})` : ""}` : "داخلی"}</span>
              <span className="tnum">{faNumber(v.price)}</span><Badge tone="muted">{faNumber(v.stock)}</Badge>
            </button>
          ))}
        </div>
      )}
      <form className="grid gap-3 rounded-xl border border-border p-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
        <div className="text-sm font-bold sm:col-span-2">تنوع جدید {p.parent && <span className="font-normal text-muted">(زیر «{p.parent.name}»)</span>}</div>
        <Field label="کد کالای جدید *"><Input required className="ltr" value={f.sku} onChange={e => setF(x => ({ ...x, sku: e.target.value }))} data-testid="variant-sku" /></Field>
        <Field label="عنوان تنوع *"><Input required minLength={2} value={f.label} onChange={e => setF(x => ({ ...x, label: e.target.value }))} placeholder="مثلاً سری واردات چین" data-testid="variant-label" /></Field>
        <Field label="مبدأ"><SegmentedControl value={f.origin} onChange={v => setF(x => ({ ...x, origin: v }))} options={[{ value: "domestic", label: "داخلی" }, { value: "imported", label: "وارداتی" }]} /></Field>
        {f.origin === "imported" ? <Field label="کشور مبدأ"><Input value={f.country} onChange={e => setF(x => ({ ...x, country: e.target.value }))} /></Field> : <div />}
        <Field label="قیمت پایه (ریال) *"><Input required inputMode="numeric" value={f.base} onChange={e => setF(x => ({ ...x, base: e.target.value }))} /></Field>
        <Field label="درصد یارانه"><Input inputMode="decimal" value={f.subsidy} onChange={e => setF(x => ({ ...x, subsidy: e.target.value }))} /></Field>
        <div className="flex justify-end sm:col-span-2"><Button type="submit" loading={create.isPending} icon={<Plus className="size-4" />} data-testid="variant-submit">ساخت تنوع</Button></div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ورود از اکسل
// ---------------------------------------------------------------------------
type Report = Schemas["ImportReport"];

export function CatalogImportModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<"ignore" | "set" | "add">("ignore");
  const [report, setReport] = useState<Report | null>(null);
  useEffect(() => { if (open) { setFile(null); setReport(null); setMode("ignore"); } }, [open]);
  const send = useMutation({
    mutationFn: (dryRun: boolean) => {
      const form = new FormData();
      form.set("file", file!);
      form.set("stock_mode", mode);
      form.set("dry_run", String(dryRun));
      return postForm<Report>("/catalog/import", form);
    },
    onSuccess: r => {
      setReport(r);
      if (r.applied) {
        toast.success(`کاتالوگ به‌روز شد: ${faNumber(r.create)} کالای جدید، ${faNumber(r.update)} به‌روزرسانی.`);
        ["products", "movements", "stats", "catalog-product"].forEach(k => queryClient.invalidateQueries({ queryKey: [k] }));
      }
    },
    onError: e => toast.error(errorMessage(e)),
  });

  return (
    <Modal open={open} onClose={onClose} size="lg" title="ورود کاتالوگ از اکسل" testId="catalog-import"
      description="کالاها، قیمت‌ها، تنوع‌ها و موجودی را یک‌جا از فایل اکسل وارد کنید."
      footer={report?.applied ? <Button onClick={onClose}>بستن</Button> : <>
        <Button variant="secondary" onClick={onClose}>انصراف</Button>
        {report && report.error_count === 0
          ? <Button loading={send.isPending} icon={<CheckCircle2 className="size-4" />} onClick={() => send.mutate(false)} data-testid="import-apply">ثبت نهایی</Button>
          : <Button loading={send.isPending} disabled={!file} icon={<Upload className="size-4" />} onClick={() => send.mutate(true)} data-testid="import-check">بررسی فایل</Button>}
      </>}>
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-3 rounded-xl bg-surface-2 p-4 text-sm">
          <FileSpreadsheet className="size-5 text-success" />
          <span className="flex-1">قالب آماده با راهنما، نمونه و فهرست‌های کشویی را دانلود و پر کنید.</span>
          <Button size="sm" variant="secondary" icon={<Download className="size-4" />} data-testid="import-template"
            onClick={() => downloadFile("/catalog/template", "Pasineh_Catalog_Template.xlsx").catch(e => toast.error(errorMessage(e)))}>دانلود قالب</Button>
        </div>
        <Field label="فایل اکسل (.xlsx) *">
          <FileField file={file} onChange={f => { setFile(f); setReport(null); }} testId="import-file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" placeholder="فایل اکسل کاتالوگ را انتخاب کنید" />
        </Field>
        <Field label="ستون «موجودی» فایل">
          <SegmentedControl value={mode} onChange={v => { setMode(v); setReport(null); }} options={[
            { value: "ignore", label: "نادیده بگیر" }, { value: "set", label: "تنظیم موجودی به عدد فایل" }, { value: "add", label: "افزودن به موجودی (ورود کالا)" },
          ]} />
        </Field>

        {report && (
          <div className="space-y-4 animate-fade" data-testid="import-report" data-errors={report.error_count} data-applied={report.applied}>
            <div className="flex flex-wrap gap-2 text-sm">
              <Badge tone="muted">{faNumber(report.rows)} ردیف</Badge>
              <Badge tone="success">{faNumber(report.create)} کالای جدید</Badge>
              <Badge tone="info">{faNumber(report.update)} به‌روزرسانی</Badge>
              {report.stock_mode !== "ignore" && <Badge tone="violet">{faNumber(report.stock_rows)} ردیف موجودی</Badge>}
              {report.error_count > 0 && <Badge tone="danger">{faNumber(report.error_count)} ردیف خطادار</Badge>}
            </div>
            {report.applied ? (
              <p className="flex items-center gap-2 rounded-xl bg-success-soft px-4 py-3 text-sm text-success"><CheckCircle2 className="size-4" />ثبت شد. موجودی‌ها در دفتر گردش کالا ثبت شده‌اند.</p>
            ) : report.error_count > 0 ? (
              <div className="space-y-2">
                <p className="flex items-center gap-2 text-sm font-medium text-danger"><AlertTriangle className="size-4" />تا رفع خطاها هیچ چیزی ذخیره نمی‌شود. فایل را اصلاح و دوباره بررسی کنید.</p>
                <ul className="max-h-60 divide-y divide-border overflow-y-auto rounded-xl border border-danger/30 text-sm" data-testid="import-errors">
                  {report.errors.map(e => (
                    <li key={e.line} className="px-4 py-2.5"><b className="tnum">ردیف {faNumber(e.line)}</b>{e.sku && <span className="ms-2 font-mono text-xs ltr">{e.sku}</span>}
                      <span className="ms-2 text-text-2">{e.messages.join(" · ")}</span></li>
                  ))}
                </ul>
              </div>
            ) : <p className="text-sm text-text-2">فایل بدون خطاست. پیش‌نمایش را ببینید و «ثبت نهایی» را بزنید.</p>}
            <div className="max-h-64 overflow-auto rounded-xl border border-border">
              <table className="table-base">
                <thead><tr><th>ردیف</th><th>کد</th><th>نام</th><th>عملیات</th><th>قیمت فروش</th><th>انبار / موجودی</th></tr></thead>
                <tbody>
                  {report.preview.map(r => (
                    <tr key={r.line} className={cn(!r.ok && "bg-danger-soft/40")}>
                      <td className="tnum text-xs">{faNumber(r.line)}</td><td className="font-mono text-xs">{r.sku}</td><td>{r.name ?? "—"}</td>
                      <td><Badge tone={r.action === "create" ? "success" : r.action === "update" ? "info" : "muted"}>{r.action === "create" ? "جدید" : r.action === "update" ? "به‌روزرسانی" : "موجودی"}</Badge></td>
                      <td className="tnum">{r.price != null ? faNumber(r.price) : "—"}</td>
                      <td className="text-xs text-text-2">{r.warehouse ?? "—"}{r.quantity != null ? ` · ${faNumber(r.quantity)}` : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
