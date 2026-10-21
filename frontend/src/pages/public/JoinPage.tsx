/** ثبت‌نام راننده با لینک دعوت سازمان (/join/:code) — پس از ساخت حساب، مستقیم وارد فرم مدارک می‌شود */
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Building2, IdCard, ShieldCheck, Truck, UserPlus } from "lucide-react";
import { api, errorMessage, tokenStore, unwrap } from "@/api/client";
import { BRAND } from "@/brand";
import { latinDigits } from "@/lib/format";
import { Logo, ThemeToggle } from "@/ui/brand";
import { Button, Field, Input, Spinner, buttonClass } from "@/ui/primitives";

export default function JoinPage() {
  const { code = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ full_name: "", mobile: "", username: "", password: "", email: "" });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm(f => ({ ...f, [k]: e.target.value }));

  useEffect(() => { document.title = `ثبت‌نام راننده — ${BRAND.nameFa}`; }, []);
  const invite = useQuery({
    queryKey: ["invite", code],
    queryFn: () => unwrap(api.GET("/driver-signup/{code}", { params: { path: { code } } })),
    retry: false,
  });
  const signup = useMutation({
    mutationFn: () => unwrap(api.POST("/driver-signup/{code}", {
      params: { path: { code } },
      body: { ...form, mobile: latinDigits(form.mobile), email: form.email || null },
    })),
    onSuccess: ({ access_token }) => {
      tokenStore.set(access_token);
      queryClient.clear();
      navigate("/app/onboarding", { replace: true });
    },
  });

  return (
    <div className="grid min-h-svh bg-bg text-text lg:grid-cols-2">
      <aside className="relative hidden overflow-hidden bg-linear-to-br from-brand to-brand-strong p-12 text-brand-ink lg:flex lg:flex-col">
        <Link to="/" className="w-fit rounded-xl bg-white/90 px-3 py-2 text-text"><Logo /></Link>
        <div className="mt-auto max-w-md">
          <h2 className="text-4xl font-black leading-tight">به ناوگان بپیوندید.</h2>
          <p className="mt-4 text-lg leading-8 opacity-90">بعد از ساخت حساب، مشخصات و مدارک خود را مرحله‌به‌مرحله بارگذاری می‌کنید. پس از تأیید سازمان، سفارش‌ها مستقیم در پنل شما ظاهر می‌شوند.</p>
          <ol className="mt-8 space-y-4">
            {[[UserPlus, "ساخت حساب"], [Truck, "نوع وسیله و مشخصات آن"], [IdCard, "مدارک هویتی، سلفی و ویدیو"], [ShieldCheck, "بررسی و تأیید توسط سازمان"]].map(([Icon, text], i) => {
              const I = Icon as typeof UserPlus;
              return <li key={i} className="flex items-center gap-3"><span className="grid size-10 place-items-center rounded-xl bg-white/15"><I className="size-5" /></span>{text as string}</li>;
            })}
          </ol>
        </div>
      </aside>

      <main className="flex flex-col px-4 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <Link to="/" className="lg:hidden"><Logo /></Link>
          <span className="lg:hidden" />
          <ThemeToggle />
        </div>
        <div className="mx-auto my-auto w-full max-w-md py-10">
          {invite.isLoading ? <div className="grid place-items-center py-20"><Spinner className="size-7" /></div> : invite.error ? (
            <div className="text-center" data-testid="invite-invalid">
              <div className="mx-auto grid size-14 place-items-center rounded-2xl bg-danger-soft text-danger"><ShieldCheck className="size-7" /></div>
              <h1 className="mt-5 text-2xl font-black">لینک دعوت معتبر نیست</h1>
              <p className="mt-3 leading-7 text-muted">{errorMessage(invite.error)}</p>
              <Link to="/" className={buttonClass("secondary", "md", "mt-6")}>صفحه اصلی</Link>
            </div>
          ) : (
            <>
              <div className="mb-6 flex items-center gap-3 rounded-2xl border border-border bg-surface p-4" data-testid="invite-org">
                <span className="grid size-11 place-items-center rounded-xl bg-brand-soft text-brand"><Building2 className="size-5" /></span>
                <div><div className="text-xs text-muted">دعوت به ناوگان</div><div className="font-bold">{invite.data!.organization_name}</div></div>
              </div>
              <h1 className="text-3xl font-black">ثبت‌نام راننده</h1>
              <p className="mt-2 text-muted">حساب کاربری بسازید؛ بلافاصله وارد فرم مدارک می‌شوید.</p>
              <form className="mt-8 space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); signup.mutate(); }} data-testid="join-form">
                <Field label="نام و نام خانوادگی"><Input required minLength={3} value={form.full_name} onChange={set("full_name")} data-testid="join-name" /></Field>
                <Field label="شماره همراه"><Input required className="ltr" inputMode="tel" pattern="[0۰][9۹][0-9۰-۹]{9}" placeholder="09xxxxxxxxx" value={form.mobile} onChange={set("mobile")} data-testid="join-mobile" /></Field>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="نام کاربری" hint="حروف انگلیسی"><Input required minLength={3} maxLength={20} className="ltr" autoComplete="username" value={form.username} onChange={set("username")} data-testid="join-username" /></Field>
                  <Field label="رمز عبور" hint="حداقل ۶ کاراکتر"><Input required minLength={6} type="password" className="ltr" autoComplete="new-password" value={form.password} onChange={set("password")} data-testid="join-password" /></Field>
                </div>
                <Field label="ایمیل" hint="اختیاری"><Input type="email" className="ltr" value={form.email} onChange={set("email")} /></Field>
                {signup.error && <p className="rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger" data-testid="join-error">{errorMessage(signup.error)}</p>}
                <Button type="submit" size="lg" className="w-full" loading={signup.isPending} data-testid="join-submit">ساخت حساب و ادامه<ArrowLeft className="size-4" /></Button>
                <p className="text-center text-sm text-muted">حساب دارید؟ <Link to="/app/login" className="font-medium text-brand">ورود</Link></p>
              </form>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
