/**
 * انبارهای سازمان (مرحله ۱۰): استان و شهر هر انبار، مبدأ مسیر سفارش‌ها روی نقشه است.
 * نوع انبار (عمومی، قرنطینه، در راه، سایت و …)، کد یکتا و انبار مادر — قواعد در app/services/warehouse_service.py
 */
import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { CornerDownLeft, MapPin, MapPinOff, MapPinned, Pencil, Plus, Trash2, Truck, Warehouse } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { CitySelect } from "@/components/CitySelect";
import { useToast } from "@/components/Toast";
import { useProvinces, useWarehouses } from "@/hooks/data";
import { WAREHOUSE_TYPES } from "@/lib/labels";
import { faNumber } from "@/lib/format";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorState, Field, Input, PageHeader, Select, Skeleton, cn } from "@/ui/primitives";
import { confirmDialog } from "@/ui/dialogs";

type WarehouseRow = Schemas["WarehouseOut"];
type WarehouseType = Schemas["WarehouseIn"]["type"];
const EMPTY = { name: "", province: "", city: "", location: "", code: "", type: "general" as WarehouseType, parent: "", active: true };

export default function WarehousesPage() {
  const me = useMe();
  const toast = useToast();
  const queryClient = useQueryClient();
  const isAdmin = me.role === "org_admin";
  const { data: warehouses, isLoading, error, refetch } = useWarehouses();
  const [editing, setEditing] = useState<WarehouseRow | "new" | null>(null);

  const remove = useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE("/warehouses/{warehouse_id}", { params: { path: { warehouse_id: id } } })),
    onSuccess: () => { toast.success("انبار حذف شد."); queryClient.invalidateQueries({ queryKey: ["warehouses"] }); },
    onError: e => toast.error(errorMessage(e)),
  });
  const missing = (warehouses ?? []).filter(w => !w.on_map).length;

  return (
    <>
      <PageHeader eyebrow="انبار" title="انبارها" subtitle="شهر هر انبار، نقطه شروع مسیر سفارش‌هایش روی نقشه است"
        actions={isAdmin && <Button icon={<Plus className="size-4" />} onClick={() => setEditing("new")} data-testid="warehouse-new">انبار جدید</Button>} />

      {missing > 0 && (
        <div className="mb-5 flex items-center gap-3 rounded-xl border border-warning/30 bg-warning-soft/50 px-4 py-3 text-sm" data-testid="warehouse-missing-city">
          <MapPinOff className="size-4 shrink-0 text-warning" />
          {faNumber(missing)} انبار شهر مشخصی ندارد؛ سفارش‌های آن روی نقشه نمایش داده نمی‌شوند.{isAdmin && " با «ویرایش» استان و شهرش را ثبت کنید."}
        </div>
      )}

      {isLoading ? <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map(i => <Skeleton key={i} className="h-40" />)}</div>
        : error ? <ErrorState error={error} onRetry={refetch} />
          : !warehouses?.length ? (
            <Card><EmptyState icon={<Warehouse className="size-5" />} title="هنوز انباری تعریف نشده"
              text="برای ثبت کالا و ارسال سفارش، ابتدا یک انبار با استان و شهرش بسازید."
              action={isAdmin && <Button icon={<Plus className="size-4" />} onClick={() => setEditing("new")}>ساخت اولین انبار</Button>} /></Card>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="warehouses-list">
              {warehouses.map(w => (
                <Card key={w.id} className={cn("flex flex-col p-5", !w.is_active && "opacity-60")} data-testid="warehouse-card" data-type={w.type} data-code={w.code}>
                  <div className="flex items-start gap-3">
                    <span className="grid size-11 shrink-0 place-items-center rounded-2xl bg-brand-soft text-brand"><Warehouse className="size-5" /></span>
                    <div className="min-w-0 flex-1">
                      <h3 className="flex items-center gap-2 font-bold"><span className="truncate">{w.name}</span><span className="font-mono text-xs font-medium text-muted ltr">{w.code}</span></h3>
                      <div className="mt-0.5 text-sm text-text-2">{w.province && w.city ? `${w.province} / ${w.city}` : "شهر ثبت نشده"}</div>
                      {w.parent_name && <div className="mt-1 flex items-center gap-1 text-xs text-muted"><CornerDownLeft className="size-3" />زیرمجموعه {w.parent_name}</div>}
                    </div>
                  </div>
                  {w.location && <p className="mt-3 text-sm text-muted">{w.location}</p>}
                  <div className="mt-4 flex flex-wrap items-center gap-2">
                    <Badge tone={w.type === "general" ? "muted" : "brand"}>{w.type_label}</Badge>
                    {w.ships_orders && w.is_active && <Badge tone="success"><Truck className="size-3" />ارسال سفارش</Badge>}
                    {!w.is_active && <Badge tone="danger">غیرفعال</Badge>}
                    {w.on_map ? <Badge tone="success"><MapPin className="size-3" />روی نقشه: {w.map_city}</Badge>
                      : <Badge tone="warning"><MapPinOff className="size-3" />روی نقشه نیست</Badge>}
                    {w.holds_stock && <Badge tone="muted">{faNumber(w.products_count)} کالا · {faNumber(w.on_hand)} واحد</Badge>}
                    {w.managers_count > 0 && <Badge tone="muted">{faNumber(w.managers_count)} مدیر</Badge>}
                  </div>
                  {w.holds_stock && (
                    <Link to={`/app/locations?warehouse=${w.id}`} className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline" data-testid="warehouse-locations">
                      <MapPinned className="size-3.5" />محل‌ها، ظرفیت و قاعده اختلاط
                    </Link>
                  )}
                  {isAdmin && (
                    <div className="mt-auto flex gap-2 pt-4">
                      <Button size="sm" variant="secondary" icon={<Pencil className="size-3.5" />} onClick={() => setEditing(w)} data-testid="warehouse-edit">ویرایش</Button>
                      <Button size="sm" variant="ghost" className="text-danger" icon={<Trash2 className="size-3.5" />} loading={remove.isPending && remove.variables === w.id}
                        onClick={() => confirmDialog({ title: `انبار «${w.name}» حذف شود؟`, confirmLabel: "حذف انبار", danger: true }).then(ok => ok && remove.mutate(w.id))}>حذف</Button>
                    </div>
                  )}
                </Card>
              ))}
            </div>
          )}

      {editing && <WarehouseForm warehouse={editing === "new" ? null : editing} all={warehouses ?? []} onClose={() => setEditing(null)} />}
    </>
  );
}

function WarehouseForm({ warehouse, all, onClose }: { warehouse: WarehouseRow | null; all: WarehouseRow[]; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data: provinces = [] } = useProvinces();
  const [form, setForm] = useState(warehouse
    ? { name: warehouse.name, province: warehouse.province ?? "", city: warehouse.city ?? "", location: warehouse.location ?? "",
        code: warehouse.code, type: warehouse.type as WarehouseType, parent: warehouse.parent_id ? String(warehouse.parent_id) : "",
        active: warehouse.is_active } : EMPTY);
  // انبار مادر: هر انبار دیگری جز خودش (چرخه را سرور هم رد می‌کند)
  const parents = all.filter(w => w.id !== warehouse?.id);
  const save = useMutation({
    mutationFn: () => {
      const body = { name: form.name, province: form.province, city: form.city, location: form.location || null,
        code: form.code.trim() || null, type: form.type, parent_id: form.parent ? Number(form.parent) : null, is_active: form.active };
      return warehouse
        ? unwrap(api.PUT("/warehouses/{warehouse_id}", { params: { path: { warehouse_id: warehouse.id } }, body }))
        : unwrap(api.POST("/warehouses/", { body }));
    },
    onSuccess: () => {
      toast.success(warehouse ? "انبار ویرایش شد." : "انبار ساخته شد.");
      queryClient.invalidateQueries({ queryKey: ["warehouses"] });
      queryClient.invalidateQueries({ queryKey: ["map-orders"] });
      onClose();
    },
    onError: e => toast.error(errorMessage(e)),
  });

  return (
    <Modal open onClose={onClose} title={warehouse ? `ویرایش ${warehouse.name}` : "انبار جدید"} testId="warehouse-form"
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="warehouse-form" loading={save.isPending}>ذخیره</Button></>}>
      <form id="warehouse-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        <Field label="نام انبار *" className="sm:col-span-2"><Input required minLength={2} maxLength={120} value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} data-testid="wh-name" /></Field>
        <Field label="استان *">
          <Select required value={form.province} onChange={e => setForm(f => ({ ...f, province: e.target.value, city: "" }))} data-testid="wh-province">
            <option value="">انتخاب کنید</option>{provinces.map(p => <option key={p} value={p}>{p}</option>)}
          </Select>
        </Field>
        <Field label="شهر *">
          <CitySelect required province={form.province} value={form.city} onChange={v => setForm(f => ({ ...f, city: v }))} testId="wh-city" />
        </Field>
        <Field label="نشانی" hint="اختیاری" className="sm:col-span-2"><Input maxLength={300} value={form.location} onChange={e => setForm(f => ({ ...f, location: e.target.value }))} /></Field>
        <Field label="نوع انبار" hint={WAREHOUSE_TYPES[form.type]?.hint}>
          <Select value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value as WarehouseType }))} data-testid="wh-type">
            {Object.entries(WAREHOUSE_TYPES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
        </Field>
        <Field label="کد انبار" hint="خالی = ساخت خودکار (WH-01، …)">
          <Input className="ltr uppercase" maxLength={16} pattern="[A-Za-z0-9][A-Za-z0-9\-]*" value={form.code} onChange={e => setForm(f => ({ ...f, code: e.target.value }))} data-testid="wh-code" />
        </Field>
        <Field label="انبار مادر" hint="اختیاری — مثلاً سایتی که این انبار در آن است">
          <Select value={form.parent} onChange={e => setForm(f => ({ ...f, parent: e.target.value }))} data-testid="wh-parent">
            <option value="">— بدون انبار مادر —</option>
            {parents.map(w => <option key={w.id} value={w.id}>{"— ".repeat(w.depth)}{w.name} ({w.code})</option>)}
          </Select>
        </Field>
        {warehouse && (
          <div className="flex items-end pb-2">
            <Checkbox label="فعال (رسید و سفارش جدید می‌پذیرد)" checked={form.active} onChange={e => setForm(f => ({ ...f, active: e.target.checked }))} data-testid="wh-active" />
          </div>
        )}
      </form>
    </Modal>
  );
}
