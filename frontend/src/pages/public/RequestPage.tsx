/** فرم عمومی «درخواست دسترسی» سه‌مرحله‌ای + پیگیری وضعیت با کد پیگیری */
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Building2, Check, ClipboardCheck, Copy, Search, Settings2, UserRound } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { BRAND } from "@/brand";
import { useProvinces } from "@/hooks/data";
import { BUSINESS_TYPES, EMPLOYEE_RANGES, FEATURES, ORDER_VOLUMES, REFERRAL_SOURCES, REQUEST_STATUS } from "@/lib/labels";
import { faDate, latinDigits, normalizeDigits } from "@/lib/format";
import { Badge, Button, Field, Input, Select, Textarea, buttonClass, cn } from "@/ui/primitives";
import { CitySelect } from "@/components/CitySelect";
import { PublicFooter, PublicHeader } from "./chrome";

type Body = Schemas["OrganizationRequestCreate"];
type FormState = Record<
  "name" | "legal_name" | "business_type" | "national_id" | "economic_code" | "registration_number" | "province" | "city" | "address" |
  "postal_code" | "phone" | "website" | "employee_count" | "monthly_order_volume" | "warehouse_count" | "fleet_size" |
  "contact_name" | "contact_mobile" | "contact_email" | "notes" | "referral_source" | "referral_detail" | "company_fax", string
> & { requested_features: string[] };

const EMPTY: FormState = {
  name: "", legal_name: "", business_type: "", national_id: "", economic_code: "", registration_number: "", province: "", city: "",
  address: "", postal_code: "", phone: "", website: "", employee_count: "", monthly_order_volume: "", warehouse_count: "", fleet_size: "",
  contact_name: "", contact_mobile: "", contact_email: "", notes: "", referral_source: "", referral_detail: "", company_fax: "", requested_features: ["transport", "warehouse"],
};
const DIGITS = ["national_id", "economic_code", "registration_number", "postal_code", "phone", "contact_mobile"] as const;
const STEPS = [
  { title: "کسب‌وکار", hint: "هویت و نشانی", icon: Building2 },
  { title: "عملیات", hint: "ابعاد و نیازها", icon: Settings2 },
  { title: "تماس", hint: "مسئول پیگیری", icon: UserRound },
];
const DRAFT_KEY = "request-draft";

export default function RequestPage() {
  const { hash } = useLocation();
  const { data: provinces = [] } = useProvinces();
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<FormState>(() => {
    try { return { ...EMPTY, ...JSON.parse(sessionStorage.getItem(DRAFT_KEY) ?? "{}") }; } catch { return EMPTY; }
  });
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Schemas["OrganizationRequestSubmitted"] | null>(null);
  const top = useRef<HTMLDivElement>(null);

  useEffect(() => { document.title = `درخواست دسترسی — ${BRAND.name}`; }, []);
  useEffect(() => {
    try { sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ ...form, company_fax: "" })); } catch { /* حالت خصوصی */ }
  }, [form]);
  useEffect(() => { if (hash === "#status") document.getElementById("status")?.scrollIntoView(); }, [hash]);

  const set = (k: keyof FormState) => (e: { target: { value: string } }) => setForm(f => ({ ...f, [k]: e.target.value }));
  const pick = (k: keyof FormState, v: string) => setForm(f => ({ ...f, [k]: v }));
  const toggleFeature = (key: string) => setForm(f => ({
    ...f, requested_features: f.requested_features.includes(key) ? f.requested_features.filter(x => x !== key) : [...f.requested_features, key],
  }));

  const submit = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { ...form };
      for (const k of DIGITS) body[k] = normalizeDigits(form[k].trim());
      if (!form.referral_source) body.referral_detail = null;
      for (const [k, v] of Object.entries(body)) if (typeof v === "string" && v.trim() === "") body[k] = null;
      body.warehouse_count = form.warehouse_count === "" ? null : Number(normalizeDigits(form.warehouse_count));
      body.fleet_size = form.fleet_size === "" ? null : Number(normalizeDigits(form.fleet_size));
      return unwrap(api.POST("/organization-requests", { body: body as unknown as Body }));
    },
    onSuccess: result => { setDone(result); try { sessionStorage.removeItem(DRAFT_KEY); } catch { /* */ } top.current?.scrollIntoView(); },
    onError: e => setError(errorMessage(e)),
  });

  function next(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (step === 0 && (!form.business_type)) return setError("حوزه فعالیت را انتخاب کنید.");
    if (step === 1) {
      if (!form.employee_count || !form.monthly_order_volume) return setError("تعداد کارکنان و حجم سفارش ماهانه را انتخاب کنید.");
      if (form.requested_features.length === 0) return setError("حداقل یک بخش مورد نیاز را انتخاب کنید.");
    }
    if (step === 2 && form.referral_source === "other" && form.referral_detail.trim().length < 2) return setError("لطفاً بنویسید از کجا با ما آشنا شدید.");
    if (step < 2) { setStep(step + 1); top.current?.scrollIntoView({ behavior: "smooth" }); }
    else submit.mutate();
  }

  return (
    <div className="min-h-svh bg-bg text-text">
      <PublicHeader />
      <main className="mx-auto max-w-7xl px-4 pb-24 pt-28 sm:px-6" ref={top}>
        <div className="grid gap-10 lg:grid-cols-[minmax(0,4fr)_minmax(0,8fr)]">
          <aside className="lg:sticky lg:top-28 lg:h-fit">
            <div className="eyebrow mb-4">درخواست دسترسی</div>
            <h1 className="text-3xl font-black leading-tight tracking-tight sm:text-4xl">فضای اختصاصی سازمانتان را درخواست کنید.</h1>
            <p className="mt-4 leading-8 text-text-2">پر کردن فرم حدود ۳ دقیقه طول می‌کشد. پس از بررسی، سازمان شما ساخته و اطلاعات ورود ادمین برایتان ارسال می‌شود.</p>
            {!done && (
              <ol className="mt-8 space-y-1" data-testid="request-stepper">
                {STEPS.map((s, i) => (
                  <li key={s.title} className={cn("flex items-center gap-3 rounded-2xl p-3 transition", i === step && "bg-surface shadow-[var(--shadow)]")}>
                    <span className={cn("grid size-10 place-items-center rounded-xl transition",
                      i < step ? "bg-brand text-brand-ink" : i === step ? "bg-brand-soft text-brand" : "bg-surface-2 text-muted")}>
                      {i < step ? <Check className="size-5" /> : <s.icon className="size-5" />}
                    </span>
                    <div><div className={cn("font-bold", i > step && "text-muted")}>{s.title}</div><div className="text-xs text-muted">{s.hint}</div></div>
                    <span className="ms-auto font-mono text-xs text-muted">0{i + 1}</span>
                  </li>
                ))}
              </ol>
            )}
          </aside>

          <div>
            {done ? <Success result={done} onAgain={() => { setDone(null); setForm(EMPTY); setStep(0); }} /> : (
              <form id="request-form" onSubmit={next} className="card p-6 sm:p-8" data-testid="request-step" data-step={step}>
                <div className="mb-6 h-1 overflow-hidden rounded-full bg-surface-2">
                  <div className="h-full rounded-full bg-linear-to-l from-brand to-accent transition-all duration-500" style={{ width: `${((step + 1) / 3) * 100}%` }} />
                </div>
                {/* تله ربات — برای انسان دیده نمی‌شود */}
                <input type="text" name="company_fax" tabIndex={-1} autoComplete="off" value={form.company_fax} onChange={set("company_fax")} className="sr-only" aria-hidden="true" />

                <div key={step} className="animate-rise">
                  {step === 0 && (
                    <div className="grid gap-5 sm:grid-cols-2">
                      <Field label="نام تجاری *"><Input required minLength={2} maxLength={200} value={form.name} onChange={set("name")} placeholder="مثلاً فروشگاه نمونه" data-testid="req-name" /></Field>
                      <Field label="نام ثبتی شرکت *"><Input required minLength={2} maxLength={200} value={form.legal_name} onChange={set("legal_name")} data-testid="req-legal-name" /></Field>
                      <Choice label="حوزه فعالیت *" className="sm:col-span-2" options={BUSINESS_TYPES} value={form.business_type} onPick={v => pick("business_type", v)} testId="req-business" />
                      <Field label="شناسه ملی *" hint="۱۱ رقم"><Input className="ltr" required inputMode="numeric" pattern="[0-9۰-۹]{11}" value={form.national_id} onChange={set("national_id")} data-testid="req-national-id" /></Field>
                      <Field label="کد اقتصادی" hint="اختیاری — ۱۱ تا ۱۴ رقم"><Input className="ltr" inputMode="numeric" pattern="[0-9۰-۹]{11,14}" value={form.economic_code} onChange={set("economic_code")} /></Field>
                      <Field label="استان *">
                        <Select required value={form.province} onChange={set("province")} data-testid="req-province">
                          <option value="">انتخاب کنید</option>{provinces.map(p => <option key={p} value={p}>{p}</option>)}
                        </Select>
                      </Field>
                      <Field label="شهر *"><CitySelect required province={form.province} value={form.city} onChange={v => pick("city", v)} testId="req-city" /></Field>
                      <Field label="نشانی *" className="sm:col-span-2"><Input required minLength={10} maxLength={500} value={form.address} onChange={set("address")} data-testid="req-address" /></Field>
                      <Field label="کد پستی" hint="اختیاری — ۱۰ رقم"><Input className="ltr" inputMode="numeric" pattern="[0-9۰-۹]{10}" value={form.postal_code} onChange={set("postal_code")} /></Field>
                      <Field label="وب‌سایت" hint="اختیاری"><Input className="ltr" value={form.website} onChange={set("website")} placeholder="example.ir" /></Field>
                    </div>
                  )}
                  {step === 1 && (
                    <div className="grid gap-6">
                      <Choice label="تعداد کارکنان *" options={EMPLOYEE_RANGES} value={form.employee_count} onPick={v => pick("employee_count", v)} testId="req-employees" />
                      <Choice label="حجم سفارش ماهانه *" options={ORDER_VOLUMES} value={form.monthly_order_volume} onPick={v => pick("monthly_order_volume", v)} testId="req-volume" />
                      <div className="grid gap-5 sm:grid-cols-2">
                        <Field label="تعداد انبار" hint="اختیاری"><Input type="number" min={0} max={10000} value={form.warehouse_count} onChange={set("warehouse_count")} /></Field>
                        <Field label="تعداد خودرو / راننده" hint="اختیاری"><Input type="number" min={0} max={100000} value={form.fleet_size} onChange={set("fleet_size")} /></Field>
                      </div>
                      <div>
                        <div className="mb-2 text-sm font-medium text-text-2">بخش‌های مورد نیاز *</div>
                        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                          {Object.entries(FEATURES).map(([key, label]) => {
                            const on = form.requested_features.includes(key);
                            return (
                              <button type="button" key={key} onClick={() => toggleFeature(key)} data-testid="req-feature" aria-pressed={on}
                                className={cn("flex items-center gap-2 rounded-xl border px-3 py-3 text-sm transition",
                                  on ? "border-brand bg-brand-soft font-semibold text-brand-strong" : "border-border bg-surface text-text-2 hover:border-border-strong")}>
                                <span className={cn("grid size-5 place-items-center rounded-md border transition", on ? "border-brand bg-brand text-brand-ink" : "border-border-strong")}>{on && <Check className="size-3.5" strokeWidth={3} />}</span>
                                {label}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                      <Field label="توضیحات" hint="اختیاری — نیاز خاص یا سؤالی که دارید"><Textarea rows={3} maxLength={2000} value={form.notes} onChange={set("notes")} /></Field>
                    </div>
                  )}
                  {step === 2 && (
                    <div className="grid gap-5 sm:grid-cols-2">
                      <Field label="نام و نام خانوادگی مسئول *" className="sm:col-span-2"><Input required minLength={2} maxLength={100} value={form.contact_name} onChange={set("contact_name")} data-testid="req-contact-name" /></Field>
                      <Field label="شماره همراه *" hint="مثل ۰۹۱۲۱۲۳۴۵۶۷"><Input className="ltr" required inputMode="tel" pattern="[0۰][9۹][0-9۰-۹]{9}" value={form.contact_mobile} onChange={set("contact_mobile")} data-testid="req-mobile" /></Field>
                      <Field label="ایمیل *"><Input className="ltr" type="email" required value={form.contact_email} onChange={set("contact_email")} data-testid="req-email" /></Field>
                      <Field label="تلفن ثابت" hint="اختیاری"><Input className="ltr" inputMode="tel" value={form.phone} onChange={set("phone")} /></Field>
                      <div className="sm:col-span-2">
                        <Choice label={<>چطور با ما آشنا شدید؟ <span className="text-xs font-normal text-muted">(اختیاری — با کلیک دوباره، انتخاب برداشته می‌شود)</span></>}
                          options={REFERRAL_SOURCES} value={form.referral_source} testId="req-referral" clearable
                          onPick={v => setForm(f => ({ ...f, referral_source: v, referral_detail: v === f.referral_source ? f.referral_detail : "" }))} />
                        {(form.referral_source === "other" || form.referral_source === "referral") && (
                          <div className="mt-3 animate-rise">
                            <Field label={form.referral_source === "other" ? "از کجا با ما آشنا شدید؟ *" : "معرف شما"} hint={form.referral_source === "other" ? undefined : "اختیاری — نام شخص یا شرکت معرف"}>
                              <Input required={form.referral_source === "other"} minLength={form.referral_source === "other" ? 2 : undefined} maxLength={200}
                                value={form.referral_detail} onChange={set("referral_detail")} data-testid="req-referral-detail"
                                placeholder={form.referral_source === "other" ? "مثلاً پادکست، وبلاگ، آپارات، …" : "مثلاً شرکت نمونه"} />
                            </Field>
                          </div>
                        )}
                      </div>
                      <div className="rounded-2xl border border-border bg-surface-2 p-4 text-sm sm:col-span-2">
                        <div className="mb-2 font-bold">خلاصه</div>
                        <div className="grid gap-1.5 text-text-2 sm:grid-cols-2">
                          <span>{form.name || "—"} · {BUSINESS_TYPES[form.business_type] ?? "—"}</span>
                          <span>{form.province} / {form.city}</span>
                          <span>سفارش ماهانه: {ORDER_VOLUMES[form.monthly_order_volume] ?? "—"}</span>
                          <span>{form.requested_features.map(f => FEATURES[f]).join("، ")}</span>
                        </div>
                      </div>
                      <p className="text-xs leading-6 text-muted sm:col-span-2" data-testid="req-terms">
                        با ثبت درخواست، <Link to="/terms" target="_blank" className="font-medium text-brand hover:underline">قوانین و مقررات</Link> استفاده از {BRAND.nameFa} را می‌پذیرید.
                      </p>
                    </div>
                  )}
                </div>

                {error && <p className="mt-6 rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger" data-testid="request-error">{error}</p>}
                <div className="mt-8 flex items-center justify-between gap-3 border-t border-border pt-6">
                  {step > 0 ? <Button type="button" variant="ghost" icon={<ArrowRight className="size-4" />} onClick={() => { setError(null); setStep(step - 1); }}>مرحله قبل</Button> : <span />}
                  <Button type="submit" size="lg" loading={submit.isPending} data-testid={step < 2 ? "request-next" : "request-submit"}>
                    {step < 2 ? <>مرحله بعد<ArrowLeft className="size-4" /></> : <>ثبت درخواست<ClipboardCheck className="size-4" /></>}
                  </Button>
                </div>
              </form>
            )}
            <StatusLookup />
          </div>
        </div>
      </main>
      <PublicFooter />
    </div>
  );
}

function Choice({ label, options, value, onPick, className, testId, clearable = false }: {
  label: ReactNode; options: Record<string, string>; value: string; onPick: (v: string) => void; className?: string; testId?: string;
  /** کلیک دوباره روی گزینه انتخاب‌شده، انتخاب را برمی‌دارد (برای سؤال‌های اختیاری) */
  clearable?: boolean;
}) {
  return (
    <div className={className} role="radiogroup" data-testid={testId}>
      <div className="mb-2 text-sm font-medium text-text-2">{label}</div>
      <div className="flex flex-wrap gap-2">
        {Object.entries(options).map(([k, v]) => (
          <button type="button" key={k} role="radio" aria-checked={value === k} data-value={k} onClick={() => onPick(clearable && value === k ? "" : k)}
            className={cn("rounded-xl border px-3.5 py-2 text-sm transition",
              value === k ? "border-brand bg-brand text-brand-ink" : "border-border bg-surface text-text-2 hover:border-border-strong hover:text-text")}>
            {v}
          </button>
        ))}
      </div>
    </div>
  );
}

function Success({ result, onAgain }: { result: Schemas["OrganizationRequestSubmitted"]; onAgain: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="card overflow-hidden" data-testid="request-success">
      <div className="bg-linear-to-l from-brand to-brand-strong p-8 text-brand-ink">
        <div className="grid size-14 animate-rise place-items-center rounded-2xl bg-white/20"><Check className="size-7" strokeWidth={3} /></div>
        <h2 className="mt-5 text-2xl font-black">درخواست شما ثبت شد</h2>
        <p className="mt-2 opacity-90">{result.message}</p>
      </div>
      <div className="p-8">
        <div className="text-sm text-muted">کد پیگیری — آن را نگه دارید</div>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <span className="rounded-xl border border-dashed border-border-strong bg-surface-2 px-4 py-2 font-mono text-2xl font-bold tracking-wider ltr" data-testid="request-tracking-code">{result.tracking_code}</span>
          <Button variant="secondary" icon={copied ? <Check className="size-4" /> : <Copy className="size-4" />}
            onClick={() => navigator.clipboard?.writeText(result.tracking_code).then(() => setCopied(true))}>{copied ? "کپی شد" : "کپی"}</Button>
        </div>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link to="/" className={buttonClass("secondary")}>بازگشت به صفحه اصلی</Link>
          <Button variant="ghost" onClick={onAgain}>ثبت درخواست دیگر</Button>
        </div>
      </div>
    </div>
  );
}

function StatusLookup() {
  const [code, setCode] = useState("");
  const lookup = useMutation({
    mutationFn: (c: string) => unwrap(api.GET("/organization-requests/status/{tracking_code}", { params: { path: { tracking_code: c } } })),
  });
  return (
    <section id="status" className="card mt-8 p-6 sm:p-8">
      <h2 className="flex items-center gap-2 text-lg font-bold"><Search className="size-5 text-brand" />پیگیری درخواست</h2>
      <p className="mt-1 text-sm text-muted">کد پیگیری‌ای را که پس از ثبت گرفتید وارد کنید.</p>
      <form className="mt-5 flex flex-wrap gap-3" onSubmit={e => { e.preventDefault(); if (code.trim()) lookup.mutate(latinDigits(code.trim()).toUpperCase()); }}>
        <Input className="ltr max-w-xs flex-1 font-mono" placeholder="REQ-..." value={code} onChange={e => setCode(e.target.value)} data-testid="status-code" />
        <Button type="submit" variant="soft" loading={lookup.isPending}>پیگیری</Button>
      </form>
      {lookup.error && <p className="mt-4 text-sm text-danger" data-testid="status-error">{errorMessage(lookup.error)}</p>}
      {lookup.data && (
        <div className="mt-5 grid animate-rise gap-3 rounded-2xl border border-border bg-surface-2 p-5 text-sm sm:grid-cols-2" data-testid="status-result">
          <div><span className="text-muted">سازمان: </span><b>{lookup.data.name}</b></div>
          <div><span className="text-muted">وضعیت: </span><Badge tone={REQUEST_STATUS[lookup.data.status]?.tone ?? "muted"} dot>{REQUEST_STATUS[lookup.data.status]?.label ?? lookup.data.status}</Badge></div>
          <div><span className="text-muted">تاریخ ثبت: </span>{faDate(lookup.data.created_at)}</div>
          {lookup.data.reviewed_at && <div><span className="text-muted">تاریخ بررسی: </span>{faDate(lookup.data.reviewed_at)}</div>}
          {lookup.data.rejection_reason && <div className="text-danger sm:col-span-2">دلیل: {lookup.data.rejection_reason}</div>}
        </div>
      )}
    </section>
  );
}
