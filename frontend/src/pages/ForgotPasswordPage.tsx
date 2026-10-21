/** بازیابی رمز توسط خود کاربر: ۱) نام کاربری، موبایل یا ایمیل ← کد ۶ رقمی  ۲) کد + رمز جدید */
import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, CheckCircle2, KeyRound, LockKeyhole, UserRound } from "lucide-react";
import { api, errorMessage, unwrap } from "@/api/client";
import { BRAND } from "@/brand";
import { normalizeDigits } from "@/lib/format";
import { Button, Field, Input, buttonClass } from "@/ui/primitives";
import { AuthLayout } from "./LoginPage";

const RESEND_SECONDS = 60;

export default function ForgotPasswordPage() {
  const location = useLocation();
  const [identifier, setIdentifier] = useState<string>((location.state as { identifier?: string } | null)?.identifier ?? "");
  const [step, setStep] = useState<"request" | "confirm" | "done">("request");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [wait, setWait] = useState(0);
  const { data: channels } = useQuery({ queryKey: ["password-reset-channels"], queryFn: () => unwrap(api.GET("/auth/password-reset")) });

  useEffect(() => { document.title = `بازیابی رمز عبور — ${BRAND.nameFa}`; }, []);
  useEffect(() => {
    if (wait <= 0) return;
    const t = window.setTimeout(() => setWait(w => w - 1), 1000);
    return () => window.clearTimeout(t);
  }, [wait]);

  const send = useMutation({
    mutationFn: () => unwrap(api.POST("/auth/password-reset/request", { body: { identifier: normalizeDigits(identifier.trim()) } })),
    onSuccess: r => { setError(null); setNotice(r.message); setStep("confirm"); setWait(RESEND_SECONDS); },
    onError: e => setError(errorMessage(e)),
  });
  const confirm = useMutation({
    mutationFn: () => unwrap(api.POST("/auth/password-reset/confirm", {
      body: { identifier: normalizeDigits(identifier.trim()), code: normalizeDigits(code.trim()), new_password: password },
    })),
    onSuccess: () => { setError(null); setStep("done"); },
    onError: e => setError(errorMessage(e)),
  });

  function submitConfirm(e: FormEvent) {
    e.preventDefault();
    if (password !== repeat) { setError("رمز جدید و تکرار آن یکسان نیستند."); return; }
    confirm.mutate();
  }

  const available = !!(channels?.sms || channels?.email);
  const errorBox = error && <div className="rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger" data-testid="reset-error">{error}</div>;

  return (
    <AuthLayout>
      <div data-testid="forgot-password-page">
        <h1 className="text-3xl font-extrabold tracking-tight">بازیابی رمز عبور</h1>

        {channels && !available ? (
          <div className="mt-6 space-y-4 text-sm leading-7 text-text-2" data-testid="reset-unavailable">
            <p>بازیابی خودکار رمز در حال حاضر فعال نیست. از ادمین سازمانتان بخواهید رمز شما را بازنشانی کند.</p>
            <p>ادمین سازمان هستید؟ با پشتیبانی {BRAND.nameFa} تماس بگیرید: <a href={`tel:${BRAND.phone}`} className="font-semibold text-brand">{BRAND.phoneDisplay}</a></p>
            <Link to="/app/login" className={buttonClass("secondary")}><ArrowRight className="size-4" />بازگشت به ورود</Link>
          </div>
        ) : step === "request" ? (
          <>
            <p className="mt-2 text-sm text-muted">نام کاربری، شماره موبایل یا ایمیل حسابتان را وارد کنید تا کد تأیید {channels?.sms ? "پیامک" : "ارسال"} شود.</p>
            <form onSubmit={e => { e.preventDefault(); send.mutate(); }} className="mt-8 space-y-5">
              <Field label="نام کاربری، موبایل یا ایمیل">
                <div className="relative">
                  <UserRound className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" />
                  <Input className="ltr pr-10" value={identifier} autoFocus required minLength={3} autoComplete="username"
                    onChange={e => setIdentifier(e.target.value)} data-testid="reset-identifier" />
                </div>
              </Field>
              {errorBox}
              <Button type="submit" size="lg" className="w-full" loading={send.isPending} data-testid="reset-send">ارسال کد <ArrowLeft className="size-4" /></Button>
            </form>
          </>
        ) : step === "confirm" ? (
          <>
            {notice && <p className="mt-3 rounded-xl bg-brand-soft px-4 py-3 text-sm leading-7 text-brand-strong" data-testid="reset-notice">{notice}</p>}
            <form onSubmit={submitConfirm} className="mt-6 space-y-5">
              <Field label="کد تأیید">
                <div className="relative">
                  <KeyRound className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" />
                  <Input className="ltr pr-10 tracking-[0.3em]" value={code} autoFocus required inputMode="numeric" autoComplete="one-time-code"
                    maxLength={12} onChange={e => setCode(e.target.value)} data-testid="reset-code" />
                </div>
              </Field>
              <Field label="رمز عبور جدید" hint="دست‌کم ۶ کاراکتر">
                <div className="relative">
                  <LockKeyhole className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" />
                  <Input type="password" className="ltr pr-10" value={password} required minLength={6} maxLength={72} autoComplete="new-password"
                    onChange={e => setPassword(e.target.value)} data-testid="reset-password" />
                </div>
              </Field>
              <Field label="تکرار رمز عبور جدید">
                <Input type="password" className="ltr" value={repeat} required minLength={6} maxLength={72} autoComplete="new-password"
                  onChange={e => setRepeat(e.target.value)} data-testid="reset-repeat" />
              </Field>
              {errorBox}
              <Button type="submit" size="lg" className="w-full" loading={confirm.isPending} data-testid="reset-confirm">تغییر رمز <ArrowLeft className="size-4" /></Button>
              <div className="flex items-center justify-between text-sm">
                <button type="button" className="text-text-2 hover:text-text" onClick={() => { setStep("request"); setError(null); }}>تغییر نام کاربری</button>
                <button type="button" disabled={wait > 0 || send.isPending} onClick={() => send.mutate()}
                  className="font-medium text-brand disabled:text-muted">
                  {wait > 0 ? `ارسال دوباره تا ${wait.toLocaleString("fa-IR")} ثانیه` : "ارسال دوباره کد"}
                </button>
              </div>
            </form>
          </>
        ) : (
          <div className="mt-6 space-y-5" data-testid="reset-done">
            <div className="flex items-start gap-3 rounded-xl border border-success/30 bg-success-soft px-4 py-3 text-sm leading-7 text-success">
              <CheckCircle2 className="mt-1 size-4 shrink-0" />رمز عبور تغییر کرد. از همه دستگاه‌های دیگر خارج شدید؛ اکنون با رمز جدید وارد شوید.
            </div>
            <Link to="/app/login" className={buttonClass("primary", "lg", "w-full")}>ورود به پنل <ArrowLeft className="size-4" /></Link>
          </div>
        )}

        {step !== "done" && available && (
          <p className="mt-8 text-center text-sm text-muted">رمز را به خاطر آوردید؟ <Link to="/app/login" className="font-semibold text-brand hover:underline">ورود</Link></p>
        )}
      </div>
    </AuthLayout>
  );
}
