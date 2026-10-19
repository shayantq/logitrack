/** بخش کاربران (مرحله ۱۵): فرم ساخت/ویرایش، نمایش رمز موقت، وضعیت حساب و عملیات هر کاربر */
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Ban, Check, Copy, Eye, KeyRound, LockOpen, MoreHorizontal, Pencil, Trash2, UserCheck, Wand2 } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { CityPicker } from "@/components/CitySelect";
import { useToast } from "@/components/Toast";
import { useWarehouses } from "@/hooks/data";
import { normalizeDigits } from "@/lib/format";
import { confirmDialog } from "@/ui/dialogs";
import { Menu, MenuItem, MenuSeparator, Modal } from "@/ui/overlays";
import { Badge, Button, Checkbox, Field, Input, Select, type Tone } from "@/ui/primitives";

export type UserRow = Schemas["UserResponse"];
export const ROLE_TONE: Record<string, Tone> = { org_admin: "violet", warehouse_manager: "info", driver: "brand" };

const ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789";
export const randomPassword = () => Array.from(crypto.getRandomValues(new Uint32Array(10)), n => ALPHABET[n % ALPHABET.length]).join("");

export function isLocked(u: Pick<UserRow, "locked_until">) {
  if (!u.locked_until) return false;
  const iso = /[zZ]|[+-]\d\d:\d\d$/.test(u.locked_until) ? u.locked_until : `${u.locked_until}Z`;
  return new Date(iso).getTime() > Date.now();
}

export function AccountBadges({ u }: { u: UserRow }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="account-status" data-active={u.is_active ? "true" : "false"}>
      {u.is_active ? <Badge tone="success" dot>فعال</Badge> : <Badge tone="danger" dot>غیرفعال</Badge>}
      {isLocked(u) && <Badge tone="warning">قفل موقت ورود</Badge>}
      {u.must_change_password && u.is_active && <Badge tone="muted">منتظر تغییر رمز</Badge>}
    </div>
  );
}

/** «۳ ساعت پیش» */
export function timeAgo(value?: string | null): string {
  if (!value) return "هرگز";
  const iso = /[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`;
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  const fa = (n: number) => Math.max(1, Math.floor(n)).toLocaleString("fa-IR");
  if (diff < 60) return "همین الان";
  if (diff < 3600) return `${fa(diff / 60)} دقیقه پیش`;
  if (diff < 86400) return `${fa(diff / 3600)} ساعت پیش`;
  if (diff < 86400 * 30) return `${fa(diff / 86400)} روز پیش`;
  return new Date(iso).toLocaleDateString("fa-IR");
}

/** مرورگر و سیستم‌عامل از روی User-Agent — فقط برای نمایش */
export function deviceLabel(ua?: string | null): string {
  if (!ua) return "—";
  const browser = /Edg\//.test(ua) ? "Edge" : /OPR\//.test(ua) ? "Opera" : /Firefox\//.test(ua) ? "Firefox"
    : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : null;
  const os = /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Windows/.test(ua) ? "Windows"
    : /Mac OS/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : null;
  if (!browser && !os) return "برنامه دیگر";
  return [browser, os].filter(Boolean).join(" روی ");
}

// ---------------------------------------------------------------- فرم ساخت / ویرایش
type FormState = { username: string; email: string; password: string; full_name: string; mobile: string; role: string; city: string; warehouse_id: string; must_change: boolean };
const EMPTY: FormState = { username: "", email: "", password: "", full_name: "", mobile: "", role: "driver", city: "", warehouse_id: "", must_change: true };

export function UserFormModal({ open, onClose, user }: { open: boolean; onClose: () => void; user?: UserRow | null }) {
  const me = useMe();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data: warehouses = [] } = useWarehouses();
  const editing = !!user;
  const [form, setForm] = useState<FormState>(EMPTY);
  const [showPassword, setShowPassword] = useState(false);
  useEffect(() => {
    if (!open) return;
    setShowPassword(false);
    setForm(user ? {
      ...EMPTY, username: user.username, email: user.email ?? "", full_name: user.full_name ?? "", mobile: user.mobile ?? "",
      role: user.role, city: user.city ?? "", warehouse_id: user.warehouse_id ? String(user.warehouse_id) : "",
    } : EMPTY);
  }, [open, user]);
  const set = (k: keyof FormState) => (e: { target: { value: string } }) => setForm(f => ({ ...f, [k]: e.target.value }));
  const done = (message: string) => {
    toast.success(message);
    queryClient.invalidateQueries({ queryKey: ["users"] });
    queryClient.invalidateQueries({ queryKey: ["user"] });
    onClose();
  };
  const mobile = normalizeDigits(form.mobile);
  const save = useMutation({
    mutationFn: () => editing
      ? unwrap(api.PUT("/users/{user_id}", { params: { path: { user_id: user!.id } }, body: {
        full_name: form.full_name, email: form.email, mobile,
        ...(user!.role !== "driver" && user!.id !== me.id ? { role: form.role as "org_admin" | "warehouse_manager" } : {}),
        ...(form.role === "warehouse_manager" && form.warehouse_id ? { warehouse_id: Number(form.warehouse_id) } : {}),
        ...(form.role === "driver" ? { city: form.city || null } : {}),
      } }))
      : unwrap(api.POST("/auth/", { body: {
        username: form.username, email: form.email, password: form.password, full_name: form.full_name || null, mobile: mobile || null,
        role: form.role as Schemas["CreateUserRequest"]["role"], must_change_password: form.must_change,
        city: form.role === "driver" ? form.city || null : null,
        warehouse_id: form.role === "warehouse_manager" && form.warehouse_id ? Number(form.warehouse_id) : null,
      } })),
    onSuccess: () => done(editing ? "تغییرات ذخیره شد." : "کاربر ساخته شد."),
    onError: e => toast.error(errorMessage(e)),
  });
  const roleLocked = editing && (user!.role === "driver" || user!.id === me.id);

  return (
    <Modal open={open} onClose={onClose} title={editing ? `ویرایش «${user!.full_name || user!.username}»` : "کاربر جدید"} testId="user-form-modal"
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="user-form" loading={save.isPending} data-testid="user-form-submit">{editing ? "ذخیره" : "ساخت کاربر"}</Button></>}>
      <form id="user-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        <Field label="نقش" className="sm:col-span-2"
          hint={roleLocked ? (user!.role === "driver" ? "حساب راننده به نقش دیگری تبدیل نمی‌شود." : "نقش خودتان را نمی‌توانید عوض کنید.") : undefined}>
          <Select value={form.role} onChange={set("role")} disabled={roleLocked} data-testid="user-role">
            {(!editing || user!.role === "driver") && <option value="driver">راننده</option>}
            <option value="warehouse_manager">مدیر انبار</option><option value="org_admin">ادمین سازمان</option>
          </Select>
        </Field>
        <Field label="نام و نام خانوادگی" className="sm:col-span-2"><Input value={form.full_name} onChange={set("full_name")} data-testid="user-fullname" /></Field>
        <Field label="نام کاربری *" hint={editing ? "شناسه ورود است و عوض نمی‌شود." : undefined}>
          <Input className="ltr" required minLength={3} maxLength={20} value={form.username} onChange={set("username")} disabled={editing} data-testid="user-username" />
        </Field>
        <Field label="موبایل"><Input className="ltr" inputMode="numeric" maxLength={11} placeholder="09xxxxxxxxx"
          value={form.mobile} onChange={set("mobile")} data-testid="user-mobile" /></Field>
        <Field label="ایمیل *" className="sm:col-span-2"><Input type="email" className="ltr" required value={form.email} onChange={set("email")} data-testid="user-email" /></Field>
        {!editing && (
          <>
            <Field label="رمز عبور اولیه *" hint="حداقل ۶ کاراکتر" className="sm:col-span-2">
              <div className="flex gap-2">
                <Input type={showPassword ? "text" : "password"} className="ltr font-mono" required minLength={6} value={form.password} onChange={set("password")} data-testid="user-password" />
                <Button type="button" variant="secondary" icon={<Wand2 className="size-4" />} onClick={() => { setForm(f => ({ ...f, password: randomPassword() })); setShowPassword(true); }}
                  data-testid="user-generate-password">ساخت رمز</Button>
              </div>
            </Field>
            <div className="sm:col-span-2">
              <Checkbox label="کاربر در اولین ورود رمزش را عوض کند (پیشنهادی)" checked={form.must_change}
                onChange={e => setForm(f => ({ ...f, must_change: e.target.checked }))} data-testid="user-must-change" />
            </div>
          </>
        )}
        {form.role === "driver" && <Field label="شهر محل فعالیت" className="sm:col-span-2"><CityPicker value={form.city} onChange={v => setForm(f => ({ ...f, city: v }))} testId="user-city" /></Field>}
        {form.role === "warehouse_manager" && (
          <Field label="انبار تحت مدیریت *" className="sm:col-span-2">
            <Select value={form.warehouse_id} onChange={set("warehouse_id")} required data-testid="user-warehouse">
              <option value="">—</option>{warehouses.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          </Field>
        )}
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------- رمز موقت (یک‌بار نمایش)
export function TempPasswordModal({ data, onClose }: { data: { name: string; username: string; password: string } | null; onClose: () => void }) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  useEffect(() => setCopied(false), [data]);
  const copy = async () => {
    if (!data) return;
    try { await navigator.clipboard.writeText(`نام کاربری: ${data.username}\nرمز موقت: ${data.password}`); setCopied(true); }
    catch { toast.error("کپی نشد؛ رمز را دستی یادداشت کنید."); }
  };
  return (
    <Modal open={!!data} onClose={onClose} title="رمز موقت ساخته شد" testId="temp-password-modal"
      description="این رمز فقط همین یک بار نمایش داده می‌شود. آن را به کاربر بدهید؛ در اولین ورود باید رمز خودش را انتخاب کند."
      footer={<Button onClick={onClose}>بستم، تحویل دادم</Button>}>
      {data && (
        <div className="space-y-3">
          <div className="text-sm text-muted">{data.name} — <span className="font-mono ltr">{data.username}</span></div>
          <div className="flex items-center gap-2 rounded-xl border border-dashed border-brand/50 bg-brand-soft/50 p-4">
            <span className="flex-1 select-all text-center font-mono text-2xl font-bold tracking-widest ltr" data-testid="temp-password">{data.password}</span>
            <Button variant="secondary" size="sm" icon={copied ? <Check className="size-4" /> : <Copy className="size-4" />} onClick={copy}>{copied ? "کپی شد" : "کپی"}</Button>
          </div>
          <p className="text-xs text-muted">همه نشست‌های قبلی این کاربر بسته شد.</p>
        </div>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------- عملیات هر کاربر
export function useUserActions() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<UserRow | null>(null);
  const [temp, setTemp] = useState<{ name: string; username: string; password: string } | null>(null);
  const refresh = () => { queryClient.invalidateQueries({ queryKey: ["users"] }); queryClient.invalidateQueries({ queryKey: ["user"] }); };
  const fail = (e: unknown) => toast.error(errorMessage(e));
  const path = (u: UserRow) => ({ params: { path: { user_id: u.id } } });
  const name = (u: UserRow) => u.full_name || u.username;

  const deactivate = useMutation({ mutationFn: (u: UserRow) => unwrap(api.POST("/users/{user_id}/deactivate", path(u))),
    onSuccess: u => { toast.success(`حساب «${name(u)}» غیرفعال شد.`); refresh(); }, onError: fail });
  const activate = useMutation({ mutationFn: (u: UserRow) => unwrap(api.POST("/users/{user_id}/activate", path(u))),
    onSuccess: u => { toast.success(`حساب «${name(u)}» فعال شد.`); refresh(); }, onError: fail });
  const unlock = useMutation({ mutationFn: (u: UserRow) => unwrap(api.POST("/users/{user_id}/unlock", path(u))),
    onSuccess: u => { toast.success(`قفل ورود «${name(u)}» برداشته شد.`); refresh(); }, onError: fail });
  const reset = useMutation({ mutationFn: (u: UserRow) => unwrap(api.POST("/users/{user_id}/reset-password", path(u))),
    onSuccess: r => { setTemp({ name: name(r.user), username: r.user.username, password: r.temporary_password }); refresh(); }, onError: fail });
  const remove = useMutation({ mutationFn: (u: UserRow) => unwrap(api.DELETE("/users/{user_id}", path(u))).then(() => u),
    onSuccess: u => { toast.success(`کاربر «${name(u)}» حذف شد.`); refresh(); }, onError: fail });

  const ask = {
    deactivate: (u: UserRow) => confirmDialog({ title: `حساب «${name(u)}» غیرفعال شود؟`, confirmLabel: "غیرفعال‌سازی", danger: true,
      text: "کاربر فوراً از همه دستگاه‌ها خارج می‌شود و دیگر نمی‌تواند وارد شود. سوابقش سر جایش می‌ماند و هر وقت بخواهید دوباره فعالش می‌کنید." })
      .then(ok => ok && deactivate.mutate(u)),
    reset: (u: UserRow) => confirmDialog({ title: `رمز «${name(u)}» بازنشانی شود؟`, confirmLabel: "ساخت رمز موقت",
      text: "یک رمز موقت ساخته می‌شود، رمز فعلی دیگر کار نمی‌کند و کاربر از همه دستگاه‌ها خارج می‌شود." })
      .then(ok => ok && reset.mutate(u)),
    remove: (u: UserRow) => confirmDialog({ title: `کاربر «${name(u)}» حذف شود؟`, confirmLabel: "حذف کاربر", danger: true,
      text: "فقط کاربری که هیچ سابقه کاری ندارد حذف می‌شود؛ برای بقیه «غیرفعال‌سازی» را بزنید." })
      .then(ok => ok && remove.mutate(u)),
  };
  const busy = deactivate.isPending || activate.isPending || unlock.isPending || reset.isPending || remove.isPending;

  const modals: ReactNode = (
    <>
      <UserFormModal open={!!editing} onClose={() => setEditing(null)} user={editing} />
      <TempPasswordModal data={temp} onClose={() => setTemp(null)} />
    </>
  );
  return { edit: setEditing, ask, activate: activate.mutate, unlock: unlock.mutate, busy, modals };
}

export function UserActionsMenu({ u, actions, showDetail = true }: { u: UserRow; actions: ReturnType<typeof useUserActions>; showDetail?: boolean }) {
  const me = useMe();
  const navigate = useNavigate();
  const self = u.id === me.id;
  return (
    <Menu trigger={
      <Button variant="ghost" size="icon" aria-label={`عملیات ${u.full_name || u.username}`} data-testid="user-actions"><MoreHorizontal className="size-4" /></Button>
    }>
      {showDetail && <MenuItem onSelect={() => navigate(`/app/users/${u.id}`)} icon={<Eye className="size-4" />}>جزئیات و فعالیت</MenuItem>}
      <MenuItem onSelect={() => actions.edit(u)} icon={<Pencil className="size-4" />}><span data-testid="action-edit">ویرایش</span></MenuItem>
      {!self && <MenuItem onSelect={() => actions.ask.reset(u)} icon={<KeyRound className="size-4" />}><span data-testid="action-reset">بازنشانی رمز</span></MenuItem>}
      {isLocked(u) && <MenuItem onSelect={() => actions.unlock(u)} icon={<LockOpen className="size-4" />}><span data-testid="action-unlock">برداشتن قفل ورود</span></MenuItem>}
      {!self && (u.is_active
        ? <MenuItem onSelect={() => actions.ask.deactivate(u)} icon={<Ban className="size-4" />}><span data-testid="action-deactivate">غیرفعال‌سازی</span></MenuItem>
        : <MenuItem onSelect={() => actions.activate(u)} icon={<UserCheck className="size-4" />}><span data-testid="action-activate">فعال‌سازی دوباره</span></MenuItem>)}
      {!self && <MenuSeparator />}
      {!self && <MenuItem danger onSelect={() => actions.ask.remove(u)} icon={<Trash2 className="size-4" />}><span data-testid="action-delete">حذف</span></MenuItem>}
    </Menu>
  );
}

