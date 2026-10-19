/** پروفایل راننده: مشخصات (فقط‌خواندنی)، ویرایش تماس و سکونت، خودروی فعلی، مدارک و تغییر رمز */
import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Car, KeyRound, Lock, Save, UserRound } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useMe } from "@/auth/AuthContext";
import { CitySelect } from "@/components/CitySelect";
import { DocumentSlot, useDocumentUrl } from "@/components/driver/DocumentSlot";
import { PlateView } from "@/components/driver/DriverInputs";
import { LevelProgressCard, RatingTags, Rial, SOURCE_LABELS, Stars } from "@/components/performance/PerformanceUI";
import { VehicleStatusBadge } from "@/components/StatusBadges";
import { useToast } from "@/components/Toast";
import { useProvinces } from "@/hooks/data";
import { DRIVER_STATUS, type DocumentKind, type DriverStatus } from "@/lib/driver";
import { VEHICLE_TYPES } from "@/lib/labels";
import { faDate, faNumber, latinDigits } from "@/lib/format";
import { Badge, Button, Card, CardHeader, DataList, ErrorState, Field, Input, PageHeader, Select, Skeleton, buttonClass } from "@/ui/primitives";
import { PasswordChangeForm } from "@/components/PasswordChangeForm";

type Profile = Schemas["DriverProfileResponse"];

export default function DriverProfilePage() {
  const me = useMe();
  const { data: p, error, refetch } = useQuery({ queryKey: ["driver-profile"], queryFn: () => unwrap(api.GET("/driver/profile")) });
  const avatar = useDocumentUrl("/driver-onboarding/documents/selfie", p?.documents.find(d => d.kind === "selfie"));

  if (error) return <ErrorState error={error} onRetry={refetch} />;
  if (!p) return <div className="mx-auto max-w-4xl space-y-4"><Skeleton className="h-32 rounded-2xl" /><Skeleton className="h-80 rounded-2xl" /></div>;
  const status = DRIVER_STATUS[p.driver_status as DriverStatus];

  return (
    <div className="mx-auto max-w-4xl" data-testid="driver-profile">
      <PageHeader eyebrow="راننده" title="پروفایل من" />
      <Card className="mb-6 overflow-hidden">
        <div className="flex flex-wrap items-center gap-5 bg-linear-to-l from-brand-soft to-transparent p-6">
          <div className="grid size-20 place-items-center overflow-hidden rounded-2xl bg-surface-2 ring-4 ring-surface">
            {avatar ? <img src={avatar} alt="" className="size-full object-cover" /> : <UserRound className="size-9 text-muted" />}
          </div>
          <div>
            <h2 className="text-2xl font-black">{[p.first_name, p.last_name].filter(Boolean).join(" ") || p.full_name || p.username}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-text-2">
              <span className="font-mono ltr">{p.driver_code}</span>·<span>{me.organization?.name}</span>
              <Badge tone={status?.tone ?? "muted"} dot>{status?.label}</Badge>
            </div>
          </div>
        </div>
      </Card>

      <MyPerformance />

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-6">
          <Card>
            <CardHeader title={<span className="flex items-center gap-2"><Lock className="size-4 text-muted" />مشخصات هویتی</span>}
              subtitle="برای اصلاح این موارد با ادمین سازمان تماس بگیرید." />
            <div className="p-5">
              <DataList items={[
                ["نام", p.first_name], ["نام خانوادگی", p.last_name], ["کد ملی", <span className="font-mono ltr">{p.national_code}</span>],
                ["تاریخ تولد", p.birth_date ? faDate(p.birth_date) : null], ["نام کاربری", <span className="font-mono ltr">{p.username}</span>],
                ["عضویت از", faDate(p.created_at)],
              ]} />
            </div>
          </Card>
          <ContactForm profile={p} />
          <PasswordForm />
        </div>
        <div className="space-y-6">
          <Card data-testid="profile-vehicle">
            <CardHeader title={<span className="flex items-center gap-2"><Car className="size-4 text-brand" />خودروی فعلی</span>}
              actions={<Link to="/app/driver/requests?new=vehicle" className={buttonClass("soft", "sm")} data-testid="profile-change-vehicle">درخواست تغییر خودرو</Link>} />
            <div className="p-5">
              {p.current_vehicle ? (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="text-lg font-bold">{p.current_vehicle.model as string}</span>
                    <PlateView plate={p.current_vehicle.license_plate as string} />
                    <VehicleStatusBadge status={p.current_vehicle.status as string} />
                  </div>
                  <DataList items={[
                    ["نوع", VEHICLE_TYPES[p.current_vehicle.type as string] ?? (p.current_vehicle.type as string)],
                    ["ظرفیت", `${faNumber(p.current_vehicle.capacity_kg as number)} کیلوگرم`],
                    ["رنگ", p.vehicle_color], ["اعتبار معاینه فنی", p.inspection_expiry ? faDate(p.inspection_expiry) : null],
                  ]} />
                </div>
              ) : <p className="text-sm text-muted">خودرویی به شما اختصاص داده نشده است.</p>}
            </div>
          </Card>
          <Card>
            <CardHeader title="مدارک" subtitle="مدارک تأییدشده — برای دیدن، روی هر کدام بزنید." />
            <div className="grid gap-3 p-5">
              {p.documents.length === 0 && <p className="text-sm text-muted">مدرکی ثبت نشده است.</p>}
              {p.documents.map(d => (
                <DocumentSlot key={d.kind} kind={d.kind as DocumentKind} doc={d} required={false} disabled
                  fileUrl={`/driver-onboarding/documents/${d.kind}`} uploadUrl="" onUploaded={() => {}} onError={() => {}} />
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function ContactForm({ profile }: { profile: Profile }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data: provinces = [] } = useProvinces();
  const pick = (p: Profile) => ({ mobile: p.mobile ?? "", email: p.email ?? "", province: p.province ?? "", city: p.city ?? "", address: p.address ?? "", postal_code: p.postal_code ?? "" });
  const [form, setForm] = useState(() => pick(profile));
  useEffect(() => setForm(pick(profile)), [profile]);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm(f => ({ ...f, [k]: e.target.value }));
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, string> = {};
      for (const [k, v] of Object.entries(form)) if (v.trim()) body[k] = ["mobile", "postal_code"].includes(k) ? latinDigits(v.trim()) : v.trim();
      return unwrap(api.PUT("/driver/profile", { body }));
    },
    onSuccess: p => { queryClient.setQueryData(["driver-profile"], p); queryClient.invalidateQueries({ queryKey: ["me"] }); toast.success("اطلاعات ذخیره شد."); },
    onError: e => toast.error(errorMessage(e)),
  });
  return (
    <Card>
      <form onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }} data-testid="profile-contact-form">
        <CardHeader title="تماس و محل سکونت" actions={<Button type="submit" size="sm" icon={<Save className="size-4" />} loading={save.isPending} data-testid="profile-save">ذخیره</Button>} />
        <div className="grid gap-4 p-5 sm:grid-cols-2">
          <Field label="شماره همراه"><Input className="ltr" inputMode="tel" value={form.mobile} onChange={set("mobile")} data-testid="profile-mobile" /></Field>
          <Field label="ایمیل"><Input className="ltr" type="email" value={form.email} onChange={set("email")} /></Field>
          <Field label="استان"><Select value={form.province} onChange={set("province")}><option value="">—</option>{provinces.map(x => <option key={x} value={x}>{x}</option>)}</Select></Field>
          <Field label="شهر"><CitySelect province={form.province} value={form.city} onChange={v => setForm(f => ({ ...f, city: v }))} /></Field>
          <Field label="نشانی" className="sm:col-span-2"><Input value={form.address} onChange={set("address")} data-testid="profile-address" /></Field>
          <Field label="کد پستی"><Input className="ltr" inputMode="numeric" value={form.postal_code} onChange={set("postal_code")} /></Field>
        </div>
      </form>
    </Card>
  );
}

function PasswordForm() {
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><KeyRound className="size-4 text-muted" />تغییر رمز عبور</span>} />
      <div className="p-5"><PasswordChangeForm columns={3} /></div>
    </Card>
  );
}

/** سطح، امتیاز و درآمد راننده (پورسانت پلکانی) */
function MyPerformance() {
  const { data } = useQuery({ queryKey: ["my-performance"], queryFn: () => unwrap(api.GET("/driver/performance")) });
  if (!data) return null;
  return (
    <div className="mb-6 grid gap-6 lg:grid-cols-2" data-testid="my-performance">
      <Card><CardHeader title="سطح من" /><div className="p-5"><LevelProgressCard p={data.progress} /></div></Card>
      <Card>
        <CardHeader title="درآمد و امتیاز" />
        <div className="grid grid-cols-3 gap-2 p-5 text-center">
          {([["امروز", data.today], ["این ماه", data.month], ["کل", data.all_time]] as const).map(([label, s]) => (
            <div key={label} className="rounded-xl bg-surface-2 p-3">
              <div className="text-xs text-muted">{label}</div>
              <div className="mt-1 text-sm font-black text-success"><Rial value={s.earnings} /></div>
              <div className="text-[11px] text-muted">{faNumber(s.deliveries)} تحویل · پورسانت <Rial value={s.commission} /></div>
            </div>
          ))}
        </div>
        <ul className="divide-y divide-border border-t border-border">
          {data.recent_ratings.length === 0 && <li className="px-5 py-4 text-sm text-muted">هنوز امتیازی نگرفته‌اید.</li>}
          {data.recent_ratings.slice(0, 5).map(r => (
            <li key={r.id} className="flex flex-wrap items-center gap-2 px-5 py-2.5 text-sm">
              <Stars value={r.score} /><Badge tone="muted">{SOURCE_LABELS[r.source]}</Badge>
              <RatingTags tags={r.tags} />
              {r.comment && <span className="text-text-2">«{r.comment}»</span>}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
