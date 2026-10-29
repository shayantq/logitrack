import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building, Plus, Power, Users, IdCard } from "lucide-react";
import { api, authFetch, errorMessage, unwrap } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { BUSINESS_TYPES, ROLE_LABELS, type Role } from "@/lib/labels";
import { faDate, faNumber } from "@/lib/format";
import { Modal } from "@/ui/overlays";
import { StarInput, Stars } from "@/components/performance/PerformanceUI";
import { ActionCenter } from "@/components/ActionCenter";
import { Badge, Button, Card, DataList, ErrorState, Field, Input, PageHeader, Spinner, StatCard, Table, TableSkeleton } from "@/ui/primitives";
import { confirmDialog } from "@/ui/dialogs";

function ProfileModal({ orgId, onClose }: { orgId: number | null; onClose: () => void }) {
  const { data: p } = useQuery({
    queryKey: ["platform-profile", orgId],
    queryFn: () => unwrap(api.GET("/platform/organizations/{organization_id}/profile", { params: { path: { organization_id: orgId! } } })),
    enabled: orgId !== null,
  });
  const { data: logo } = useQuery({
    queryKey: ["platform-logo", orgId, p?.updated_at],
    queryFn: async () => { const r = await authFetch(`/platform/organizations/${orgId}/logo`); return r.ok ? URL.createObjectURL(await r.blob()) : null; },
    enabled: !!p?.has_logo,
  });
  return (
    <Modal open={orgId !== null} onClose={onClose} size="lg"
      title={<span className="flex items-center gap-3">{logo && <img src={logo} alt="" className="size-9 rounded-lg bg-white object-contain p-0.5" />}{p?.name ?? "پروفایل سازمان"}</span>}>
      {!p ? <div className="grid place-items-center py-10"><Spinner /></div> : (
        <DataList columns={3} items={[
          ["نام ثبتی", p.legal_name], ["حوزه فعالیت", BUSINESS_TYPES[p.business_type ?? ""] ?? p.business_type], ["شناسه ملی", p.national_id],
          ["کد اقتصادی", p.economic_code], ["استان / شهر", [p.province, p.city].filter(Boolean).join(" / ")], ["کد پستی", p.postal_code],
          ["نشانی", p.address], ["تلفن", p.phone], ["وب‌سایت", p.website], ["کارکنان", p.employee_count], ["سفارش ماهانه", p.monthly_order_volume],
          ["انبارها", p.warehouse_count], ["راننده/خودرو", p.fleet_size], ["مسئول", p.contact_name], ["همراه", p.contact_mobile], ["ایمیل", p.contact_email],
        ]} />
      )}
    </Modal>
  );
}

function UsersModal({ org, onClose }: { org: { id: number; name: string } | null; onClose: () => void }) {
  const { data: users } = useQuery({
    queryKey: ["platform-users", org?.id],
    queryFn: () => unwrap(api.GET("/platform/organizations/{organization_id}/users", { params: { path: { organization_id: org!.id } } })),
    enabled: !!org,
  });
  return (
    <Modal open={!!org} onClose={onClose} size="lg" title={`کاربران «${org?.name ?? ""}»`}>
      {!users ? <div className="grid place-items-center py-10"><Spinner /></div> : (
        <div className="overflow-hidden rounded-xl border border-border">
          <table className="table-base">
            <thead><tr><th>نام</th><th>نام کاربری</th><th>نقش</th><th>کد راننده</th><th>شهر</th></tr></thead>
            <tbody>{users.map(u => (
              <tr key={u.id}><td>{u.full_name ?? "—"}</td><td className="font-mono text-xs ltr">{u.username}</td>
                <td><Badge tone="violet">{ROLE_LABELS[u.role as Role] ?? u.role}</Badge></td><td className="font-mono text-xs">{u.driver_code ?? "—"}</td><td>{u.city ?? "—"}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {org && <PlatformDriverRatings orgId={org.id} />}
    </Modal>
  );
}

const EMPTY = { name: "", slug: "", full_name: "", username: "", email: "", password: "" };

export default function OrganizationsPage() {
  const me = useMe();
  const toast = useToast();
  const queryClient = useQueryClient();
  const isAdmin = me.role === "platform_admin";
  const { data: orgs, isLoading, error, refetch } = useQuery({ queryKey: ["platform-orgs"], queryFn: () => unwrap(api.GET("/platform/organizations")) });
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [profileId, setProfileId] = useState<number | null>(null);
  const [usersOf, setUsersOf] = useState<{ id: number; name: string } | null>(null);
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm(f => ({ ...f, [k]: e.target.value }));

  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/platform/organizations", { body: {
      name: form.name, slug: form.slug, admin: { username: form.username, email: form.email, password: form.password, full_name: form.full_name || null },
    } })),
    onSuccess: () => { toast.success("سازمان و ادمین آن ساخته شدند."); setCreateOpen(false); setForm(EMPTY); queryClient.invalidateQueries({ queryKey: ["platform-orgs"] }); },
    onError: e => toast.error(errorMessage(e)),
  });
  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) =>
      unwrap(api.PATCH("/platform/organizations/{organization_id}", { params: { path: { organization_id: id } }, body: { is_active: active } })),
    onSuccess: o => { toast.success(o.is_active ? "سازمان فعال شد." : "سازمان غیرفعال شد."); queryClient.invalidateQueries({ queryKey: ["platform-orgs"] }); },
    onError: e => toast.error(errorMessage(e)),
  });
  const list = orgs ?? [];

  return (
    <>
      <PageHeader eyebrow="پلتفرم" title="سازمان‌ها" subtitle={isAdmin ? "ساخت و مدیریت سازمان‌هایی که از سامانه استفاده می‌کنند" : "پشتیبان پلتفرم — فقط مشاهده"}
        actions={isAdmin && <Button icon={<Plus className="size-4" />} onClick={() => setCreateOpen(true)}>سازمان جدید</Button>} />
      <ActionCenter />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="سازمان‌ها" value={faNumber(list.length)} icon={<Building className="size-[18px]" />} />
        <StatCard label="فعال" value={faNumber(list.filter(o => o.is_active).length)} tone="success" />
        <StatCard label="کل کاربران" value={faNumber(list.reduce((s, o) => s + (o.users_count ?? 0), 0))} tone="violet" />
        <StatCard label="سفارش‌های فعال" value={faNumber(list.reduce((s, o) => s + (o.active_orders_count ?? 0), 0))} tone="orange" />
      </div>
      <Card>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
          <Table testId="orgs-table">
            <thead><tr><th>سازمان</th><th>وضعیت</th><th>کاربران</th><th>رانندگان</th><th>کالاها</th><th>خودروها</th><th>سفارش (فعال)</th><th>ایجاد</th><th /></tr></thead>
            <tbody>
              {list.map(o => (
                <tr key={o.id}>
                  <td><div className="font-medium">{o.name}</div><div className="font-mono text-xs text-muted ltr">{o.slug}</div></td>
                  <td>{o.is_active ? <Badge tone="success" dot>فعال</Badge> : <Badge tone="danger" dot>غیرفعال</Badge>}</td>
                  <td className="tnum">{faNumber(o.users_count)}</td><td className="tnum">{faNumber(o.drivers_count)}</td>
                  <td className="tnum">{faNumber(o.products_count)}</td><td className="tnum">{faNumber(o.vehicles_count)}</td>
                  <td className="tnum">{faNumber(o.orders_count)} <span className="text-muted">({faNumber(o.active_orders_count)})</span></td>
                  <td className="text-xs text-text-2">{faDate(o.created_at)}</td>
                  <td>
                    <div className="flex gap-1">
                      <Button size="sm" variant="ghost" icon={<IdCard className="size-4" />} onClick={() => setProfileId(o.id)}>پروفایل</Button>
                      <Button size="sm" variant="ghost" icon={<Users className="size-4" />} onClick={() => setUsersOf({ id: o.id, name: o.name })}>کاربران</Button>
                      {isAdmin && <Button size="sm" variant={o.is_active ? "outline-danger" : "soft"} icon={<Power className="size-4" />}
                        onClick={() => confirmDialog({ title: o.is_active ? `«${o.name}» غیرفعال شود؟ همه کاربرانش قفل می‌شوند.` : `«${o.name}» فعال شود؟`, danger: o.is_active, confirmLabel: o.is_active ? "غیرفعال شود" : "فعال شود" }).then(ok => ok && toggle.mutate({ id: o.id, active: !o.is_active }))}>
                        {o.is_active ? "غیرفعال" : "فعال"}</Button>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="ساخت سازمان جدید"
        footer={<><Button variant="secondary" onClick={() => setCreateOpen(false)}>انصراف</Button><Button type="submit" form="org-form" loading={create.isPending}>ساخت سازمان</Button></>}>
        <form id="org-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
          <Field label="نام سازمان *"><Input required minLength={2} value={form.name} onChange={set("name")} /></Field>
          <Field label="شناسه انگلیسی (slug) *" hint="حروف انگلیسی، عدد و خط تیره"><Input className="ltr" required pattern="[A-Za-z0-9][A-Za-z0-9-]*" value={form.slug} onChange={set("slug")} /></Field>
          <div className="eyebrow sm:col-span-2">اولین ادمین سازمان</div>
          <Field label="نام و نام خانوادگی" className="sm:col-span-2"><Input value={form.full_name} onChange={set("full_name")} /></Field>
          <Field label="نام کاربری *"><Input className="ltr" required minLength={3} maxLength={20} value={form.username} onChange={set("username")} /></Field>
          <Field label="رمز عبور *"><Input type="password" className="ltr" required minLength={6} value={form.password} onChange={set("password")} /></Field>
          <Field label="ایمیل *" className="sm:col-span-2"><Input type="email" className="ltr" required value={form.email} onChange={set("email")} /></Field>
        </form>
      </Modal>
      <ProfileModal orgId={profileId} onClose={() => setProfileId(null)} />
      <UsersModal org={usersOf} onClose={() => setUsersOf(null)} />
    </>
  );
}

/** ارزیابی کیفی پلتفرم از رانندگان هر سازمان (۱۵٪ وزن در امتیاز کل راننده) */
function PlatformDriverRatings({ orgId }: { orgId: number }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [active, setActive] = useState<number | null>(null);
  const [score, setScore] = useState(0);
  const [comment, setComment] = useState("");
  const { data: drivers = [] } = useQuery({
    queryKey: ["platform-drivers", orgId],
    queryFn: () => unwrap(api.GET("/platform/organizations/{organization_id}/drivers", { params: { path: { organization_id: orgId } } })) as Promise<
      { driver_id: number; driver_name: string; driver_code: string | null; driver_status: string; rating: number | null; deliveries: number }[]>,
  });
  const rate = useMutation({
    mutationFn: () => unwrap(api.POST("/platform/organizations/{organization_id}/drivers/{driver_id}/ratings", {
      params: { path: { organization_id: orgId, driver_id: active! } }, body: { score, comment: comment || null } })),
    onSuccess: () => { toast.success("ارزیابی پلتفرم ثبت شد."); setActive(null); setScore(0); setComment("");
      queryClient.invalidateQueries({ queryKey: ["platform-drivers", orgId] }); },
    onError: e => toast.error(errorMessage(e)),
  });
  if (drivers.length === 0) return null;
  return (
    <div className="mt-5" data-testid="platform-driver-ratings">
      <h4 className="mb-2 text-sm font-bold">ارزیابی پلتفرم از رانندگان</h4>
      <ul className="divide-y divide-border rounded-xl border border-border">
        {drivers.map(d => (
          <li key={d.driver_id} className="px-4 py-2.5">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className="font-medium">{d.driver_name}</span><span className="font-mono text-xs text-muted">{d.driver_code}</span>
              <span className="text-xs text-muted">{d.deliveries.toLocaleString("fa-IR")} تحویل</span>
              <Stars value={d.rating} />
              <Button size="sm" variant="ghost" className="ms-auto" onClick={() => { setActive(active === d.driver_id ? null : d.driver_id); setScore(0); }}
                data-testid="platform-rate-open">ارزیابی</Button>
            </div>
            {active === d.driver_id && (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <StarInput value={score} onChange={setScore} />
                <Input className="min-w-48 flex-1" placeholder="توضیح (مثلاً گزارش کیفیت)" value={comment} onChange={e => setComment(e.target.value)} />
                <Button size="sm" disabled={!score} loading={rate.isPending} onClick={() => rate.mutate()} data-testid="platform-rate-save">ثبت</Button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
