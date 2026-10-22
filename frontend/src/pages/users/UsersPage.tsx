import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { History, Search, UserPlus, Users } from "lucide-react";
import { useMe } from "@/auth/AuthContext";
import { useUsers, useWarehouses } from "@/hooks/data";
import { ROLE_LABELS, type Role } from "@/lib/labels";
import { DRIVER_STATUS, type DriverStatus } from "@/lib/driver";
import { latinDigits } from "@/lib/format";
import { Badge, Button, Card, EmptyState, ErrorState, Input, PageHeader, SegmentedControl, Select, Table, TableSkeleton } from "@/ui/primitives";
import { AccountBadges, ROLE_TONE, UserActionsMenu, UserFormModal, isLocked, timeAgo, useUserActions } from "./shared";

type StatusFilter = "all" | "active" | "inactive" | "locked";
/** جستجو بی‌توجه به ی/ک عربی، ارقام فارسی و حروف بزرگ */
const normalizePersian = (v: string) => latinDigits(v).replace(/ي/g, "ی").replace(/ك/g, "ک").toLowerCase();

export default function UsersPage() {
  const me = useMe();
  const { data: users, isLoading, error, refetch } = useUsers();
  const { data: warehouses = [] } = useWarehouses();
  const actions = useUserActions();
  const [creating, setCreating] = useState(false);
  const [roleFilter, setRoleFilter] = useState<"all" | Role>("all");
  const [status, setStatus] = useState<StatusFilter>("active");
  const [q, setQ] = useState("");
  const warehouseName = (id?: number | null) => warehouses.find(w => w.id === id)?.name ?? "—";

  const counts = useMemo(() => ({
    active: (users ?? []).filter(u => u.is_active).length,
    inactive: (users ?? []).filter(u => !u.is_active).length,
    locked: (users ?? []).filter(isLocked).length,
  }), [users]);
  const visible = useMemo(() => {
    const term = normalizePersian(q.trim());
    return (users ?? []).filter(u =>
      (roleFilter === "all" || u.role === roleFilter)
      && (status === "all" || (status === "active" ? u.is_active : status === "inactive" ? !u.is_active : isLocked(u)))
      && (!term || [u.full_name, u.username, u.email, u.mobile, u.driver_code].some(v => v && normalizePersian(v).includes(term))));
  }, [users, roleFilter, status, q]);

  return (
    <>
      <PageHeader eyebrow="تیم" title="کاربران و رانندگان" subtitle="حساب کارکنان سازمان، نقش و دسترسی هر نفر، وضعیت حساب و آخرین ورود"
        actions={<>
          <Link to="/app/activity" className="tap-target inline-flex items-center gap-1.5 text-sm font-medium text-brand hover:underline"><History className="size-4" />گزارش فعالیت</Link>
          <Button icon={<UserPlus className="size-4" />} onClick={() => setCreating(true)} data-testid="user-new">کاربر جدید</Button>
        </>} />
      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-border p-4">
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" />
            <Input className="pr-9" placeholder="جستجوی نام، نام کاربری، موبایل…" value={q} onChange={e => setQ(e.target.value)} data-testid="users-search" aria-label="جستجو" />
          </div>
          <SegmentedControl value={roleFilter} onChange={setRoleFilter} options={[
            { value: "all", label: "همه" }, { value: "driver", label: "رانندگان" },
            { value: "warehouse_manager", label: "مدیران انبار" }, { value: "org_admin", label: "ادمین‌ها" },
          ]} />
          <Select value={status} onChange={e => setStatus(e.target.value as StatusFilter)} className="w-48" aria-label="وضعیت حساب" data-testid="users-status">
            <option value="active">فعال ({counts.active.toLocaleString("fa-IR")})</option>
            <option value="inactive">غیرفعال ({counts.inactive.toLocaleString("fa-IR")})</option>
            <option value="locked">قفل موقت ({counts.locked.toLocaleString("fa-IR")})</option>
            <option value="all">همه حساب‌ها</option>
          </Select>
        </div>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : visible.length === 0 ? (
          <EmptyState icon={<Users className="size-5" />} title="کاربری با این فیلترها نیست" />
        ) : (
          <Table testId="users-table">
            <thead><tr><th>کاربر</th><th>نقش</th><th>وضعیت حساب</th><th>شهر / انبار</th><th>آخرین ورود</th><th className="w-1" /></tr></thead>
            <tbody>
              {visible.map(u => (
                <tr key={u.id} data-testid="user-row" data-username={u.username} className={u.is_active ? undefined : "opacity-70"}>
                  <td>
                    <Link to={`/app/users/${u.id}`} className="font-medium hover:text-brand" data-testid="user-open">{u.full_name || u.username}</Link>
                    {u.id === me.id && <Badge className="ms-1.5">شما</Badge>}
                    <div className="font-mono text-xs text-muted ltr text-end">{u.username}{u.driver_code ? ` · ${u.driver_code}` : ""}</div>
                  </td>
                  <td>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge tone={ROLE_TONE[u.role] ?? "muted"}>{ROLE_LABELS[u.role as Role] ?? u.role}</Badge>
                      {u.role === "driver" && u.driver_status && u.driver_status !== "approved" && (
                        <Badge tone={DRIVER_STATUS[u.driver_status as DriverStatus]?.tone ?? "muted"} dot>{DRIVER_STATUS[u.driver_status as DriverStatus]?.label}</Badge>
                      )}
                    </div>
                  </td>
                  <td><AccountBadges u={u} /></td>
                  <td className="text-text-2">{u.role === "warehouse_manager" ? warehouseName(u.warehouse_id) : u.city ?? "—"}</td>
                  <td className="whitespace-nowrap text-xs text-text-2" data-testid="user-last-login">{timeAgo(u.last_login_at)}</td>
                  <td><UserActionsMenu u={u} actions={actions} /></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <UserFormModal open={creating} onClose={() => setCreating(false)} />
      {actions.modals}
    </>
  );
}
