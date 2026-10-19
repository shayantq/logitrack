/** انبارهای سازمان (مرحله ۱۰): استان و شهر هر انبار، مبدأ مسیر سفارش‌ها روی نقشه است */
import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MapPin, MapPinOff, Pencil, Plus, Trash2, Warehouse } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { CitySelect } from "@/components/CitySelect";
import { useToast } from "@/components/Toast";
import { useProvinces, useWarehouses } from "@/hooks/data";
import { faNumber } from "@/lib/format";
import { Modal } from "@/ui/overlays";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, Select, Skeleton } from "@/ui/primitives";
import { confirmDialog } from "@/ui/dialogs";

type WarehouseRow = Schemas["WarehouseOut"];
const EMPTY = { name: "", province: "", city: "", location: "" };

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
                <Card key={w.id} className="flex flex-col p-5" data-testid="warehouse-card">
                  <div className="flex items-start gap-3">
                    <span className="grid size-11 shrink-0 place-items-center rounded-2xl bg-brand-soft text-brand"><Warehouse className="size-5" /></span>
                    <div className="min-w-0 flex-1">
                      <h3 className="truncate font-bold">{w.name}</h3>
                      <div className="mt-0.5 text-sm text-text-2">{w.province && w.city ? `${w.province} / ${w.city}` : "شهر ثبت نشده"}</div>
                    </div>
                  </div>
                  {w.location && <p className="mt-3 text-sm text-muted">{w.location}</p>}
                  <div className="mt-4 flex flex-wrap items-center gap-2">
                    {w.on_map ? <Badge tone="success"><MapPin className="size-3" />روی نقشه: {w.map_city}</Badge>
                      : <Badge tone="warning"><MapPinOff className="size-3" />روی نقشه نیست</Badge>}
                    <Badge tone="muted">{faNumber(w.products_count)} کالا</Badge>
                    {w.managers_count > 0 && <Badge tone="muted">{faNumber(w.managers_count)} مدیر</Badge>}
                  </div>
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

      {editing && <WarehouseForm warehouse={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function WarehouseForm({ warehouse, onClose }: { warehouse: WarehouseRow | null; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data: provinces = [] } = useProvinces();
  const [form, setForm] = useState(warehouse
    ? { name: warehouse.name, province: warehouse.province ?? "", city: warehouse.city ?? "", location: warehouse.location ?? "" } : EMPTY);
  const save = useMutation({
    mutationFn: () => {
      const body = { name: form.name, province: form.province, city: form.city, location: form.location || null };
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
      </form>
    </Modal>
  );
}
