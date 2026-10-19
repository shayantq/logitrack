/** برنامه کاری رانندگان: شیفت هفتگی، بار هر روز، سقف روزانه، بار بین‌شهری و مرخصی (مرحله ۷) */
import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, CalendarOff, Plus, Trash2, Truck } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { JalaliDateInput, PlateView, thisJalaliYear } from "@/components/driver/DriverInputs";
import { useToast } from "@/components/Toast";
import { DRIVER_STATUS, type DriverStatus } from "@/lib/driver";
import { faDate, faNumber } from "@/lib/format";
import { EMPLOYMENT, PRESETS, WEEK, hhmm, iranDayStart, isoDate, nextDays, pyWeekday, type ShiftDraft } from "@/lib/schedule";
import { Modal } from "@/ui/overlays";
import {
  Badge, Button, Card, Checkbox, EmptyState, ErrorState, Field, Input, PageHeader, SegmentedControl, StatCard, Table, TableSkeleton, cn,
} from "@/ui/primitives";
import { TimeField } from "@/ui/datetime";

type Row = Schemas["DriverScheduleResponse"];

export default function SchedulesPage() {
  const me = useMe();
  const isAdmin = me.role === "org_admin";
  const days = nextDays(7);
  const [day, setDay] = useState(isoDate(days[0]));
  const [editing, setEditing] = useState<Row | null>(null);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["schedules", day],
    queryFn: () => unwrap(api.GET("/dispatch/schedules", { params: { query: { day } } })),
    placeholderData: keepPreviousData,
  });
  const rows = data ?? [];
  const onShift = rows.filter(r => r.day.shifts.length > 0 && !r.day.off).length;

  return (
    <>
      <PageHeader eyebrow="عملیات" title="برنامه رانندگان"
        subtitle="شیفت‌ها، مرخصی و ظرفیت هر راننده — پیشنهاد راننده برای سفارش‌ها از روی همین برنامه انجام می‌شود." />

      <div className="mb-5 flex gap-2 overflow-x-auto pb-1" data-testid="schedule-days">
        {days.map((d, i) => {
          const iso = isoDate(d);
          return (
            <button key={iso} type="button" onClick={() => setDay(iso)} data-testid="schedule-day" data-day={iso}
              className={cn("min-w-24 shrink-0 rounded-2xl border px-4 py-2.5 text-center transition",
                iso === day ? "border-brand bg-brand text-brand-ink shadow-[var(--shadow)]" : "border-border bg-surface hover:border-border-strong")}>
              <div className="text-sm font-bold">{i === 0 ? "امروز" : i === 1 ? "فردا" : WEEK.find(w => w.weekday === pyWeekday(d))?.name}</div>
              <div className={cn("text-xs", iso === day ? "opacity-85" : "text-muted")}>{faDate(iso)}</div>
            </button>
          );
        })}
      </div>

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="در شیفت" value={faNumber(onShift)} icon={<CalendarClock className="size-[18px]" />} hint={`از ${faNumber(rows.length)} راننده`} />
        <StatCard label="مرخصی" value={faNumber(rows.filter(r => r.day.off).length)} tone="warning" icon={<CalendarOff className="size-[18px]" />} />
        <StatCard label="سفارش‌های این روز" value={faNumber(rows.reduce((s, r) => s + r.day.orders, 0))} tone="info" />
        <StatCard label="بار این روز" value={`${faNumber(Math.round(rows.reduce((s, r) => s + r.day.load_kg, 0)))} کیلو`} tone="violet" icon={<Truck className="size-[18px]" />} />
      </div>

      <Card>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : rows.length === 0 ? (
          <EmptyState icon={<CalendarClock className="size-5" />} title="هنوز راننده‌ای ندارید" />
        ) : (
          <Table testId="schedules-table">
            <thead><tr><th>راننده</th><th>خودرو</th><th>هفته</th><th>این روز</th><th>بار این روز</th><th>شرایط</th></tr></thead>
            <tbody>
              {rows.map(r => {
                const cap = r.vehicle?.capacity_kg ?? 0;
                const status = DRIVER_STATUS[r.driver_status as DriverStatus];
                return (
                  <tr key={r.driver_id} className={cn(isAdmin && "clickable")} onClick={isAdmin ? () => setEditing(r) : undefined}>
                    <td>
                      <div className="font-medium">{r.driver_name}</div>
                      <div className="flex items-center gap-1.5 text-xs text-muted"><span className="font-mono">{r.driver_code}</span>{r.city && `· ${r.city}`}</div>
                      {r.driver_status !== "approved" && <Badge tone={status?.tone ?? "muted"} className="mt-1">{status?.label}</Badge>}
                    </td>
                    <td>{r.vehicle ? <><div className="text-sm">{r.vehicle.model}</div><PlateView plate={r.vehicle.license_plate} className="h-7 origin-right scale-90" /></> : <span className="text-muted">—</span>}</td>
                    <td>
                      <div className="flex gap-1" dir="rtl" aria-label="روزهای کاری">
                        {WEEK.map(w => {
                          const has = r.shifts.some(s => s.weekday === w.weekday);
                          return <span key={w.weekday} title={w.name}
                            className={cn("grid size-6 place-items-center rounded-md text-[10px] font-bold", has ? "bg-brand-soft text-brand-strong" : "bg-surface-2 text-muted/60",
                              w.weekday === pyWeekday(new Date(`${day}T00:00:00`)) && "ring-2 ring-brand/50")}>{w.short}</span>;
                        })}
                      </div>
                      <div className="mt-1 text-[11px] text-muted">{EMPLOYMENT[r.employment_type]}{r.shifts.length === 0 && " · برنامه ثبت نشده"}</div>
                    </td>
                    <td>
                      {r.day.off ? <Badge tone="warning" dot>مرخصی</Badge>
                        : r.day.shifts.length ? <span className="font-mono text-sm ltr">{r.day.shifts.join("، ")}</span>
                        : r.shifts.length ? <span className="text-sm text-muted">خارج از شیفت</span> : <span className="text-sm text-muted">همیشه در دسترس</span>}
                    </td>
                    <td className="min-w-40">
                      <div className="flex justify-between text-xs"><span className="tnum">{faNumber(r.day.orders)}{r.max_daily_orders ? ` / ${faNumber(r.max_daily_orders)}` : ""} سفارش</span>
                        <span className="tnum text-muted">{faNumber(Math.round(r.day.load_kg))} کیلو</span></div>
                      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2">
                        <div className="h-full rounded-full bg-brand" style={{ width: `${cap ? Math.min(100, (r.day.load_kg / cap) * 100) : 0}%` }} />
                      </div>
                    </td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {r.intercity && <Badge tone="info">بین‌شهری</Badge>}
                        {r.time_off.length > 0 && <Badge tone="warning">{faNumber(r.time_off.length)} مرخصی پیش‌رو</Badge>}
                        {r.vehicle && ["maintenance", "inactive"].includes(r.vehicle.status ?? "") && <Badge tone="danger">خودرو {r.vehicle.status === "maintenance" ? "در تعمیر" : "غیرفعال"}</Badge>}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>
      {!isAdmin && <p className="mt-3 text-xs text-muted">تغییر برنامه رانندگان فقط با ادمین سازمان است.</p>}
      {editing && <ScheduleModal row={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function ScheduleModal({ row, onClose }: { row: Row; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [employment, setEmployment] = useState(row.employment_type);
  const [maxDaily, setMaxDaily] = useState(row.max_daily_orders ? String(row.max_daily_orders) : "");
  const [intercity, setIntercity] = useState(row.intercity);
  const [shifts, setShifts] = useState<ShiftDraft[]>(row.shifts.map(s => ({ weekday: s.weekday, start_time: hhmm(s.start_time), end_time: hhmm(s.end_time) })));
  const [off, setOff] = useState<{ from: string | null; to: string | null; reason: string }>({ from: null, to: null, reason: "" });
  const invalidate = () => { queryClient.invalidateQueries({ queryKey: ["schedules"] }); queryClient.invalidateQueries({ queryKey: ["suggest"] }); };

  const save = useMutation({
    mutationFn: () => unwrap(api.PUT("/dispatch/schedules/{driver_id}", { params: { path: { driver_id: row.driver_id } }, body: {
      employment_type: employment, max_daily_orders: maxDaily ? Number(maxDaily) : null, intercity, shifts,
    } })),
    onSuccess: () => { toast.success("برنامه راننده ذخیره شد."); invalidate(); onClose(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const addOff = useMutation({
    mutationFn: () => {
      const end = new Date(`${off.to}T00:00:00`);
      end.setDate(end.getDate() + 1);   // تا پایان روز آخر
      return unwrap(api.POST("/dispatch/schedules/{driver_id}/time-off", { params: { path: { driver_id: row.driver_id } }, body: {
        starts_at: iranDayStart(off.from!), ends_at: iranDayStart(isoDate(end)), reason: off.reason || null,
      } }));
    },
    onSuccess: () => { toast.success("مرخصی ثبت شد."); invalidate(); onClose(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const removeOff = useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE("/dispatch/schedules/{driver_id}/time-off/{time_off_id}", {
      params: { path: { driver_id: row.driver_id, time_off_id: id } } })),
    onSuccess: () => { toast.success("مرخصی حذف شد."); invalidate(); onClose(); },
    onError: e => toast.error(errorMessage(e)),
  });

  const update = (index: number, patch: Partial<ShiftDraft>) => setShifts(list => list.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  const applyPreset = (key: keyof typeof PRESETS) => { setEmployment(key as Row["employment_type"]); setShifts(PRESETS[key].shifts.map(s => ({ ...s }))); };

  return (
    <Modal open onClose={onClose} size="lg" testId="schedule-modal" title={`برنامه ${row.driver_name}`}
      description={row.vehicle ? `${row.vehicle.model ?? ""} · ظرفیت ${faNumber(row.vehicle.capacity_kg)} کیلوگرم` : "خودرویی ثبت نشده"}
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button loading={save.isPending} onClick={() => save.mutate()} data-testid="schedule-save">ذخیره برنامه</Button></>}>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center gap-3">
          <SegmentedControl value={employment} onChange={v => setEmployment(v)} options={[{ value: "full_time", label: "تمام‌وقت" }, { value: "part_time", label: "پاره‌وقت" }]} />
          <span className="text-xs text-muted">الگوی آماده:</span>
          {(Object.keys(PRESETS) as (keyof typeof PRESETS)[]).map(k => (
            <Button key={k} size="sm" variant="ghost" onClick={() => applyPreset(k)} data-testid={`preset-${k}`}>{PRESETS[k].label}</Button>
          ))}
        </div>

        <div className="space-y-2" data-testid="shift-editor">
          {WEEK.map(w => {
            const dayShifts = shifts.map((s, i) => ({ s, i })).filter(x => x.s.weekday === w.weekday);
            return (
              <div key={w.weekday} className="grid grid-cols-[88px_1fr] items-start gap-3 rounded-xl border border-border p-2.5">
                <span className={cn("pt-2 text-sm font-semibold", !dayShifts.length && "text-muted")}>{w.name}</span>
                <div className="flex flex-wrap items-center gap-2">
                  {dayShifts.length === 0 && <span className="py-2 text-sm text-muted">تعطیل</span>}
                  {dayShifts.map(({ s, i }) => (
                    <span key={i} className="flex items-center gap-1.5 rounded-lg bg-surface-2 p-1" dir="ltr">
                      <TimeField value={s.start_time} onChange={v => update(i, { start_time: v })} className="h-8 w-28" aria-label={`شروع ${w.name}`} step={15} />
                      <span className="text-muted">–</span>
                      <TimeField value={s.end_time} onChange={v => update(i, { end_time: v })} className="h-8 w-28" aria-label={`پایان ${w.name}`} step={15} />
                      <button type="button" className="grid size-7 place-items-center rounded-md text-muted hover:bg-danger-soft hover:text-danger" aria-label="حذف بازه"
                        onClick={() => setShifts(list => list.filter((_, j) => j !== i))}><Trash2 className="size-3.5" /></button>
                    </span>
                  ))}
                  <Button size="sm" variant="ghost" icon={<Plus className="size-3.5" />} data-testid={`add-shift-${w.weekday}`}
                    onClick={() => setShifts(list => [...list, { weekday: w.weekday, start_time: dayShifts.length ? "14:00" : "08:00", end_time: dayShifts.length ? "20:00" : "17:00" }])}>
                    {dayShifts.length ? "بازه دیگر" : "افزودن شیفت"}</Button>
                </div>
              </div>
            );
          })}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="سقف سفارش در روز" hint="خالی = بدون سقف"><Input type="number" min={1} max={50} value={maxDaily} onChange={e => setMaxDaily(e.target.value)} data-testid="max-daily" /></Field>
          <div className="flex items-end pb-2"><Checkbox label="بار بین‌شهری می‌برد" checked={intercity} onChange={e => setIntercity(e.target.checked)} data-testid="intercity" /></div>
        </div>

        <div className="rounded-2xl border border-border p-4">
          <h4 className="mb-3 flex items-center gap-2 text-sm font-bold"><CalendarOff className="size-4 text-warning" />مرخصی</h4>
          {row.time_off.length > 0 && (
            <ul className="mb-4 space-y-2">
              {row.time_off.map(t => (
                <li key={t.id} className="flex items-center gap-3 rounded-xl bg-warning-soft px-3 py-2 text-sm">
                  <span className="font-medium">{faDate(t.starts_at)} تا {faDate(new Date(new Date(t.ends_at + "Z").getTime() - 1).toISOString())}</span>
                  <span className="text-text-2">{t.reason}</span>
                  <Button size="icon" variant="ghost" className="ms-auto hover:text-danger" aria-label="حذف مرخصی" onClick={() => removeOff.mutate(t.id)}><Trash2 className="size-4" /></Button>
                </li>
              ))}
            </ul>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="از روز"><JalaliDateInput value={off.from} onChange={v => setOff(o => ({ ...o, from: v }))} fromYear={thisJalaliYear()} toYear={thisJalaliYear() + 1} testId="off-from" /></Field>
            <Field label="تا روز (شامل)"><JalaliDateInput value={off.to} onChange={v => setOff(o => ({ ...o, to: v }))} fromYear={thisJalaliYear()} toYear={thisJalaliYear() + 1} testId="off-to" /></Field>
            <Field label="علت" className="sm:col-span-2"><Input value={off.reason} maxLength={200} onChange={e => setOff(o => ({ ...o, reason: e.target.value }))} placeholder="مثلاً مرخصی استحقاقی" /></Field>
          </div>
          <Button size="sm" variant="soft" className="mt-3" icon={<Plus className="size-4" />} disabled={!off.from || !off.to || off.to < off.from}
            loading={addOff.isPending} onClick={() => addOff.mutate()} data-testid="add-time-off">ثبت مرخصی</Button>
        </div>
      </div>
    </Modal>
  );
}
