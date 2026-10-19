/**
 * فرم چندمرحله‌ای احراز هویت راننده:
 * وسیله ← هویت و مدارک ← مشخصات وسیله ← محل سکونت ← بازبینی و ارسال.
 * هر مرحله جدا ذخیره می‌شود (راننده می‌تواند بعداً ادامه دهد)؛ مدارک بلافاصله آپلود می‌شوند.
 */
import { useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, ArrowRight, Check, Clock, FileCheck2, Home, IdCard, Send, Truck } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { CitySelect } from "@/components/CitySelect";
import { DocumentSlot } from "@/components/driver/DocumentSlot";
import { JalaliDateInput, PlateInput, PlateView, thisJalaliYear } from "@/components/driver/DriverInputs";
import { useToast } from "@/components/Toast";
import { useProvinces } from "@/hooks/data";
import { DRIVER_STATUS, MISSING_LABELS, STEP_OF, VEHICLE_KINDS, type DocumentKind } from "@/lib/driver";
import { faDate, faDateTime, faNumber, latinDigits } from "@/lib/format";
import { Badge, Button, Card, ErrorState, Field, Input, PageHeader, Select, Skeleton, cn } from "@/ui/primitives";

type Application = Schemas["DriverApplicationResponse"];
type Update = Schemas["DriverApplicationUpdate"];

const STEPS = [
  { title: "وسیله", icon: Truck },
  { title: "هویت و مدارک", icon: IdCard },
  { title: "مشخصات وسیله", icon: FileCheck2 },
  { title: "محل سکونت", icon: Home },
  { title: "بازبینی و ارسال", icon: Send },
];

export default function OnboardingPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data: app, error, refetch } = useQuery({
    queryKey: ["my-application"],
    queryFn: () => unwrap(api.GET("/driver-onboarding")),
    // در انتظار بررسی: هر ۳۰ ثانیه، تا تأیید/رد بلافاصله دیده شود
    refetchInterval: q => (q.state.data?.driver_status === "submitted" ? 30_000 : false),
  });

  useEffect(() => {
    if (app?.driver_status === "approved") {
      queryClient.invalidateQueries({ queryKey: ["me"] }).then(() => navigate("/app/driver", { replace: true }));
    }
  }, [app?.driver_status, navigate, queryClient]);

  if (error) return <ErrorState error={error} onRetry={refetch} />;
  if (!app) return <div className="mx-auto max-w-3xl space-y-4"><Skeleton className="h-24 rounded-2xl" /><Skeleton className="h-96 rounded-2xl" /></div>;
  if (app.driver_status === "submitted") return <Waiting app={app} />;
  return <Wizard app={app} />;
}

function Waiting({ app }: { app: Application }) {
  return (
    <div className="mx-auto max-w-2xl" data-testid="onboarding-waiting">
      <Card className="overflow-hidden">
        <div className="bg-linear-to-l from-brand to-brand-strong p-8 text-brand-ink">
          <div className="grid size-14 place-items-center rounded-2xl bg-white/20"><Clock className="size-7" /></div>
          <h1 className="mt-5 text-2xl font-black">پرونده شما در حال بررسی است</h1>
          <p className="mt-2 leading-7 opacity-90">ادمین سازمان مدارک را بررسی می‌کند. پس از تأیید، سفارش‌ها در همین پنل نمایش داده می‌شوند — این صفحه خودکار به‌روز می‌شود.</p>
        </div>
        <ol className="space-y-4 p-6">
          {[["ساخت حساب", app.created_at, true], ["ارسال پرونده", app.submitted_at, true], ["بررسی و تأیید سازمان", null, false]].map(([label, at, done], i) => (
            <li key={i} className="flex items-center gap-3">
              <span className={cn("grid size-8 place-items-center rounded-full", done ? "bg-brand text-brand-ink" : "border-2 border-brand bg-surface")}>
                {done ? <Check className="size-4" /> : <span className="size-2 animate-pulse rounded-full bg-brand" />}
              </span>
              <span className="flex-1 font-medium">{label as string}</span>
              <span className="text-xs text-muted">{at ? faDateTime(at as string) : "در جریان"}</span>
            </li>
          ))}
        </ol>
        <div className="flex flex-wrap items-center gap-3 border-t border-border bg-surface-2 px-6 py-4 text-sm">
          <span className="text-muted">وسیله:</span><b>{app.vehicle_model}</b><PlateView plate={app.license_plate} />
        </div>
      </Card>
    </div>
  );
}

function Wizard({ app }: { app: Application }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const firstIncomplete = Math.min(4, ...app.missing.map(k => STEP_OF[k] ?? 4));
  const [step, setStep] = useState(app.missing.length ? firstIncomplete : 4);
  const [form, setForm] = useState<Update>(() => pickFields(app));
  const setField = <K extends keyof Update>(key: K, value: Update[K]) => setForm(f => ({ ...f, [key]: value }));
  const accept = (next: Application) => queryClient.setQueryData(["my-application"], next);

  const save = useMutation({
    mutationFn: (body: Update) => unwrap(api.PUT("/driver-onboarding", { body })),
    onSuccess: next => { accept(next); setStep(s => Math.min(4, s + 1)); window.scrollTo({ top: 0, behavior: "smooth" }); },
    onError: e => toast.error(errorMessage(e)),
  });
  const submit = useMutation({
    mutationFn: () => unwrap(api.POST("/driver-onboarding/submit")),
    onSuccess: next => { accept(next); toast.success("پرونده برای بررسی ارسال شد."); },
    onError: e => toast.error(errorMessage(e)),
  });

  const stepDone = (i: number) => !app.missing.some(k => (STEP_OF[k] ?? 4) === i);
  const motorcycle = form.vehicle_type === "motorcycle";
  const required = new Set(app.required_documents);
  const slot = (kind: DocumentKind) => (
    <DocumentSlot key={kind} kind={kind} doc={app.documents.find(d => d.kind === kind)} required={required.has(kind)}
      fileUrl={`/driver-onboarding/documents/${kind}`} uploadUrl={`/driver-onboarding/documents/${kind}`}
      onUploaded={next => { accept(next as Application); toast.success("مدرک بارگذاری شد."); }} onError={toast.error} />
  );
  /** فقط فیلدهای همین مرحله، بدون مقدارهای خالی */
  const saveStep = (keys: (keyof Update)[]) => {
    const body: Update = {};
    for (const k of keys) {
      const v = form[k];
      if (v !== undefined && v !== null && v !== "") (body as Record<string, unknown>)[k] = v;
    }
    save.mutate(body);
  };

  return (
    <div className="mx-auto max-w-3xl" data-testid="onboarding">
      <PageHeader eyebrow="احراز هویت راننده" title="تکمیل پرونده" subtitle="اطلاعات هر مرحله ذخیره می‌شود؛ هر وقت خواستید ادامه دهید." />

      {app.driver_status === "rejected" && (
        <div className="mb-6 flex gap-3 rounded-2xl border border-danger/30 bg-danger-soft p-4 text-sm text-danger" data-testid="onboarding-rejected">
          <AlertTriangle className="mt-0.5 size-5 shrink-0" />
          <div><b>پرونده شما رد شد.</b> دلیل: {app.rejection_reason}<div className="mt-1 text-text-2">موارد را اصلاح کنید و دوباره ارسال کنید.</div></div>
        </div>
      )}

      {/* مراحل */}
      <ol className="mb-6 grid grid-cols-5 gap-1.5" data-testid="onboarding-steps">
        {STEPS.map((s, i) => (
          <li key={s.title}>
            <button type="button" onClick={() => setStep(i)} className="group flex w-full flex-col items-center gap-1.5 text-center">
              <span className={cn("grid size-10 place-items-center rounded-xl transition",
                i === step ? "bg-brand text-brand-ink shadow-[var(--shadow)]" : i < 4 && stepDone(i) ? "bg-brand-soft text-brand" : "bg-surface-2 text-muted")}>
                {i < 4 && stepDone(i) && i !== step ? <Check className="size-5" /> : <s.icon className="size-5" />}
              </span>
              <span className={cn("hidden text-[11px] sm:block", i === step ? "font-bold text-text" : "text-muted")}>{s.title}</span>
            </button>
          </li>
        ))}
      </ol>

      <Card className="p-5 sm:p-7">
        <div key={step} className="animate-rise">
          {step === 0 && (
            <Section title="با چه وسیله‌ای بار جابه‌جا می‌کنید؟">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3" role="radiogroup" data-testid="vehicle-kind">
                {VEHICLE_KINDS.map(k => (
                  <button key={k.value} type="button" role="radio" aria-checked={form.vehicle_type === k.value}
                    onClick={() => setField("vehicle_type", k.value as Update["vehicle_type"])}
                    className={cn("flex flex-col items-start gap-3 rounded-2xl border-2 p-4 text-start transition",
                      form.vehicle_type === k.value ? "border-brand bg-brand-soft" : "border-border hover:border-border-strong")}>
                    <k.icon className={cn("size-8", form.vehicle_type === k.value ? "text-brand" : "text-muted")} />
                    <span><span className="block font-bold">{k.label}</span><span className="text-xs text-muted">{k.hint}</span></span>
                  </button>
                ))}
              </div>
              <Nav onNext={() => form.vehicle_type ? saveStep(["vehicle_type"]) : toast.error("نوع وسیله را انتخاب کنید.")} loading={save.isPending} />
            </Section>
          )}

          {step === 1 && (
            <Section title="مشخصات هویتی">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="نام"><Input value={form.first_name ?? ""} onChange={e => setField("first_name", e.target.value)} data-testid="ob-first-name" /></Field>
                <Field label="نام خانوادگی"><Input value={form.last_name ?? ""} onChange={e => setField("last_name", e.target.value)} data-testid="ob-last-name" /></Field>
                <Field label="کد ملی" hint="۱۰ رقم"><Input className="ltr" inputMode="numeric" maxLength={10} value={form.national_code ?? ""}
                  onChange={e => setField("national_code", latinDigits(e.target.value))} data-testid="ob-national-code" /></Field>
                <Field label="شماره همراه"><Input className="ltr" inputMode="tel" value={form.mobile ?? ""} onChange={e => setField("mobile", latinDigits(e.target.value))} /></Field>
                <Field label="تاریخ تولد" className="sm:col-span-2">
                  <JalaliDateInput value={form.birth_date} onChange={v => setField("birth_date", v)} fromYear={thisJalaliYear() - 75} toYear={thisJalaliYear() - 18} testId="ob-birth-date" />
                </Field>
              </div>
              <h3 className="mb-3 mt-8 font-bold">مدارک هویتی</h3>
              <div className="grid gap-3">{(["national_card", "selfie", "video", "driving_license"] as DocumentKind[]).map(slot)}</div>
              <Nav onBack={() => setStep(0)} onNext={() => saveStep(["first_name", "last_name", "national_code", "mobile", "birth_date"])} loading={save.isPending} />
            </Section>
          )}

          {step === 2 && (
            <Section title="مشخصات وسیله">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="مدل وسیله" hint="مثلاً نیسان زامیاد، پژو پارس"><Input value={form.vehicle_model ?? ""} onChange={e => setField("vehicle_model", e.target.value)} data-testid="ob-model" /></Field>
                <Field label="رنگ" hint="اختیاری"><Input value={form.vehicle_color ?? ""} onChange={e => setField("vehicle_color", e.target.value)} /></Field>
                <Field label="پلاک" className="sm:col-span-2">
                  <PlateInput key={String(motorcycle)} motorcycle={motorcycle} value={form.license_plate} onChange={v => setField("license_plate", v || null)} />
                </Field>
                <Field label="سقف وزن بار (کیلوگرم)" hint={`حداکثر برای این وسیله: ${faNumber(VEHICLE_KINDS.find(k => k.value === form.vehicle_type)?.maxKg ?? 0)}`}>
                  <Input type="number" min={1} value={form.max_weight_kg ?? ""} onChange={e => setField("max_weight_kg", e.target.value ? Number(latinDigits(e.target.value)) : null)} data-testid="ob-max-weight" />
                </Field>
                {!motorcycle && (
                  <Field label="اعتبار معاینه فنی تا">
                    <JalaliDateInput value={form.inspection_expiry} onChange={v => setField("inspection_expiry", v)} fromYear={thisJalaliYear()} toYear={thisJalaliYear() + 3} testId="ob-inspection" />
                  </Field>
                )}
                <label className="flex cursor-pointer items-center justify-between gap-4 rounded-2xl border border-border p-4 sm:col-span-2">
                  <span><span className="block font-semibold">بار بین‌شهری می‌برم</span><span className="text-xs text-muted">سفارش‌های شهرهای دیگر هم به شما پیشنهاد شود</span></span>
                  <input type="checkbox" className="size-5 accent-[var(--brand)]" checked={!!form.intercity} onChange={e => setField("intercity", e.target.checked)} data-testid="ob-intercity" />
                </label>
              </div>
              <h3 className="mb-3 mt-8 font-bold">مدارک وسیله</h3>
              <div className="grid gap-3">
                {(["vehicle_photo", "vehicle_card", ...(motorcycle ? [] : ["technical_inspection"])] as DocumentKind[]).map(slot)}
              </div>
              <Nav onBack={() => setStep(1)} onNext={() => saveStep(["vehicle_model", "vehicle_color", "license_plate", "max_weight_kg", "inspection_expiry", "intercity"])} loading={save.isPending} />
            </Section>
          )}

          {step === 3 && <ResidenceStep form={form} setField={setField} onBack={() => setStep(2)}
            onNext={() => saveStep(["province", "city", "address", "postal_code"])} loading={save.isPending} />}

          {step === 4 && (
            <Section title="بازبینی و ارسال">
              {app.missing.length > 0 ? (
                <div className="rounded-2xl border border-warning/30 bg-warning-soft p-4" data-testid="onboarding-missing">
                  <div className="mb-3 font-bold text-warning">این موارد هنوز کامل نشده‌اند:</div>
                  <div className="flex flex-wrap gap-2">
                    {app.missing.map(k => (
                      <button key={k} type="button" onClick={() => setStep(STEP_OF[k] ?? 0)}
                        className="rounded-full border border-warning/40 bg-surface px-3 py-1 text-sm hover:border-warning">{MISSING_LABELS[k] ?? k}</button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="rounded-2xl border border-success/30 bg-success-soft p-4 font-semibold text-success">همه اطلاعات و مدارک کامل است ✓</div>
              )}
              <dl className="mt-6 grid gap-x-6 gap-y-4 sm:grid-cols-2">
                {[
                  ["نام", [app.first_name, app.last_name].filter(Boolean).join(" ")], ["کد ملی", app.national_code],
                  ["تاریخ تولد", app.birth_date ? faDate(app.birth_date) : null], ["همراه", app.mobile],
                  ["وسیله", [VEHICLE_KINDS.find(k => k.value === app.vehicle_type)?.label, app.vehicle_model].filter(Boolean).join(" — ")],
                  ["پلاک", app.license_plate ? <PlateView plate={app.license_plate} /> : null],
                  ["سقف بار", app.max_weight_kg ? `${faNumber(app.max_weight_kg)} کیلوگرم` : null], ["بین‌شهری", app.intercity ? "بله" : "خیر"],
                  ["سکونت", [app.province, app.city].filter(Boolean).join(" / ")], ["مدارک", `${faNumber(app.documents.length)} از ${faNumber(app.required_documents.length)}`],
                ].map(([k, v]) => (
                  <div key={k as string}><dt className="text-xs text-muted">{k}</dt><dd className="mt-0.5 font-medium">{v || "—"}</dd></div>
                ))}
              </dl>
              <p className="mt-6 text-sm leading-7 text-muted">با ارسال، اطلاعات و مدارک تا پایان بررسی قفل می‌شوند. صحت اطلاعات را تأیید می‌کنید.</p>
              <div className="mt-6 flex items-center justify-between gap-3 border-t border-border pt-6">
                <Button variant="ghost" icon={<ArrowRight className="size-4" />} onClick={() => setStep(3)}>مرحله قبل</Button>
                <Button size="lg" icon={<Send className="size-4" />} disabled={app.missing.length > 0} loading={submit.isPending}
                  onClick={() => submit.mutate()} data-testid="onboarding-submit">ارسال برای بررسی</Button>
              </div>
            </Section>
          )}
        </div>
      </Card>
      <p className="mt-4 text-center text-xs text-muted">وضعیت فعلی: <Badge tone={DRIVER_STATUS[app.driver_status as keyof typeof DRIVER_STATUS]?.tone ?? "muted"}>{DRIVER_STATUS[app.driver_status as keyof typeof DRIVER_STATUS]?.label}</Badge></p>
    </div>
  );
}

function ResidenceStep({ form, setField, onBack, onNext, loading }: {
  form: Update; setField: <K extends keyof Update>(k: K, v: Update[K]) => void; onBack: () => void; onNext: () => void; loading: boolean;
}) {
  const { data: provinces = [] } = useProvinces();
  return (
    <Section title="محل سکونت">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="استان">
          <Select value={form.province ?? ""} onChange={e => setField("province", e.target.value || null)} data-testid="ob-province">
            <option value="">انتخاب کنید</option>{provinces.map(p => <option key={p} value={p}>{p}</option>)}
          </Select>
        </Field>
        <Field label="شهر"><CitySelect province={form.province ?? ""} value={form.city ?? ""} onChange={v => setField("city", v || null)} testId="ob-city" /></Field>
        <Field label="نشانی کامل" className="sm:col-span-2"><Input value={form.address ?? ""} onChange={e => setField("address", e.target.value)} data-testid="ob-address" /></Field>
        <Field label="کد پستی" hint="اختیاری — ۱۰ رقم"><Input className="ltr" inputMode="numeric" maxLength={10} value={form.postal_code ?? ""} onChange={e => setField("postal_code", latinDigits(e.target.value))} /></Field>
      </div>
      <Nav onBack={onBack} onNext={onNext} loading={loading} />
    </Section>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section><h2 className="mb-5 text-xl font-black">{title}</h2>{children}</section>;
}

function Nav({ onBack, onNext, loading }: { onBack?: () => void; onNext: () => void; loading: boolean }) {
  return (
    <div className="mt-8 flex items-center justify-between gap-3 border-t border-border pt-6">
      {onBack ? <Button type="button" variant="ghost" icon={<ArrowRight className="size-4" />} onClick={onBack}>مرحله قبل</Button> : <span />}
      <Button type="button" size="lg" loading={loading} onClick={onNext} data-testid="onboarding-next">ذخیره و ادامه<ArrowLeft className="size-4" /></Button>
    </div>
  );
}

function pickFields(app: Application): Update {
  return {
    first_name: app.first_name, last_name: app.last_name, national_code: app.national_code, birth_date: app.birth_date,
    mobile: app.mobile, province: app.province, city: app.city, address: app.address, postal_code: app.postal_code,
    vehicle_type: app.vehicle_type as Update["vehicle_type"], vehicle_model: app.vehicle_model, vehicle_color: app.vehicle_color,
    license_plate: app.license_plate, max_weight_kg: app.max_weight_kg, intercity: app.intercity, inspection_expiry: app.inspection_expiry,
  };
}
