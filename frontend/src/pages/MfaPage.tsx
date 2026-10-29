/**
 * ورود دومرحله‌ای (TOTP): ساخت کد QR، فعال‌سازی با اولین کد و خاموش‌کردن.
 * برای کارکنان پلتفرم در سرور اصلی اجباری است و تا فعال نشود پنل باز نمی‌شود (مثل تغییر اجباری رمز).
 */
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, LogOut, ShieldCheck } from "lucide-react";
import { authFetch, errorMessage } from "@/api/client";
import { homePathFor, useAuth } from "@/auth/AuthContext";
import { Logo, ThemeToggle } from "@/ui/brand";
import { Button, Card, Field, Input } from "@/ui/primitives";

type Setup = { secret: string; uri: string; qr: string };

async function call<T>(url: string, method = "GET", body?: unknown): Promise<T> {
  const response = await authFetch(url, {
    method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(errorMessage(await response.json().catch(() => ({}))));
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export default function MfaPage() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["mfa-status"], queryFn: () => call<{ enabled: boolean; required: boolean }>("/auth/mfa") });
  const [setup, setSetup] = useState<Setup | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!me) return null;
  const forced = me.mfa_setup_required;

  async function run(action: () => Promise<void>) {
    setError(null);
    setBusy(true);
    try { await action(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  const start = () => run(async () => setSetup(await call<Setup>("/auth/mfa/setup", "POST")));
  const enable = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await call("/auth/mfa/enable", "POST", { code });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      await status.refetch();
      setSetup(null);
      setCode("");
      if (forced) navigate(homePathFor(me), { replace: true });
    });
  };
  const disable = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await call("/auth/mfa/disable", "POST", { code, password });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      await status.refetch();
      setCode("");
      setPassword("");
    });
  };

  return (
    <div className="flex min-h-dvh flex-col px-6 py-6 sm:px-12">
      <div className="flex items-center justify-between">
        <Link to="/"><Logo /></Link>
        <ThemeToggle />
      </div>
      <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center py-12">
        <Card className="p-6 sm:p-8" data-testid="mfa-page">
          <div className="grid size-12 place-items-center rounded-2xl bg-brand-soft text-brand"><ShieldCheck className="size-6" /></div>
          <h1 className="mt-4 text-2xl font-extrabold tracking-tight">ورود دومرحله‌ای</h1>
          <p className="mt-2 text-sm leading-7 text-muted">
            {forced ? "برای کارکنان پلتفرم که به همه سازمان‌ها دسترسی دارند، ورود دومرحله‌ای اجباری است. " : ""}
            بعد از رمز عبور، یک کد شش‌رقمی از برنامه‌ای مثل Google Authenticator یا Microsoft Authenticator روی گوشی‌تان هم خواسته می‌شود؛
            حتی اگر رمز لو برود، بدون گوشی کسی وارد نمی‌شود.
          </p>

          {status.data?.enabled ? (
            <div className="mt-6 space-y-4">
              <p className="rounded-xl bg-success-soft px-4 py-3 text-sm font-medium text-success" data-testid="mfa-enabled">ورود دومرحله‌ای فعال است.</p>
              {!status.data.required && (
                <form onSubmit={disable} className="space-y-4">
                  <p className="text-sm text-muted">برای خاموش‌کردن، رمز عبور و کد فعلی برنامه را وارد کنید.</p>
                  <Field label="رمز عبور"><Input type="password" className="ltr" value={password} required autoComplete="current-password" onChange={e => setPassword(e.target.value)} /></Field>
                  <Field label="کد شش‌رقمی"><Input inputMode="numeric" className="ltr" value={code} required maxLength={6} autoComplete="one-time-code" onChange={e => setCode(e.target.value)} /></Field>
                  <Button type="submit" variant="secondary" loading={busy}>خاموش‌کردن ورود دومرحله‌ای</Button>
                </form>
              )}
            </div>
          ) : setup ? (
            <form onSubmit={enable} className="mt-6 space-y-4">
              <p className="text-sm text-text-2">۱. این کد را با برنامه احراز هویت اسکن کنید:</p>
              <img src={setup.qr} alt="کد QR ورود دومرحله‌ای" className="mx-auto size-48 rounded-xl bg-white p-2" data-testid="mfa-qr" />
              <p className="text-xs text-muted">اگر اسکن ممکن نیست، این کلید را دستی وارد کنید:</p>
              <code className="block break-all rounded-lg bg-surface-2 px-3 py-2 text-center font-mono text-sm ltr" data-testid="mfa-secret">{setup.secret}</code>
              <Field label="۲. کد شش‌رقمی که برنامه نشان می‌دهد">
                <Input inputMode="numeric" className="ltr" value={code} required maxLength={6} autoFocus autoComplete="one-time-code" onChange={e => setCode(e.target.value)} data-testid="mfa-code" />
              </Field>
              <Button type="submit" className="w-full" loading={busy} data-testid="mfa-enable">فعال‌سازی</Button>
            </form>
          ) : (
            <Button className="mt-6 w-full" loading={busy || status.isLoading} onClick={start} data-testid="mfa-start">راه‌اندازی با گوشی</Button>
          )}
          {error && <div className="mt-4 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">{error}</div>}
        </Card>
        {forced
          ? <Button variant="ghost" size="sm" className="mx-auto mt-4" icon={<LogOut className="size-4" />} onClick={logout}>خروج</Button>
          : <Link to={homePathFor(me)} className="mx-auto mt-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-text"><ArrowRight className="size-4" />بازگشت به پنل</Link>}
      </div>
    </div>
  );
}
