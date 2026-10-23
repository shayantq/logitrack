import { useEffect, useMemo, useState, type FormEvent } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock3, Plus, Sparkles, Trash2 } from "lucide-react";
import { api, errorMessage, isServerError, newIdempotencyKey, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { CitySelect } from "@/components/CitySelect";
import { SuggestionList } from "@/components/dispatch/SuggestionList";
import { useToast } from "@/components/Toast";
import { useProducts, useProvinces, useWarehouses } from "@/hooks/data";
import { PACKAGE_SIZES } from "@/lib/labels";
import { faNumber, localToIso, normalizeDigits, tomorrowIsoDate } from "@/lib/format";
import { Modal } from "@/ui/overlays";
import { Button, Checkbox, Field, Input, Select, cn } from "@/ui/primitives";
import { DateField, TimeField } from "@/ui/datetime";

type Item = { product_id: number | ""; quantity: number };

const EMPTY = {
  customerName: "", customerMobile: "", recipientName: "", recipientMobile: "",
  province: "", city: "", address: "", postal: "",
  date: tomorrowIsoDate(), from: "09:00", to: "13:00",
  size: "m" as Schemas["OrderRequest"]["size"], priority: false, warehouse: "", vehicle: "auto", notes: "", fee: "",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-6">
      <h4 className="mb-3 text-sm font-bold text-text">{title}</h4>
      {children}
    </section>
  );
}

export function OrderFormModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const me = useMe();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data: products = [] } = useProducts();
  const { data: allWarehouses = [] } = useWarehouses();
  // سفارش فقط از انبارهای فعالی ارسال می‌شود که نوعشان ارسال سفارش دارد (عمومی، محصول نهایی، توزیع)
  const warehouses = useMemo(() => allWarehouses.filter(w => w.ships_orders && w.is_active), [allWarehouses]);
  const { data: provinces = [] } = useProvinces();
  const [form, setForm] = useState(EMPTY);
  const [requestKey, setRequestKey] = useState(newIdempotencyKey);
  const [items, setItems] = useState<Item[]>([{ product_id: "", quantity: 1 }]);
  const set = <K extends keyof typeof EMPTY>(key: K, value: (typeof EMPTY)[K]) => setForm(f => ({ ...f, [key]: value }));

  useEffect(() => {
    if (open) { setForm({ ...EMPTY, date: tomorrowIsoDate() }); setItems([{ product_id: "", quantity: 1 }]); setRequestKey(newIdempotencyKey()); }
  }, [open]);

  const totals = useMemo(() => items.reduce((acc, item) => {
    const p = products.find(x => x.id === item.product_id);
    if (!p) return acc;
    return { count: acc.count + item.quantity, weight: acc.weight + (p.weight_kg ?? 0) * item.quantity, price: acc.price + p.price * item.quantity };
  }, { count: 0, weight: 0, price: 0 }), [items, products]);
  const chosen = items.filter(i => i.product_id !== "" && i.quantity > 0);
  const fulfilling = useMemo(() => warehouses.map(w => w.id).filter(wid => chosen.every(i => {
    const p = products.find(x => x.id === i.product_id);
    return (p?.stock_by_warehouse.find(s => s.warehouse_id === wid)?.free ?? 0) >= i.quantity;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  })), [items, products, warehouses]);

  const { data: plan } = useQuery({ queryKey: ["commission-plan"], queryFn: () => unwrap(api.GET("/commission-plan")), enabled: open, staleTime: 300_000 });
  const defaultFee = plan ? Math.round((plan.base_fare + plan.fare_per_kg * totals.weight) / 1000) * 1000 : 0;

  // پیشنهاد راننده با هر تغییر وزن/زمان/مقصد (با کمی تأخیر تا هنگام تایپ شهر درخواست زیادی نرود)
  const query = useDebounced({
    weight: totals.weight, city: form.city.trim(), province: form.province,
    start: form.date && form.from ? localToIso(form.date, form.from) : "", end: form.date && form.to ? localToIso(form.date, form.to) : "",
  }, 400);
  const canSuggest = open && query.weight > 0 && query.city.length >= 2 && !!query.start && query.end > query.start;
  const suggestions = useQuery({
    queryKey: ["suggest", query],
    queryFn: () => unwrap(api.POST("/dispatch/suggest", { body: {
      total_weight_kg: query.weight, destination_city: query.city, destination_province: query.province || null,
      delivery_window_start: query.start, delivery_window_end: query.end,
    } })),
    enabled: canSuggest,
    placeholderData: keepPreviousData,
  });
  // اگر راننده انتخاب‌شده با تغییر زمان/مقصد دیگر مناسب نبود، به «خودکار» برگرد
  useEffect(() => {
    if (/^\d+$/.test(form.vehicle) && suggestions.data && !suggestions.data.candidates.some(c => String(c.vehicle_id) === form.vehicle)) {
      setForm(f => ({ ...f, vehicle: "auto" }));
    }
  }, [suggestions.data, form.vehicle]);

  const create = useMutation({
    mutationFn: (body: Schemas["OrderRequest"]) => unwrap(api.POST("/orders/", { body, params: { header: { "Idempotency-Key": requestKey } } })),
    onSuccess: order => {
      toast.success(`سفارش ${order.tracking_code} ثبت شد.`);
      for (const key of ["orders", "products", "vehicles", "stats"]) queryClient.invalidateQueries({ queryKey: [key] });
      onClose();
    },
    onError: e => { toast.error(errorMessage(e)); if (isServerError(e)) setRequestKey(newIdempotencyKey()); },
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const validItems = items.filter((i): i is { product_id: number; quantity: number } => i.product_id !== "" && i.quantity > 0);
    if (!validItems.length) { toast.error("حداقل یک کالا با تعداد معتبر انتخاب کنید."); return; }
    create.mutate({
      items: validItems,
      customer: { name: form.customerName, mobile: normalizeDigits(form.customerMobile) },
      recipient_name: form.recipientName || null,
      recipient_mobile: form.recipientMobile ? normalizeDigits(form.recipientMobile) : null,
      destination_province: form.province, destination_city: form.city, destination_address: form.address,
      destination_postal_code: form.postal ? normalizeDigits(form.postal) : null,
      size: form.size, priority: form.priority,
      delivery_window_start: localToIso(form.date, form.from), delivery_window_end: localToIso(form.date, form.to),
      notes: form.notes || null,
      warehouse_id: form.warehouse ? Number(form.warehouse) : null,
      vehicle_id: /^\d+$/.test(form.vehicle) ? Number(form.vehicle) : null,
      delivery_fee: form.fee.trim() ? Number(normalizeDigits(form.fee)) : null,
      auto_assign: form.vehicle === "auto",
    });
  }

  return (
    <Modal open={open} onClose={onClose} title="ثبت سفارش جدید" description="کالاها، مشتری، مقصد و زمان تحویل را وارد کنید." size="lg"
      footer={<>
        <Button variant="secondary" onClick={onClose}>انصراف</Button>
        <Button type="submit" form="order-form" loading={create.isPending}>ثبت سفارش</Button>
      </>}>
      <form id="order-form" onSubmit={onSubmit}>
        <Section title="اقلام سفارش">
          <div className="space-y-2">
            {items.map((item, index) => (
              <div className="grid grid-cols-[1fr_96px_40px] gap-2" key={index}>
                <Select required value={item.product_id} data-testid="order-item-product" aria-label="کالا"
                  onChange={e => setItems(list => list.map((x, i) => i === index ? { ...x, product_id: e.target.value ? Number(e.target.value) : "" } : x))}>
                  <option value="">انتخاب کالا...</option>
                  {products.map(p => <option key={p.id} value={p.id}>{p.name} ({p.sku}) — موجودی آزاد: {faNumber(p.free_stock)}</option>)}
                </Select>
                <Input type="number" min={1} required value={item.quantity} aria-label="تعداد" data-testid="order-item-qty"
                  onChange={e => setItems(list => list.map((x, i) => i === index ? { ...x, quantity: Number(e.target.value) } : x))} />
                <Button type="button" variant="ghost" size="icon" aria-label="حذف ردیف" disabled={items.length === 1}
                  onClick={() => setItems(list => list.filter((_, i) => i !== index))}><Trash2 className="size-4" /></Button>
                <WarehouseStockLine product={products.find(p => p.id === item.product_id)} quantity={item.quantity} warehouses={warehouses} ownOnly={me.role === "warehouse_manager"}
                  selected={form.warehouse ? Number(form.warehouse) : (fulfilling[0] ?? null)} />
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <Button type="button" variant="soft" size="sm" icon={<Plus className="size-4" />} onClick={() => setItems(list => [...list, { product_id: "", quantity: 1 }])}>افزودن کالا</Button>
            {totals.count > 0 && <span className="text-xs text-muted">جمع: {faNumber(totals.count)} عدد · {faNumber(totals.weight)} کیلوگرم · {faNumber(totals.price)} ریال</span>}
          </div>
        </Section>

        <Section title="مشتری و تحویل‌گیرنده">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="نام مشتری *"><Input required minLength={2} value={form.customerName} onChange={e => set("customerName", e.target.value)} data-testid="customer-name" /></Field>
            <Field label="موبایل مشتری *"><Input className="ltr" required placeholder="09121234567" value={form.customerMobile} onChange={e => set("customerMobile", e.target.value)} data-testid="customer-mobile" /></Field>
            <Field label="نام تحویل‌گیرنده" hint="خالی = خود مشتری"><Input value={form.recipientName} onChange={e => set("recipientName", e.target.value)} /></Field>
            <Field label="موبایل تحویل‌گیرنده"><Input className="ltr" value={form.recipientMobile} onChange={e => set("recipientMobile", e.target.value)} /></Field>
          </div>
        </Section>

        <Section title="مقصد">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="استان *">
              <Select required value={form.province} onChange={e => set("province", e.target.value)} data-testid="order-province">
                <option value="">انتخاب کنید...</option>{provinces.map(p => <option key={p} value={p}>{p}</option>)}
              </Select>
            </Field>
            <Field label="شهر *"><CitySelect required province={form.province} value={form.city} onChange={v => set("city", v)} testId="order-city" /></Field>
            <Field label="کد پستی"><Input className="ltr" value={form.postal} onChange={e => set("postal", e.target.value)} /></Field>
            <Field label="نشانی کامل *" className="sm:col-span-3"><Input required minLength={5} value={form.address} onChange={e => set("address", e.target.value)} data-testid="order-address" /></Field>
          </div>
        </Section>

        <Section title="زمان و نحوه ارسال">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="تاریخ تحویل *"><DateField required value={form.date} onChange={v => set("date", v)} testId="order-date" /></Field>
            <Field label="از ساعت *"><TimeField required value={form.from} onChange={v => set("from", v)} testId="order-from" /></Field>
            <Field label="تا ساعت *"><TimeField required value={form.to} onChange={v => set("to", v)} testId="order-to" /></Field>
            <Field label="سایز بسته">
              <Select value={form.size} onChange={e => set("size", e.target.value as typeof form.size)}>
                {Object.entries(PACKAGE_SIZES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </Select>
            </Field>
            {me.role === "org_admin" && (
              <Field label="انبار مبدأ">
                <Select value={form.warehouse} onChange={e => set("warehouse", e.target.value)}>
                  <option value="">خودکار{chosen.length && fulfilling.length ? ` (${warehouses.find(w => w.id === fulfilling[0])?.name ?? ""})` : ""}</option>
                  {warehouses.map(w => <option key={w.id} value={w.id}>{w.name}{chosen.length ? (fulfilling.includes(w.id) ? " — موجودی کافی" : " — موجودی ناکافی") : ""}</option>)}
                </Select>
                {chosen.length > 0 && fulfilling.length === 0 && <p className="mt-1 text-xs text-danger">هیچ انباری به‌تنهایی موجودی کافی برای همه اقلام ندارد.</p>}
              </Field>
            )}
            <Field label="کرایه حمل (ریال)" hint={plan ? `خالی = ${faNumber(defaultFee)} ریال طبق قانون سازمان` : undefined}>
              <Input inputMode="numeric" className="ltr" placeholder={plan ? faNumber(defaultFee) : ""} value={form.fee} onChange={e => set("fee", e.target.value)} data-testid="order-fee" />
            </Field>
            <div className="sm:col-span-3"><Checkbox label="فوری / اورژانسی" checked={form.priority} onChange={e => set("priority", e.target.checked)} /></div>
            <Field label="توضیحات" className="sm:col-span-3"><Input maxLength={1000} value={form.notes} onChange={e => set("notes", e.target.value)} /></Field>
          </div>
        </Section>

        <Section title="تخصیص راننده">
          <div className="mb-3 grid grid-cols-2 gap-2" role="radiogroup" data-testid="assign-mode">
            {[["auto", Sparkles, "بهترین پیشنهاد، خودکار", "هنگام ثبت، مناسب‌ترین راننده انتخاب می‌شود"],
              ["later", Clock3, "بعداً تخصیص می‌دهم", "سفارش «در انتظار تخصیص» می‌ماند"]].map(([value, Icon, title, hint]) => {
              const I = Icon as typeof Sparkles;
              const active = form.vehicle === value;
              return (
                <button key={value as string} type="button" role="radio" aria-checked={active} data-testid={`assign-mode-${value}`}
                  onClick={() => set("vehicle", value as string)}
                  className={cn("flex items-start gap-2 rounded-xl border p-3 text-start transition", active ? "border-brand bg-brand-soft" : "border-border hover:border-border-strong")}>
                  <I className={cn("mt-0.5 size-4 shrink-0", active ? "text-brand" : "text-muted")} />
                  <span><span className="block text-sm font-semibold">{title as string}</span><span className="text-xs text-muted">{hint as string}</span></span>
                </button>
              );
            })}
          </div>
          {canSuggest ? (
            <>
              <p className="mb-2 text-xs text-muted">یا یکی از رانندگان پیشنهادی را خودتان انتخاب کنید ({faNumber(Math.round(totals.weight))} کیلوگرم):</p>
              <SuggestionList data={suggestions.data} loading={suggestions.isFetching} weightKg={totals.weight}
                selected={/^\d+$/.test(form.vehicle) ? Number(form.vehicle) : null} onSelect={id => set("vehicle", String(id))} />
            </>
          ) : (
            <p className="rounded-xl bg-surface-2 px-4 py-3 text-sm text-muted">برای دیدن رانندگان پیشنهادی، کالا، شهر مقصد و زمان تحویل را وارد کنید.</p>
          )}
        </Section>
      </form>
    </Modal>
  );
}

/** مقدار با تأخیر — برای جلوگیری از درخواست به ازای هر حرف تایپ‌شده */
function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  const key = JSON.stringify(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ms]);
  return debounced;
}

/** زیر هر ردیف کالا: موجودی این کالا در هر انبار (انبار مبدأ پررنگ؛ کمتر از تعداد سفارش قرمز؛ صفر کم‌رنگ) */
function WarehouseStockLine({ product, quantity, selected, warehouses, ownOnly = false }: {
  product?: Schemas["ProductResponse"]; quantity: number; selected: number | null; warehouses: Schemas["WarehouseOut"][];
  /** مدیر انبار فقط موجودی انبار خودش را می‌بیند */
  ownOnly?: boolean;
}) {
  if (!product) return null;
  // موجودی آزاد = موجودی سالم − رزرو سفارش‌های باز
  const rows = warehouses.filter(w => !ownOnly || product.stock_by_warehouse.some(s => s.warehouse_id === w.id)).map(w => ({ id: w.id, name: w.name, city: w.city, quantity: product.stock_by_warehouse.find(s => s.warehouse_id === w.id)?.free ?? 0 }));
  return (
    <div className="col-span-3 -mt-0.5 flex flex-wrap gap-1.5 pb-1 text-[11px]" data-testid="warehouse-stock">
      {rows.map(r => (
        <span key={r.id} data-warehouse={r.id} data-quantity={r.quantity}
          className={cn("inline-flex items-center gap-1 rounded-md border px-2 py-0.5",
            r.id === selected ? "border-brand bg-brand-soft font-semibold text-brand-strong" : "border-border text-text-2",
            r.quantity === 0 ? "opacity-55" : r.quantity < quantity && "border-danger/40 text-danger")}>
          {r.name}{r.city && !r.name.includes(r.city) ? ` (${r.city})` : ""}: <b className="tnum">{faNumber(r.quantity)}</b>
        </span>
      ))}
    </div>
  );
}
