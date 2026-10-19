import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Truck } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { CityPicker } from "@/components/CitySelect";
import { VehicleStatusBadge } from "@/components/StatusBadges";
import { useToast } from "@/components/Toast";
import { useUsers, useVehicles } from "@/hooks/data";
import { VEHICLE_STATUS, VEHICLE_TYPES } from "@/lib/labels";
import { faNumber } from "@/lib/format";
import { Modal, Tooltip } from "@/ui/overlays";
import { Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, Select, StatCard, Table, TableSkeleton } from "@/ui/primitives";
import { confirmDialog } from "@/ui/dialogs";

type VehicleRequest = Schemas["VehicleRequest"];
const EMPTY = { license_plate: "", vehicle_type: "van", vehicle_name: "", capacity_kg: "1000", vehicle_status: "available", driver_id: "", city: "" };

export default function VehiclesPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data: vehicles, isLoading, error, refetch } = useVehicles();
  const { data: users = [] } = useUsers();
  // فقط رانندگان احراز هویت‌شده خودرو و سفارش می‌گیرند
  const drivers = users.filter(u => u.role === "driver" && (u.driver_status ?? "approved") === "approved");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm(f => ({ ...f, [k]: e.target.value }));
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["vehicles"] });

  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/vehicles/", { body: {
      license_plate: form.license_plate, vehicle_type: form.vehicle_type as VehicleRequest["vehicle_type"],
      vehicle_name: form.vehicle_name || null, capacity_kg: Number(form.capacity_kg),
      vehicle_status: form.vehicle_status as VehicleRequest["vehicle_status"], driver_id: Number(form.driver_id), city: form.city || null,
    } })),
    onSuccess: () => { toast.success("خودرو ثبت شد."); invalidate(); setOpen(false); setForm(EMPTY); },
    onError: e => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE("/vehicles/{vehicle_id}", { params: { path: { vehicle_id: id } } })),
    onSuccess: () => { toast.success("خودرو حذف شد."); invalidate(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const changeDriver = useMutation({
    mutationFn: ({ id, driver }: { id: number; driver: number }) =>
      unwrap(api.PUT("/vehicles/{vehicle_id}/driver", { params: { path: { vehicle_id: id } }, body: { driver_id: driver } })),
    onSuccess: () => { toast.success("راننده خودرو تغییر کرد."); invalidate(); },
    onError: e => toast.error(errorMessage(e)),
  });

  const list = vehicles ?? [];
  const count = (s: string) => list.filter(v => v.status === s).length;

  return (
    <>
      <PageHeader eyebrow="تیم" title="ناوگان حمل‌ونقل" subtitle="خودروها، ظرفیت و راننده هر خودرو"
        actions={<Button icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>خودروی جدید</Button>} />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="کل خودروها" value={faNumber(list.length)} icon={<Truck className="size-[18px]" />} />
        <StatCard label="در دسترس" value={faNumber(count("available"))} tone="success" />
        <StatCard label="در مسیر" value={faNumber(count("busy") + count("on_route"))} tone="info" />
        <StatCard label="تعمیرات / غیرفعال" value={faNumber(count("maintenance") + count("inactive"))} tone="warning" />
      </div>
      <Card>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : list.length === 0 ? (
          <EmptyState icon={<Truck className="size-5" />} title="خودرویی ثبت نشده" action={<Button size="sm" onClick={() => setOpen(true)}>افزودن خودرو</Button>} />
        ) : (
          <Table testId="vehicles-table">
            <thead><tr><th>خودرو</th><th>پلاک</th><th>راننده</th><th>شهر</th><th>ظرفیت</th><th>وضعیت</th><th className="w-1" /></tr></thead>
            <tbody>
              {list.map(v => (
                <tr key={v.id}>
                  <td><div className="font-medium">{v.model ?? "—"}</div><div className="text-xs text-muted">{VEHICLE_TYPES[v.type ?? ""] ?? v.type}</div></td>
                  <td className="font-mono">{v.license_plate ?? "—"}</td>
                  <td className="min-w-48">
                    <Select className="h-9" value={v.driver_id ?? ""} aria-label="راننده"
                      onChange={e => e.target.value && Number(e.target.value) !== v.driver_id && changeDriver.mutate({ id: v.id, driver: Number(e.target.value) })}>
                      {!drivers.some(d => d.id === v.driver_id) && <option value="">—</option>}
                      {drivers.map(d => <option key={d.id} value={d.id}>{d.full_name ?? d.username}{d.driver_code ? ` (${d.driver_code})` : ""}</option>)}
                    </Select>
                  </td>
                  <td className="text-text-2">{v.city ?? "—"}</td>
                  <td className="tnum">{faNumber(v.capacity_kg)} کیلوگرم</td>
                  <td><VehicleStatusBadge status={v.status} /></td>
                  <td><Tooltip content="حذف"><Button variant="ghost" size="icon" className="hover:text-danger" onClick={() => confirmDialog({ title: "این خودرو حذف شود؟", text: <>پلاک: <span className="font-semibold">{v.license_plate}</span> — این کار برگشت‌پذیر نیست.</>, confirmLabel: "حذف خودرو", danger: true }).then(ok => ok && remove.mutate(v.id))}><Trash2 className="size-4" /></Button></Tooltip></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Modal open={open} onClose={() => setOpen(false)} title="افزودن خودرو"
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>انصراف</Button><Button type="submit" form="vehicle-form" loading={create.isPending}>ثبت خودرو</Button></>}>
        <form id="vehicle-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
          <Field label="نام خودرو"><Input placeholder="مثلاً وانت نیسان" value={form.vehicle_name} onChange={set("vehicle_name")} /></Field>
          <Field label="پلاک *"><Input required minLength={3} maxLength={15} value={form.license_plate} onChange={set("license_plate")} /></Field>
          <Field label="نوع"><Select value={form.vehicle_type} onChange={set("vehicle_type")}>{Object.entries(VEHICLE_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
          <Field label="ظرفیت (کیلوگرم) *"><Input type="number" min={1} required value={form.capacity_kg} onChange={set("capacity_kg")} /></Field>
          <Field label="راننده *" hint={drivers.length ? "فقط رانندگان تأییدشده نمایش داده می‌شوند." : "ابتدا یک راننده بسازید یا پرونده راننده‌ای را تأیید کنید."}>
            <Select required value={form.driver_id}
              onChange={e => { const d = drivers.find(x => x.id === Number(e.target.value)); setForm(f => ({ ...f, driver_id: e.target.value, city: f.city || d?.city || "" })); }}>
              <option value="">انتخاب راننده...</option>
              {drivers.map(d => <option key={d.id} value={d.id}>{d.full_name ?? d.username}{d.city ? ` — ${d.city}` : ""}</option>)}
            </Select>
          </Field>
          <Field label="شهر فعالیت" className="sm:col-span-2"><CityPicker value={form.city} onChange={v => setForm(f => ({ ...f, city: v }))} testId="vehicle-city" /></Field>
          <Field label="وضعیت اولیه">
            <Select value={form.vehicle_status} onChange={set("vehicle_status")}>
              {["available", "on_route", "maintenance", "inactive"].map(s => <option key={s} value={s}>{VEHICLE_STATUS[s]}</option>)}
            </Select>
          </Field>
        </form>
      </Modal>
    </>
  );
}
