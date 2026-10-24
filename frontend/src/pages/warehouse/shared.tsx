/**
 * اجزای مشترک عملیات انبار (محل‌ها، رسید، بازرسی، جانمایی، کاردکس):
 * انتخاب انبار (مدیر انبار همیشه انبار خودش)، فهرست محل‌ها، نشان وضعیت کیفی و پنجره بازرسی کیفی.
 */
import { useState, type FormEvent, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { api, errorMessage, isServerError, newIdempotencyKey, unwrap } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { useWarehouses } from "@/hooks/data";
import { LOCATION_TYPES, STOCK_STATUS, type StockStatus } from "@/lib/labels";
import { faNumber } from "@/lib/format";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Field, Input, Select } from "@/ui/primitives";

export const STATUS_KEYS = Object.keys(STOCK_STATUS) as StockStatus[];

export function StatusBadge({ status }: { status: string }) {
  const s = STOCK_STATUS[status as StockStatus];
  return <Badge tone={s?.tone ?? "muted"}>{s?.label ?? status}</Badge>;
}

export function LocationTypeBadge({ type }: { type: string }) {
  const t = LOCATION_TYPES[type];
  return <Badge tone={t?.tone ?? "muted"}>{t?.label ?? type}</Badge>;
}

/** همه کلیدهای کش موجودی که پس از هر عملیات انبار تازه می‌شوند */
export function useInvalidateOperations() {
  const queryClient = useQueryClient();
  return () => ["products", "movements", "documents", "stock-buckets", "locations", "location", "receipts", "receipt",
    "putaway-tasks", "inspections", "positions", "balances", "stock-card", "warehouses"]
    .forEach(key => queryClient.invalidateQueries({ queryKey: [key] }));
}

/** انبار جاری صفحه: ادمین انتخاب می‌کند (پیش‌فرض اولین انبار کالادار)، مدیر انبار همیشه انبار خودش */
export function useWarehouseChoice(initial?: string | null, defaultFirst = true) {
  const me = useMe();
  const { data: warehouses = [] } = useWarehouses();
  const stockWarehouses = warehouses.filter(w => w.holds_stock);
  const [chosen, setChosen] = useState(initial ?? "");
  const isManager = me.role === "warehouse_manager";
  const value = isManager ? String(me.warehouse_id ?? "")
    : chosen || (defaultFirst && stockWarehouses[0] ? String(stockWarehouses[0].id) : "");
  return { value, set: setChosen, isManager, warehouses: stockWarehouses, current: warehouses.find(w => String(w.id) === value) };
}

export function WarehousePicker({ choice, testId = "warehouse-picker", allowAll = false }: {
  choice: ReturnType<typeof useWarehouseChoice>; testId?: string; allowAll?: boolean;
}) {
  return (
    <Select value={choice.value} disabled={choice.isManager} onChange={e => choice.set(e.target.value)} aria-label="انبار" data-testid={testId}>
      {allowAll && <option value="">همه انبارها</option>}
      {choice.warehouses.map(w => <option key={w.id} value={w.id}>{w.name} ({w.code})</option>)}
    </Select>
  );
}

export const useLocations = (warehouseId?: number | null) =>
  useQuery({
    queryKey: ["locations", warehouseId],
    queryFn: () => unwrap(api.GET("/warehouses/{warehouse_id}/locations", { params: { path: { warehouse_id: warehouseId! } } })),
    enabled: !!warehouseId,
  });

/** انتخاب محل انتهایی یک انبار (اختیاری: فقط نوع‌های مشخص) */
export function LocationSelect({ warehouseId, value, onChange, types, empty = "بدون محل", testId, required }: {
  warehouseId?: number | null; value: string; onChange: (v: string) => void; types?: string[]; empty?: string | null;
  testId?: string; required?: boolean;
}) {
  const { data: locations = [] } = useLocations(warehouseId);
  const options = locations.filter(l => l.is_leaf && l.is_active && (!types || types.includes(l.location_type)));
  return (
    <Select value={value} onChange={e => onChange(e.target.value)} data-testid={testId} required={required} searchable>
      {empty !== null && <option value="">{empty}</option>}
      {options.map(l => (
        <option key={l.id} value={l.id}>{l.code} — {LOCATION_TYPES[l.location_type]?.label ?? l.location_type}
          {l.is_blocked ? " (مسدود)" : ""}{l.quantity ? ` · ${faNumber(l.quantity)} عدد` : ""}</option>
      ))}
    </Select>
  );
}

/** ورودی اسکن: بارکدخوان مثل صفحه‌کلید تایپ می‌کند و Enter می‌زند؛ Enter به ورودی بعدی می‌رود */
export function scanKeyDown(next?: () => void) {
  return (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && next) {
      e.preventDefault();
      next();
    }
  };
}

type InspectTarget = {
  product_id: number; product_name: string; warehouse_id: number; from_status: string; quantity: number;
  location_id?: number | null; location_code?: string | null; lot_number?: string | null; receipt_id?: number | null;
};

/** پنجره بازرسی کیفی: تقسیم مقدار بازرسی‌شده بین نتیجه‌ها (تأیید، قرنطینه، مردود، معیوب، آسیب‌دیده، ...) */
export function InspectModal({ target, onClose }: { target: InspectTarget | null; onClose: () => void }) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const { data: transitions = [] } = useQuery({
    queryKey: ["quality-transitions"],
    queryFn: () => unwrap(api.GET("/quality/transitions")),
    staleTime: Infinity,
  });
  const [rows, setRows] = useState<{ status: string; quantity: string; reason: string }[]>([]);
  const [note, setNote] = useState("");
  const [key, setKey] = useState(newIdempotencyKey);
  const allowed = transitions.filter(t => t.from === target?.from_status && t.allowed).map(t => t.to);
  const lines = rows.length ? rows : target ? [{ status: allowed.includes("available") ? "available" : allowed[0] ?? "", quantity: String(target.quantity), reason: "" }] : [];
  const total = lines.reduce((s, r) => s + (Number(r.quantity) || 0), 0);
  const update = (i: number, patch: Partial<typeof lines[number]>) => setRows(lines.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  function close() { setRows([]); setNote(""); setKey(newIdempotencyKey()); onClose(); }
  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/quality/inspections", {
      params: { header: { "Idempotency-Key": key } },
      body: {
        product_id: target!.product_id, warehouse_id: target!.warehouse_id, from_status: target!.from_status as StockStatus,
        location_id: target!.location_id ?? null, lot_number: target!.lot_number ?? null, receipt_id: target!.receipt_id ?? null,
        note: note || null,
        results: lines.map(r => ({ status: r.status as StockStatus, quantity: Number(r.quantity), reason: r.reason || null })),
      },
    })),
    onSuccess: inspection => { toast.success(`بازرسی ${inspection.code} ثبت شد.`); invalidate(); close(); },
    onError: e => { toast.error(errorMessage(e)); if (isServerError(e)) setKey(newIdempotencyKey()); },
  });

  return (
    <Modal open={target != null} onClose={close} size="lg" testId="inspect-modal" title={target ? `بازرسی کیفی — ${target.product_name}` : "بازرسی کیفی"}
      description={target && `${faNumber(target.quantity)} عدد «${STOCK_STATUS[target.from_status as StockStatus]?.label ?? target.from_status}»`
        + `${target.location_code ? ` در محل ${target.location_code}` : ""}${target.lot_number ? ` · بچ ${target.lot_number}` : ""}. وضعیت کیفی عوض می‌شود، محل نه.`}
      footer={<><Button variant="secondary" onClick={close}>انصراف</Button>
        <Button type="submit" form="inspect-form" loading={save.isPending} disabled={!allowed.length || total <= 0 || (target != null && total > target.quantity)}>ثبت نتیجه بازرسی</Button></>}>
      {target && !allowed.length ? <p className="text-sm text-danger">برای نقش شما تغییری از این وضعیت مجاز نیست؛ ادمین سازمان باید تصمیم بگیرد.</p> : (
        <form id="inspect-form" className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
          {lines.map((r, i) => (
            <div key={i} className="grid items-end gap-2 sm:grid-cols-[1fr_7rem_1.4fr_auto]" data-testid="inspect-row">
              <Field label="نتیجه">
                <Select value={r.status} onChange={e => update(i, { status: e.target.value })} data-testid="inspect-status">
                  {allowed.map(s => <option key={s} value={s}>{STOCK_STATUS[s as StockStatus]?.label ?? s}</option>)}
                </Select>
              </Field>
              <Field label="تعداد"><Input type="number" min={1} required value={r.quantity} onChange={e => update(i, { quantity: e.target.value })} data-testid="inspect-qty" /></Field>
              <Field label={r.status === "available" ? "توضیح (اختیاری)" : "نوع ایراد / دلیل *"}>
                <Input required={r.status !== "available"} maxLength={300} value={r.reason} onChange={e => update(i, { reason: e.target.value })} data-testid="inspect-reason" />
              </Field>
              <Button type="button" variant="ghost" size="icon" disabled={lines.length === 1} onClick={() => setRows(lines.filter((_, j) => j !== i))} aria-label="حذف ردیف"><Trash2 className="size-4" /></Button>
            </div>
          ))}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button type="button" size="sm" variant="soft" icon={<Plus className="size-4" />} disabled={lines.length >= allowed.length}
              onClick={() => setRows([...lines, { status: allowed.find(s => !lines.some(r => r.status === s)) ?? allowed[0], quantity: "1", reason: "" }])}
              data-testid="inspect-add">نتیجه دیگر</Button>
            <span className={`text-sm tnum ${target && total > target.quantity ? "text-danger" : "text-muted"}`}>
              جمع: {faNumber(total)} از {faNumber(target?.quantity ?? 0)}
            </span>
          </div>
          <Field label="یادداشت بازرس"><Input maxLength={500} value={note} onChange={e => setNote(e.target.value)} /></Field>
        </form>
      )}
    </Modal>
  );
}
