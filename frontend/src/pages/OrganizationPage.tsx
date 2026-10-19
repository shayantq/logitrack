import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ImageUp, Palette, Save, Trash2 } from "lucide-react";
import { api, authFetch, errorMessage, unwrap, type Schemas } from "@/api/client";
import { CitySelect } from "@/components/CitySelect";
import { useToast } from "@/components/Toast";
import { useProvinces } from "@/hooks/data";
import { BUSINESS_TYPES, EMPLOYEE_RANGES, ORDER_VOLUMES } from "@/lib/labels";
import { latinDigits, normalizeDigits } from "@/lib/format";
import { Button, Card, CardHeader, ErrorState, Field, Input, PageHeader, Select, Skeleton, cn } from "@/ui/primitives";
import { confirmDialog } from "@/ui/dialogs";
import { FileField } from "@/ui/file";

type Profile = Schemas["OrganizationProfileResponse"];
const TEXT_FIELDS = ["name", "legal_name", "business_type", "national_id", "economic_code", "registration_number", "province", "city",
  "address", "postal_code", "phone", "website", "employee_count", "monthly_order_volume", "contact_name", "contact_mobile", "contact_email"] as const;
const DIGIT_FIELDS = new Set(["national_id", "economic_code", "registration_number", "postal_code", "phone", "contact_mobile"]);
type FormState = Record<(typeof TEXT_FIELDS)[number] | "warehouse_count" | "fleet_size", string>;

export default function OrganizationPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data: provinces = [] } = useProvinces();
  const { data: profile, error, refetch } = useQuery({ queryKey: ["organization-profile"], queryFn: () => unwrap(api.GET("/organization/profile")) });
  const [form, setForm] = useState<FormState | null>(null);
  const [logoFile, setLogoFile] = useState<File | null>(null);

  useEffect(() => {
    if (!profile) return;
    const next = {} as FormState;
    for (const key of [...TEXT_FIELDS, "warehouse_count", "fleet_size"] as const) {
      const value = profile[key as keyof Profile];
      next[key] = value === null || value === undefined ? "" : String(value);
    }
    setForm(next);
  }, [profile]);

  const { data: logoUrl } = useQuery({
    queryKey: ["organization-logo", profile?.has_logo, profile?.updated_at],
    queryFn: async () => { const res = await authFetch("/organization/logo"); return res.ok ? URL.createObjectURL(await res.blob()) : null; },
    enabled: !!profile?.has_logo,
  });
  const afterChange = (p: Profile) => { queryClient.setQueryData(["organization-profile"], p); queryClient.invalidateQueries({ queryKey: ["me"] }); };
  const save = useMutation({
    mutationFn: (body: Schemas["OrganizationProfileUpdate"]) => unwrap(api.PUT("/organization/profile", { body })),
    onSuccess: p => { toast.success("پروفایل سازمان ذخیره شد."); afterChange(p); },
    onError: e => toast.error(errorMessage(e)),
  });
  const uploadLogo = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      const res = await authFetch("/organization/logo", { method: "POST", body });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(errorMessage(data, "خطا در آپلود لوگو."));
      return data as Profile;
    },
    onSuccess: p => { toast.success("لوگو آپلود شد."); setLogoFile(null); afterChange(p); },
    onError: e => toast.error(errorMessage(e)),
  });
  const deleteLogo = useMutation({
    mutationFn: () => unwrap(api.DELETE("/organization/logo")),
    onSuccess: () => { toast.success("لوگو حذف شد."); refetch(); },
    onError: e => toast.error(errorMessage(e)),
  });

  if (error) return <ErrorState error={error} onRetry={refetch} />;
  if (!form || !profile) return <div className="grid gap-6 lg:grid-cols-3"><Skeleton className="h-72 rounded-2xl" /><Skeleton className="h-[32rem] rounded-2xl lg:col-span-2" /></div>;

  const set = (k: keyof FormState) => (e: { target: { value: string } }) => setForm(f => f && ({ ...f, [k]: e.target.value }));
  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const body: Record<string, string | number | null> = {};
    for (const key of TEXT_FIELDS) {
      const raw = form![key].trim();
      body[key] = raw === "" ? null : DIGIT_FIELDS.has(key) ? normalizeDigits(raw) : raw;
    }
    for (const key of ["warehouse_count", "fleet_size"] as const) body[key] = form![key] === "" ? null : Number(form![key]);
    save.mutate(body as Schemas["OrganizationProfileUpdate"]);
  }
  const options = (key: keyof FormState, map: Record<string, string>) => (
    <Select value={form[key]} onChange={set(key)}><option value="">—</option>{Object.entries(map).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>
  );

  return (
    <>
      <PageHeader eyebrow="تنظیمات" title="پروفایل سازمان" subtitle={<>شناسه سازمان: <span className="font-mono ltr">{profile.slug}</span></>} />
      <div className="grid items-start gap-6 lg:grid-cols-3">
        <Card className="h-fit lg:col-start-1">
          <CardHeader title="لوگوی سازمان" subtitle="در هدر پنل‌ها و سربرگ گزارش‌ها" />
          <div className="space-y-4 p-5">
            <div className="grid h-40 place-items-center rounded-xl border border-dashed border-border-strong bg-surface-2">
              {logoUrl ? <img src={logoUrl} alt="لوگو" className="max-h-32 max-w-[80%] object-contain" /> : <ImageUp className="size-8 text-muted" />}
            </div>
            <FileField file={logoFile} onChange={setLogoFile} accept="image/png,image/jpeg,image/webp" testId="logo-file"
              placeholder="تصویر لوگو را انتخاب کنید" button="انتخاب تصویر" icon={<ImageUp className="size-4" />} />
            <p className="text-xs text-muted">PNG، JPG یا WEBP — حداکثر ۲ مگابایت.</p>
            <div className="flex gap-2">
              <Button size="sm" icon={<ImageUp className="size-4" />} disabled={!logoFile} loading={uploadLogo.isPending} onClick={() => logoFile && uploadLogo.mutate(logoFile)}>آپلود</Button>
              {profile.has_logo && <Button size="sm" variant="outline-danger" icon={<Trash2 className="size-4" />} onClick={() => confirmDialog({ title: "لوگو حذف شود؟", confirmLabel: "حذف", danger: true }).then(ok => ok && deleteLogo.mutate())}>حذف</Button>}
            </div>
          </div>
        </Card>
        <BrandColorCard profile={profile} logoUrl={logoUrl ?? null} onSaved={afterChange} />
        <Card className="lg:col-span-2 lg:col-start-2 lg:row-span-2 lg:row-start-1">
          <form onSubmit={onSubmit} data-testid="org-profile-form">
            <CardHeader title="اطلاعات هویتی و تجاری" actions={<Button type="submit" size="sm" icon={<Save className="size-4" />} loading={save.isPending}>ذخیره</Button>} />
            <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="نام تجاری *" className="sm:col-span-2 lg:col-span-1"><Input required minLength={2} value={form.name} onChange={set("name")} /></Field>
              <Field label="نام ثبتی" className="lg:col-span-2"><Input value={form.legal_name} onChange={set("legal_name")} /></Field>
              <Field label="حوزه فعالیت">{options("business_type", BUSINESS_TYPES)}</Field>
              <Field label="شناسه ملی"><Input className="ltr" value={form.national_id} onChange={set("national_id")} /></Field>
              <Field label="کد اقتصادی"><Input className="ltr" value={form.economic_code} onChange={set("economic_code")} /></Field>
              <Field label="شماره ثبت"><Input className="ltr" value={form.registration_number} onChange={set("registration_number")} /></Field>
              <Field label="استان"><Select value={form.province} onChange={set("province")}><option value="">—</option>{provinces.map(p => <option key={p} value={p}>{p}</option>)}</Select></Field>
              <Field label="شهر"><CitySelect province={form.province} value={form.city} onChange={v => setForm(f => f && ({ ...f, city: v }))} /></Field>
              <Field label="نشانی" className="sm:col-span-2 lg:col-span-3"><Input value={form.address} onChange={set("address")} /></Field>
              <Field label="کد پستی"><Input className="ltr" value={form.postal_code} onChange={set("postal_code")} /></Field>
              <Field label="تلفن ثابت"><Input className="ltr" value={form.phone} onChange={set("phone")} /></Field>
              <Field label="وب‌سایت"><Input className="ltr" value={form.website} onChange={set("website")} /></Field>
              <Field label="تعداد کارکنان">{options("employee_count", EMPLOYEE_RANGES)}</Field>
              <Field label="سفارش ماهانه">{options("monthly_order_volume", ORDER_VOLUMES)}</Field>
              <Field label="تعداد انبار"><Input type="number" min={0} value={form.warehouse_count} onChange={set("warehouse_count")} /></Field>
              <Field label="تعداد راننده/خودرو"><Input type="number" min={0} value={form.fleet_size} onChange={set("fleet_size")} /></Field>
              <Field label="نام مسئول"><Input value={form.contact_name} onChange={set("contact_name")} /></Field>
              <Field label="همراه مسئول"><Input className="ltr" value={form.contact_mobile} onChange={set("contact_mobile")} /></Field>
              <Field label="ایمیل مسئول" className="sm:col-span-2 lg:col-span-3"><Input type="email" className="ltr" value={form.contact_email} onChange={set("contact_email")} /></Field>
            </div>
          </form>
        </Card>
      </div>
    </>
  );
}

/** رنگ پیش‌فرض سربرگ گزارش‌ها — همان رنگ برند LogiTrack (report_builder.DEFAULT_COLOR) */
const DEFAULT_BRAND = "#0D9488";
const SWATCHES = ["#0D9488", "#1D4ED8", "#4338CA", "#7C3AED", "#BE185D", "#B91C1C", "#C2410C", "#A16207", "#15803D", "#334155"];

function BrandColorCard({ profile, logoUrl, onSaved }: { profile: Profile; logoUrl: string | null; onSaved: (p: Profile) => void }) {
  const toast = useToast();
  const saved = (profile.brand_color ?? "").toUpperCase();
  const [color, setColor] = useState(saved || DEFAULT_BRAND);
  const [hex, setHex] = useState(saved || DEFAULT_BRAND);
  useEffect(() => { setColor(saved || DEFAULT_BRAND); setHex(saved || DEFAULT_BRAND); }, [saved]);
  const save = useMutation({
    mutationFn: (brand_color: string | null) => unwrap(api.PUT("/organization/profile", { body: { brand_color } })),
    onSuccess: p => { toast.success("رنگ گزارش‌ها ذخیره شد."); onSaved(p); },
    onError: e => toast.error(errorMessage(e)),
  });
  const pick = (c: string) => { setColor(c); setHex(c); };
  const onHex = (raw: string) => {
    const v = ("#" + latinDigits(raw).replace(/[^0-9a-fA-F]/g, "").slice(0, 6)).toUpperCase();
    setHex(v);
    if (/^#[0-9A-F]{6}$/.test(v)) setColor(v);
  };
  const dirty = color !== (saved || DEFAULT_BRAND);

  return (
    <Card className="h-fit lg:col-start-1" data-testid="brand-color-card">
      <CardHeader title="رنگ سربرگ گزارش‌ها" subtitle="در فایل‌های اکسل و PDF، کنار لوگو" />
      <div className="space-y-4 p-5">
        {/* پیش‌نمایش کوچک سربرگ */}
        <div className="overflow-hidden rounded-xl border border-border bg-white text-[11px] text-slate-700" data-testid="brand-preview" data-color={color}>
          <div className="flex items-center gap-2 p-3">
            {logoUrl ? <img src={logoUrl} alt="" className="size-8 object-contain" /> : <span className="size-8 rounded-full" style={{ background: color }} />}
            <div className="min-w-0">
              <div className="truncate text-sm font-bold" style={{ color }}>{profile.name}</div>
              <div className="text-slate-500">گزارش مالی حمل‌ونقل</div>
            </div>
          </div>
          <div className="h-0.5 transition-colors duration-300" style={{ background: color }} />
          <div className="grid grid-cols-3 px-3 py-1.5 font-medium text-white transition-colors duration-300" style={{ background: color }}><span>راننده</span><span>سفر</span><span>کرایه</span></div>
          <div className="grid grid-cols-3 px-3 py-1.5"><span>علی رضایی</span><span>۱۶</span><span>۶۴٬۸۰۰٬۰۰۰</span></div>
        </div>
        <div className="grid w-fit grid-cols-5 gap-2.5" role="radiogroup" aria-label="رنگ گزارش‌ها">
          {SWATCHES.map(c => (
            <button key={c} type="button" role="radio" aria-checked={color === c} aria-label={c} data-testid="brand-swatch" data-color={c}
              onClick={() => pick(c)} style={{ background: c }}
              className={cn("grid size-8 place-items-center rounded-full text-white transition duration-200 hover:scale-110 focus:outline-none focus-visible:ring-4 focus-visible:ring-brand/30",
                color === c && "ring-2 ring-offset-2 ring-offset-surface")}
              data-active={color === c || undefined}>
              {color === c && <Check className="size-4" />}
            </button>
          ))}
        </div>
        <Field label="کد رنگ دلخواه">
          <div className="flex items-center gap-2">
            <span className="size-10 shrink-0 rounded-xl border border-border transition-colors duration-300" style={{ background: color }} />
            <Input className="ltr font-mono" value={hex} maxLength={7} onChange={e => onHex(e.target.value)} data-testid="brand-hex" aria-label="کد رنگ" />
          </div>
        </Field>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" icon={<Palette className="size-4" />} disabled={!dirty} loading={save.isPending} onClick={() => save.mutate(color)} data-testid="brand-save">ذخیره رنگ</Button>
          {saved && <Button size="sm" variant="ghost" onClick={() => save.mutate(null)}>بازگشت به پیش‌فرض</Button>}
        </div>
      </div>
    </Card>
  );
}
