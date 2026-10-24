/**
 * محل‌های انبار (فصل ۶): منطقه ← راهرو ← قفسه ← طبقه ← خانه، با نوع، ظرفیت (وزن، حجم، پالت) و قاعده اختلاط.
 * کالا فقط در محل انتهایی می‌نشیند؛ فقط موجودی محل‌های «نگهداری» و «برداشت» قابل تخصیص به سفارش است.
 */
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Ban, Boxes, MapPinned, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useToast } from "@/components/Toast";
import { LOCATION_LEVELS, LOCATION_LEVEL_ORDER, LOCATION_TYPES } from "@/lib/labels";
import { faDate, faNumber } from "@/lib/format";
import { confirmDialog } from "@/ui/dialogs";
import { Modal, Tooltip } from "@/ui/overlays";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorState, Field, Input, PageHeader, Select, Table, TableSkeleton, cn } from "@/ui/primitives";
import { LocationTypeBadge, StatusBadge, WarehousePicker, useInvalidateOperations, useLocations, useWarehouseChoice } from "./shared";

type Loc = Schemas["LocationOut"];
type LocIn = Schemas["LocationIn"];

function Gauge({ pct, label }: { pct?: number | null; label: string }) {
  if (pct == null) return null;
  const tone = pct >= 100 ? "bg-danger" : pct >= 80 ? "bg-warning" : "bg-success";
  return (
    <Tooltip content={`${label}: ${faNumber(pct)}٪`}>
      <div className="h-1.5 w-14 overflow-hidden rounded-full bg-surface-2" aria-label={`${label} ${pct}%`}>
        <div className={cn("h-full rounded-full transition-all", tone)} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
    </Tooltip>
  );
}

export default function LocationsPage() {
  const [params] = useSearchParams();
  const choice = useWarehouseChoice(params.get("warehouse"));
  const warehouseId = choice.value ? Number(choice.value) : null;
  const { data: locations, isLoading, error, refetch } = useLocations(warehouseId);
  const [editing, setEditing] = useState<Loc | "new" | { parent: Loc } | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [term, setTerm] = useState("");
  const visible = (locations ?? []).filter(l => !term || l.code.includes(term.toUpperCase()) || (l.name ?? "").includes(term));

  return (
    <>
      <PageHeader eyebrow="انبار" title="محل‌های انبار"
        subtitle="ساختار فیزیکی انبار با ظرفیت و قاعده اختلاط هر محل — جانمایی و تخصیص سفارش از همین ساختار پیروی می‌کند."
        actions={<Button icon={<Plus className="size-4" />} disabled={!warehouseId} onClick={() => setEditing("new")} data-testid="location-new">محل جدید</Button>} />
      <Card>
        <div className="grid gap-3 border-b border-border p-4 md:grid-cols-3">
          <WarehousePicker choice={choice} />
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" />
            <Input className="pr-10" placeholder="کد یا نام محل" value={term} onChange={e => setTerm(e.target.value)} data-testid="location-search" />
          </div>
          <p className="self-center text-xs text-muted">
            {choice.current?.type === "transit" ? "انبار در راه معمولاً محل‌بندی ندارد." : "بارکد هر محل (پیش‌فرض: کد انبار-کد محل) برای اسکن در جانمایی است."}
          </p>
        </div>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : !visible.length ? (
          <EmptyState icon={<MapPinned className="size-5" />} title={term ? "محلی با این کد نیست" : "هنوز محلی برای این انبار تعریف نشده"}
            text="انبار بدون محل هم کار می‌کند (موجودی «بدون محل»)؛ با تعریف محل تخلیه و قفسه‌های نگهداری، جانمایی و ظرفیت فعال می‌شود."
            action={!term && warehouseId && <Button size="sm" onClick={() => setEditing("new")}>تعریف اولین محل</Button>} />
        ) : (
          <Table testId="locations-table">
            <thead><tr><th>کد محل</th><th>سطح</th><th>نوع</th><th>موجودی</th><th>ظرفیت</th><th>اختلاط</th><th className="w-1" /></tr></thead>
            <tbody>
              {visible.map(l => (
                <tr key={l.id} data-testid="location-row" data-code={l.code} className={cn(!l.is_active && "opacity-50")}>
                  <td>
                    <button type="button" className="flex items-center gap-1.5 text-start hover:text-brand" style={{ paddingInlineStart: `${l.depth * 1.25}rem` }}
                      onClick={() => setOpenId(l.id)} data-testid="location-open">
                      <span className="font-mono text-sm font-semibold ltr">{l.code}</span>
                      {l.name && <span className="text-xs text-muted">{l.name}</span>}
                    </button>
                  </td>
                  <td className="text-xs text-text-2">{l.level_label}</td>
                  <td><div className="flex flex-wrap gap-1">
                    <LocationTypeBadge type={l.location_type} />
                    {l.is_blocked && <Tooltip content={l.block_reason ?? ""}><Badge tone="danger"><Ban className="size-3" />مسدود</Badge></Tooltip>}
                    {!l.is_active && <Badge>غیرفعال</Badge>}
                  </div></td>
                  <td className="tnum">{l.is_leaf ? (l.quantity ? `${faNumber(l.quantity)} عدد · ${faNumber(l.products)} کالا` : "خالی") : "—"}</td>
                  <td>
                    <div className="flex flex-col gap-1 text-[11px] text-muted">
                      {l.max_weight_kg != null && <span className="flex items-center gap-2"><Gauge pct={l.weight_pct} label="وزن" />{faNumber(l.weight_kg)} / {faNumber(l.max_weight_kg)} کیلو</span>}
                      {l.max_volume_m3 != null && <span className="flex items-center gap-2"><Gauge pct={l.volume_pct} label="حجم" />{faNumber(l.volume_m3)} / {faNumber(l.max_volume_m3)} م³</span>}
                      {l.max_pallets != null && <span className="flex items-center gap-2"><Gauge pct={l.pallets_pct} label="پالت" />{faNumber(l.pallets)} / {faNumber(l.max_pallets)} پالت</span>}
                      {l.max_weight_kg == null && l.max_volume_m3 == null && l.max_pallets == null && "نامحدود"}
                    </div>
                  </td>
                  <td className="text-xs text-text-2">
                    {[!l.allow_mixed_products && "تک‌کالا", !l.allow_mixed_lots && "تک‌بچ", !l.allow_mixed_owners && "تک‌مالک"].filter(Boolean).join("، ") || "آزاد"}
                  </td>
                  <td>
                    <div className="flex gap-1">
                      {l.level !== "bin" && !l.quantity && <Tooltip content="زیرمجموعه"><Button variant="ghost" size="icon" onClick={() => setEditing({ parent: l })} data-testid="location-child"><Plus className="size-4" /></Button></Tooltip>}
                      <Tooltip content="ویرایش"><Button variant="ghost" size="icon" onClick={() => setEditing(l)} data-testid="location-edit"><Pencil className="size-4" /></Button></Tooltip>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {editing && warehouseId && <LocationForm warehouseId={warehouseId} all={locations ?? []} editing={editing} onClose={() => setEditing(null)} />}
      <LocationDetail id={openId} onClose={() => setOpenId(null)} />
    </>
  );
}

const BLANK: LocIn = {
  parent_id: null, level: "bin", code: "", barcode: "", name: "", location_type: "storage", max_weight_kg: null,
  max_volume_m3: null, max_pallets: null, allow_mixed_products: true, allow_mixed_lots: true, allow_mixed_owners: true,
  is_active: true, is_blocked: false, block_reason: null,
};

function fromLocation(l: Loc): LocIn {
  return {
    parent_id: l.parent_id ?? null, level: l.level as LocIn["level"], code: l.code, barcode: l.barcode, name: l.name ?? "",
    location_type: l.location_type as LocIn["location_type"], max_weight_kg: l.max_weight_kg ?? null, max_volume_m3: l.max_volume_m3 ?? null,
    max_pallets: l.max_pallets ?? null, allow_mixed_products: l.allow_mixed_products, allow_mixed_lots: l.allow_mixed_lots,
    allow_mixed_owners: l.allow_mixed_owners, is_active: l.is_active, is_blocked: l.is_blocked, block_reason: l.block_reason ?? null,
  };
}

function LocationForm({ warehouseId, all, editing, onClose }: {
  warehouseId: number; all: Loc[]; editing: Loc | "new" | { parent: Loc }; onClose: () => void;
}) {
  const toast = useToast();
  const invalidate = useInvalidateOperations();
  const existing = editing !== "new" && !("parent" in editing) ? editing : null;
  const parent = editing !== "new" && "parent" in editing ? editing.parent : null;
  const [form, setForm] = useState<LocIn>(() => existing ? fromLocation(existing) : parent ? {
    ...BLANK, parent_id: parent.id, code: `${parent.code}-`, location_type: parent.location_type as LocIn["location_type"],
    level: LOCATION_LEVEL_ORDER[Math.min(LOCATION_LEVEL_ORDER.indexOf(parent.level) + 1, 4)] as LocIn["level"],
  } : BLANK);
  const set = <K extends keyof LocIn>(key: K, value: LocIn[K]) => setForm(f => ({ ...f, [key]: value }));
  const num = (v: string) => (v === "" ? null : Number(v));
  const parents = all.filter(l => l.id !== existing?.id && l.level !== "bin");
  const save = useMutation({
    mutationFn: () => {
      const body = { ...form, barcode: form.barcode || null, name: form.name || null };
      return existing
        ? unwrap(api.PUT("/locations/{location_id}", { params: { path: { location_id: existing.id } }, body }))
        : unwrap(api.POST("/warehouses/{warehouse_id}/locations", { params: { path: { warehouse_id: warehouseId } }, body }));
    },
    onSuccess: loc => { toast.success(existing ? `محل ${loc.code} ذخیره شد.` : `محل ${loc.code} ساخته شد.`); invalidate(); onClose(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: () => unwrap(api.DELETE("/locations/{location_id}", { params: { path: { location_id: existing!.id } } })),
    onSuccess: () => { toast.success("محل حذف شد."); invalidate(); onClose(); },
    onError: e => toast.error(errorMessage(e)),
  });

  return (
    <Modal open onClose={onClose} size="lg" testId="location-form" title={existing ? `ویرایش محل ${existing.code}` : "محل جدید"}
      description="زیرمجموعه هر محل سطح پایین‌تری دارد؛ کالا فقط در محل‌های انتهایی نگهداری می‌شود."
      footer={<>
        {existing && <Button variant="outline-danger" className="me-auto" icon={<Trash2 className="size-4" />} loading={remove.isPending}
          onClick={() => confirmDialog({ title: `محل ${existing.code} حذف شود؟`, text: "فقط محل بی‌سابقه حذف می‌شود؛ بقیه را غیرفعال کنید.", danger: true, confirmLabel: "حذف" }).then(ok => ok && remove.mutate())}>حذف</Button>}
        <Button variant="secondary" onClick={onClose}>انصراف</Button>
        <Button type="submit" form="location-form-el" loading={save.isPending} data-testid="location-save">ذخیره</Button>
      </>}>
      <form id="location-form-el" className="grid gap-4 sm:grid-cols-3" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        <Field label="کد محل *" hint="مثلاً A-01-03-2 (حروف لاتین، عدد، خط تیره)">
          <Input required className="ltr uppercase" maxLength={32} pattern="[0-9A-Za-z._\/\-]+" value={form.code} onChange={e => set("code", e.target.value)} data-testid="loc-code" />
        </Field>
        <Field label="سطح">
          <Select value={form.level} onChange={e => set("level", e.target.value as LocIn["level"])} data-testid="loc-level">
            {LOCATION_LEVEL_ORDER.map(l => <option key={l} value={l}>{LOCATION_LEVELS[l]}</option>)}
          </Select>
        </Field>
        <Field label="نوع محل" hint={LOCATION_TYPES[form.location_type]?.hint}>
          <Select value={form.location_type} onChange={e => set("location_type", e.target.value as LocIn["location_type"])} data-testid="loc-type">
            {Object.entries(LOCATION_TYPES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
        </Field>
        <Field label="محل مادر">
          <Select value={form.parent_id ? String(form.parent_id) : ""} onChange={e => set("parent_id", e.target.value ? Number(e.target.value) : null)} data-testid="loc-parent">
            <option value="">— مستقیم زیر انبار —</option>
            {parents.map(l => <option key={l.id} value={l.id}>{"— ".repeat(l.depth)}{l.code} ({l.level_label})</option>)}
          </Select>
        </Field>
        <Field label="بارکد" hint="خالی = کد انبار-کد محل"><Input className="ltr uppercase" maxLength={64} value={form.barcode ?? ""} onChange={e => set("barcode", e.target.value)} /></Field>
        <Field label="نام" hint="اختیاری"><Input maxLength={100} value={form.name ?? ""} onChange={e => set("name", e.target.value)} /></Field>
        <Field label="حداکثر وزن (کیلوگرم)" hint="خالی = نامحدود"><Input type="number" min={0.01} step="0.01" value={form.max_weight_kg ?? ""} onChange={e => set("max_weight_kg", num(e.target.value))} data-testid="loc-max-weight" /></Field>
        <Field label="حداکثر حجم (مترمکعب)" hint="از ابعاد کالا"><Input type="number" min={0.001} step="0.001" value={form.max_volume_m3 ?? ""} onChange={e => set("max_volume_m3", num(e.target.value))} /></Field>
        <Field label="حداکثر پالت" hint="از «تعداد در پالت» کالا"><Input type="number" min={1} value={form.max_pallets ?? ""} onChange={e => set("max_pallets", num(e.target.value))} data-testid="loc-max-pallets" /></Field>
        <div className="space-y-2 sm:col-span-3">
          <div className="text-xs font-semibold text-text-2">قواعد اختلاط</div>
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            <Checkbox label="چند کالای مختلف" checked={form.allow_mixed_products} onChange={e => set("allow_mixed_products", e.target.checked)} data-testid="loc-mixed-products" />
            <Checkbox label="چند بچ از یک کالا" checked={form.allow_mixed_lots} onChange={e => set("allow_mixed_lots", e.target.checked)} />
            <Checkbox label="کالای چند مالک" checked={form.allow_mixed_owners} onChange={e => set("allow_mixed_owners", e.target.checked)} />
          </div>
        </div>
        {existing && (
          <div className="grid gap-3 sm:col-span-3 sm:grid-cols-3">
            <Checkbox label="فعال" checked={form.is_active} onChange={e => set("is_active", e.target.checked)} />
            <Checkbox label="مسدود (کالای جدید نمی‌گیرد)" checked={form.is_blocked} onChange={e => set("is_blocked", e.target.checked)} data-testid="loc-blocked" />
            {form.is_blocked && <Input required minLength={2} maxLength={200} placeholder="دلیل مسدودی" value={form.block_reason ?? ""} onChange={e => set("block_reason", e.target.value)} />}
          </div>
        )}
      </form>
    </Modal>
  );
}

function LocationDetail({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { data: loc, isLoading } = useQuery({
    queryKey: ["location", id],
    queryFn: () => unwrap(api.GET("/locations/{location_id}", { params: { path: { location_id: id! } } })),
    enabled: id != null,
  });
  return (
    <Modal open={id != null} onClose={onClose} size="lg" testId="location-detail"
      title={loc ? <span className="flex items-center gap-2"><span className="font-mono ltr">{loc.code}</span><LocationTypeBadge type={loc.location_type} /></span> : "محل"}
      description={loc && `${loc.level_label} · بارکد ${loc.barcode}${loc.allocatable ? " · قابل تخصیص به سفارش" : " · غیرقابل تخصیص"}`}>
      {isLoading || !loc ? <div className="h-32 animate-pulse rounded-xl bg-surface-2" /> : !loc.contents?.length ? (
        <EmptyState icon={<Boxes className="size-5" />} title="این محل خالی است" />
      ) : (
        <div className="overflow-x-auto">
          <table className="table-base" data-testid="location-contents">
            <thead><tr><th>کالا</th><th>وضعیت</th><th>بچ / سریال</th><th>انقضا</th><th>مالک</th><th>مقدار</th></tr></thead>
            <tbody>
              {loc.contents.map(c => (
                <tr key={c.balance_id}>
                  <td><div className="font-medium">{c.product_name}</div><div className="font-mono text-xs text-muted">{c.product_sku}</div></td>
                  <td><StatusBadge status={c.stock_status} /></td>
                  <td className="font-mono text-xs ltr text-start">{[c.lot_number, c.serial_number].filter(Boolean).join(" / ") || "—"}</td>
                  <td className="text-xs">{c.expiry_date ? faDate(c.expiry_date) : "—"}</td>
                  <td className="text-xs">{c.owner_name ?? "سازمان"}</td>
                  <td className="tnum font-bold">{faNumber(c.quantity)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}
