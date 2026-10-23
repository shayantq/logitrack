/**
 * طرف‌های تجاری: تأمین‌کنندگان، مشتریان حقوقی/عمده و شرکت‌های حمل — یک طرف می‌تواند چند نقش داشته باشد.
 * شناسه ملی، کد اقتصادی، شبا و کد پستی در سرور اعتبارسنجی می‌شوند؛ مدیر انبار شناسه ملی و شبا را پوشیده می‌بیند.
 */
import { useState, type FormEvent } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, Handshake, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { CitySelect } from "@/components/CitySelect";
import { useToast } from "@/components/Toast";
import { useProvinces } from "@/hooks/data";
import { CARRIER_SERVICES, PARTNER_ROLES } from "@/lib/labels";
import { faNumber, normalizeDigits } from "@/lib/format";
import { confirmDialog } from "@/ui/dialogs";
import { Modal, Tooltip } from "@/ui/overlays";
import { Badge, Button, Card, Checkbox, EmptyState, ErrorState, Field, Input, PageHeader, SegmentedControl, Select, Table, TableSkeleton, Textarea, cn } from "@/ui/primitives";

type Partner = Schemas["PartnerOut"];
type Role = "supplier" | "customer" | "carrier";
type CarrierService = NonNullable<Schemas["PartnerIn"]["carrier_service"]>;

const EMPTY = {
  code: "", name: "", kind: "legal" as "legal" | "individual", is_supplier: true, is_customer: false, is_carrier: false,
  legal_name: "", national_id: "", economic_code: "", registration_number: "", phone: "", mobile: "", email: "", website: "",
  province: "", city: "", address: "", postal_code: "", contact_name: "", contact_mobile: "", iban: "",
  payment_terms_days: "", lead_time_days: "", carrier_service: "" as CarrierService | "", tracking_url: "", notes: "",
};

export default function PartnersPage() {
  const me = useMe();
  const toast = useToast();
  const queryClient = useQueryClient();
  const isAdmin = me.role === "org_admin";
  const [role, setRole] = useState<Role | "all">("all");
  const [q, setQ] = useState("");
  const [inactive, setInactive] = useState(false);
  const [editing, setEditing] = useState<Partner | "new" | null>(null);
  const { data: partners, isLoading, error, refetch } = useQuery({
    queryKey: ["partners", "page", role, q, inactive],
    queryFn: () => unwrap(api.GET("/partners/", { params: { query: { role: role === "all" ? null : role, q: q.trim() || null, include_inactive: inactive } } })),
    placeholderData: keepPreviousData,
  });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["partners"] });
  const toggle = useMutation({
    mutationFn: (p: Partner) => p.is_active
      ? unwrap(api.POST("/partners/{partner_id}/archive", { params: { path: { partner_id: p.id } } }))
      : unwrap(api.POST("/partners/{partner_id}/activate", { params: { path: { partner_id: p.id } } })),
    onSuccess: p => { toast.success(p.is_active ? "طرف تجاری فعال شد." : "طرف تجاری بایگانی شد."); invalidate(); },
    onError: e => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: (id: number) => unwrap(api.DELETE("/partners/{partner_id}", { params: { path: { partner_id: id } } })),
    onSuccess: () => { toast.success("طرف تجاری حذف شد."); invalidate(); },
    onError: e => toast.error(errorMessage(e)),
  });

  return (
    <>
      <PageHeader eyebrow="انبار" title="طرف‌های تجاری" subtitle="تأمین‌کنندگان، مشتریان حقوقی و شرکت‌های حمل — با شناسه‌های اعتبارسنجی‌شده"
        actions={isAdmin && <Button icon={<Plus className="size-4" />} onClick={() => setEditing("new")} data-testid="partner-new">طرف تجاری جدید</Button>} />
      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-border p-4">
          <SegmentedControl value={role} onChange={setRole} options={[
            { value: "all", label: "همه" }, ...Object.entries(PARTNER_ROLES).map(([k, v]) => ({ value: k as Role, label: v.label })),
          ]} />
          <div className="relative min-w-56 flex-1 sm:max-w-xs">
            <Search className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" />
            <Input className="pr-10" placeholder="نام، کد، شناسه یا موبایل" value={q} onChange={e => setQ(e.target.value)} data-testid="partners-search" />
          </div>
          <Checkbox label="نمایش بایگانی‌شده‌ها" checked={inactive} onChange={e => setInactive(e.target.checked)} />
        </div>
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : !partners?.length ? (
          <EmptyState icon={<Handshake className="size-5" />} title={q ? "طرفی با این مشخصات نیست" : "هنوز طرف تجاری ثبت نشده"}
            text="تأمین‌کننده‌ها را تعریف کنید تا در رسید کالا و فهرست تأمین هر کالا انتخاب شوند."
            action={isAdmin && !q && <Button size="sm" onClick={() => setEditing("new")}>تعریف اولین طرف تجاری</Button>} />
        ) : (
          <Table testId="partners-table">
            <thead><tr><th>کد</th><th>نام</th><th>نقش</th><th>تماس</th><th>شهر</th><th>سوابق</th><th className="w-1" /></tr></thead>
            <tbody>
              {partners.map(p => (
                <tr key={p.id} data-testid="partner-row" data-code={p.code} className={cn(!p.is_active && "opacity-60")}>
                  <td className="font-mono text-xs ltr text-start">{p.code}</td>
                  <td>
                    <div className="font-medium">{p.name}{!p.is_active && <Badge className="ms-1.5">بایگانی</Badge>}</div>
                    {p.legal_name && <div className="text-xs text-muted">{p.legal_name}</div>}
                  </td>
                  <td><div className="flex flex-wrap gap-1">{p.roles.map(r => <Badge key={r} tone={PARTNER_ROLES[r]?.tone}>{PARTNER_ROLES[r]?.label ?? r}</Badge>)}</div></td>
                  <td className="text-xs text-text-2">{p.contact_name ?? ""}<div className="ltr text-start tnum">{p.mobile ?? p.phone ?? "—"}</div></td>
                  <td className="text-xs text-text-2">{p.city ?? "—"}</td>
                  <td className="text-xs text-text-2">{faNumber(p.documents_count)} سند · {faNumber(p.products_count)} کالا</td>
                  <td>
                    {isAdmin && (
                      <div className="flex gap-1">
                        <Tooltip content="ویرایش"><Button variant="ghost" size="icon" onClick={() => setEditing(p)} data-testid="partner-edit"><Pencil className="size-4" /></Button></Tooltip>
                        <Tooltip content={p.is_active ? "بایگانی" : "فعال‌سازی"}><Button variant="ghost" size="icon" onClick={() => toggle.mutate(p)}>
                          {p.is_active ? <Archive className="size-4" /> : <ArchiveRestore className="size-4" />}</Button></Tooltip>
                        {p.documents_count + p.products_count === 0 && (
                          <Tooltip content="حذف"><Button variant="ghost" size="icon" className="hover:text-danger"
                            onClick={() => confirmDialog({ title: `«${p.name}» حذف شود؟`, danger: true, confirmLabel: "حذف" }).then(ok => ok && remove.mutate(p.id))}><Trash2 className="size-4" /></Button></Tooltip>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {editing && <PartnerForm partner={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

/** مقادیر فرم از طرف تجاری موجود (null ← رشته خالی، اعداد ← رشته) */
function fromPartner(p: Partner): typeof EMPTY {
  const form = { ...EMPTY };
  for (const key of Object.keys(EMPTY) as (keyof typeof EMPTY)[]) {
    const value = p[key as keyof Partner];
    if (value === null || value === undefined) continue;
    (form as Record<string, unknown>)[key] = typeof EMPTY[key] === "string" ? String(value) : value;
  }
  return form;
}

function PartnerForm({ partner, onClose }: { partner: Partner | null; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data: provinces = [] } = useProvinces();
  const [f, setF] = useState(() => partner ? fromPartner(partner) : EMPTY);
  const set = <K extends keyof typeof EMPTY>(k: K, v: (typeof EMPTY)[K]) => setF(x => ({ ...x, [k]: v }));
  const text = (k: keyof typeof EMPTY) => ({ value: String(f[k] ?? ""), onChange: (e: { target: { value: string } }) => set(k, e.target.value as never) });
  const opt = (v: string) => v.trim() || null;
  const digits = (v: string) => (v.trim() ? normalizeDigits(v.trim()) : null);
  const save = useMutation({
    mutationFn: () => {
      const body: Schemas["PartnerIn"] = {
        code: opt(f.code), name: f.name, kind: f.kind, is_supplier: f.is_supplier, is_customer: f.is_customer, is_carrier: f.is_carrier,
        legal_name: opt(f.legal_name), national_id: digits(f.national_id), economic_code: digits(f.economic_code),
        registration_number: digits(f.registration_number), phone: digits(f.phone), mobile: digits(f.mobile), email: opt(f.email),
        website: opt(f.website), province: opt(f.province), city: opt(f.city), address: opt(f.address), postal_code: digits(f.postal_code),
        contact_name: opt(f.contact_name), contact_mobile: digits(f.contact_mobile), iban: digits(f.iban.replace(/\s/g, "")),
        payment_terms_days: f.payment_terms_days ? Number(normalizeDigits(f.payment_terms_days)) : null,
        lead_time_days: f.is_supplier && f.lead_time_days ? Number(normalizeDigits(f.lead_time_days)) : null,
        carrier_service: f.is_carrier && f.carrier_service ? f.carrier_service : null, tracking_url: f.is_carrier ? opt(f.tracking_url) : null,
        notes: opt(f.notes),
      };
      return partner
        ? unwrap(api.PUT("/partners/{partner_id}", { params: { path: { partner_id: partner.id } }, body }))
        : unwrap(api.POST("/partners/", { body }));
    },
    onSuccess: p => {
      toast.success(partner ? "طرف تجاری ذخیره شد." : `طرف تجاری ${p.code} ثبت شد.`);
      queryClient.invalidateQueries({ queryKey: ["partners"] });
      onClose();
    },
    onError: e => toast.error(errorMessage(e)),
  });
  const masked = partner?.masked;

  return (
    <Modal open onClose={onClose} size="lg" testId="partner-form" title={partner ? `ویرایش ${partner.name}` : "طرف تجاری جدید"}
      footer={<><Button variant="secondary" onClick={onClose}>انصراف</Button><Button type="submit" form="partner-form" loading={save.isPending} data-testid="partner-save">ذخیره</Button></>}>
      <form id="partner-form" className="grid gap-4 sm:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        <div className="flex flex-wrap gap-4 sm:col-span-2" data-testid="partner-roles">
          {Object.entries(PARTNER_ROLES).map(([k, v]) => (
            <Checkbox key={k} label={v.label} checked={f[`is_${k}` as "is_supplier"]} onChange={e => set(`is_${k}` as "is_supplier", e.target.checked)} />
          ))}
        </div>
        <Field label="نام نمایشی *"><Input required minLength={2} maxLength={200} {...text("name")} data-testid="partner-name" /></Field>
        <Field label="کد" hint="خالی = ساخت خودکار (SUP-001، …)"><Input className="ltr uppercase" maxLength={16} {...text("code")} /></Field>
        <Field label="نوع شخصیت">
          <SegmentedControl value={f.kind} onChange={v => set("kind", v)} options={[{ value: "legal", label: "حقوقی" }, { value: "individual", label: "حقیقی" }]} />
        </Field>
        <Field label={f.kind === "legal" ? "شناسه ملی (۱۱ رقم)" : "کد ملی (۱۰ رقم)"} hint={masked ? "فقط ادمین سازمان کامل می‌بیند" : undefined}>
          <Input className="ltr" inputMode="numeric" maxLength={11} disabled={masked} {...text("national_id")} data-testid="partner-national-id" />
        </Field>
        {f.kind === "legal" && <>
          <Field label="نام ثبتی"><Input maxLength={200} {...text("legal_name")} /></Field>
          <Field label="شماره ثبت"><Input className="ltr" inputMode="numeric" maxLength={32} {...text("registration_number")} /></Field>
        </>}
        <Field label="کد اقتصادی" hint="۱۲ تا ۱۴ رقم"><Input className="ltr" inputMode="numeric" maxLength={14} {...text("economic_code")} /></Field>
        <Field label="شماره شبا" hint={masked ? "فقط ادمین سازمان کامل می‌بیند" : "IR و ۲۴ رقم"}>
          <Input className="ltr" maxLength={32} disabled={masked} placeholder="IR..." {...text("iban")} data-testid="partner-iban" />
        </Field>
        <Field label="تلفن"><Input className="ltr" inputMode="tel" maxLength={12} {...text("phone")} /></Field>
        <Field label="موبایل"><Input className="ltr" inputMode="tel" maxLength={11} placeholder="09..." {...text("mobile")} /></Field>
        <Field label="ایمیل"><Input className="ltr" type="email" maxLength={254} {...text("email")} /></Field>
        <Field label="وب‌سایت"><Input className="ltr" maxLength={200} {...text("website")} /></Field>
        <Field label="استان">
          <Select value={f.province} onChange={e => setF(x => ({ ...x, province: e.target.value, city: "" }))}>
            <option value="">—</option>{provinces.map(p => <option key={p} value={p}>{p}</option>)}
          </Select>
        </Field>
        <Field label="شهر"><CitySelect province={f.province} value={f.city} onChange={v => set("city", v)} testId="partner-city" /></Field>
        <Field label="نشانی" className="sm:col-span-2"><Input maxLength={500} {...text("address")} /></Field>
        <Field label="کد پستی" hint="۱۰ رقم"><Input className="ltr" inputMode="numeric" maxLength={10} {...text("postal_code")} /></Field>
        <Field label="مهلت پرداخت (روز)"><Input type="number" min={0} max={365} {...text("payment_terms_days")} /></Field>
        <Field label="نام رابط"><Input maxLength={100} {...text("contact_name")} /></Field>
        <Field label="موبایل رابط"><Input className="ltr" inputMode="tel" maxLength={11} {...text("contact_mobile")} /></Field>
        {f.is_supplier && <Field label="زمان تأمین پیش‌فرض (روز)" hint="برای نقطه سفارش و برنامه خرید"><Input type="number" min={0} max={365} {...text("lead_time_days")} /></Field>}
        {f.is_carrier && <>
          <Field label="نوع خدمت حمل">
            <Select value={f.carrier_service} onChange={e => set("carrier_service", e.target.value as CarrierService | "")}>
              <option value="">—</option>{Object.entries(CARRIER_SERVICES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </Field>
          <Field label="الگوی لینک رهگیری" hint="با https:// و {code} به‌جای کد مرسوله" className="sm:col-span-2">
            <Input className="ltr" maxLength={300} placeholder="https://example.ir/track/{code}" {...text("tracking_url")} />
          </Field>
        </>}
        <Field label="یادداشت" className="sm:col-span-2"><Textarea rows={2} maxLength={2000} {...text("notes")} /></Field>
      </form>
    </Modal>
  );
}
