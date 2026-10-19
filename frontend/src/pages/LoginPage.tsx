import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ArrowLeft, LockKeyhole, UserRound } from "lucide-react";
import { homePathFor, useAuth } from "@/auth/AuthContext";
import { errorMessage } from "@/api/client";
import { BRAND } from "@/brand";
import { Logo, ThemeToggle } from "@/ui/brand";
import { Button, Field, Input } from "@/ui/primitives";

/** تصویر کوچک مسیر: انبار ← مسیر خط‌چین متحرک ← مقصد */
function RouteIllustration() {
  return (
    <svg viewBox="0 0 400 260" className="w-full max-w-md" aria-hidden="true">
      <defs>
        <linearGradient id="road" x1="0" x2="1"><stop offset="0" stopColor="white" stopOpacity=".15" /><stop offset="1" stopColor="white" stopOpacity=".4" /></linearGradient>
      </defs>
      {[40, 110, 180].map(y => <rect key={y} x="20" y={y} width="360" height="1" fill="white" opacity=".08" />)}
      {[80, 200, 320].map(x => <rect key={x} x={x} y="10" width="1" height="240" fill="white" opacity=".08" />)}
      <path id="route" d="M60 200 C 120 200, 120 120, 200 120 S 300 50, 340 60" fill="none" stroke="url(#road)" strokeWidth="3" strokeDasharray="8 8">
        <animate attributeName="stroke-dashoffset" from="64" to="0" dur="2s" repeatCount="indefinite" />
      </path>
      <rect x="40" y="185" width="42" height="30" rx="6" fill="white" opacity=".9" />
      <rect x="46" y="178" width="30" height="8" rx="3" fill="var(--accent)" />
      <circle cx="340" cy="60" r="10" fill="var(--accent)" />
      <circle cx="340" cy="60" r="18" fill="none" stroke="var(--accent)" opacity=".5">
        <animate attributeName="r" from="10" to="26" dur="1.8s" repeatCount="indefinite" />
        <animate attributeName="opacity" from=".6" to="0" dur="1.8s" repeatCount="indefinite" />
      </circle>
      <g>
        <rect x="-14" y="-9" width="28" height="18" rx="4" fill="white" />
        <rect x="4" y="-7" width="9" height="8" rx="2" fill="var(--brand)" />
        <animateMotion dur="6s" repeatCount="indefinite" rotate="auto" path="M60 200 C 120 200, 120 120, 200 120 S 300 50, 340 60" />
      </g>
    </svg>
  );
}

export default function LoginPage() {
  const { me, login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (me) return <Navigate to={homePathFor(me)} replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const user = await login(username.trim(), password);
      navigate(homePathFor(user), { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="flex flex-col px-6 py-6 sm:px-12">
        <div className="flex items-center justify-between">
          <Link to="/"><Logo /></Link>
          <ThemeToggle />
        </div>
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-12">
          <h1 className="text-3xl font-extrabold tracking-tight">ورود به پنل</h1>
          <p className="mt-2 text-sm text-muted">با نام کاربری و رمزی که مدیر سازمان برایتان ساخته وارد شوید.</p>
          <form onSubmit={onSubmit} className="mt-8 space-y-5" autoComplete="on">
            <Field label="نام کاربری">
              <div className="relative">
                <UserRound className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" />
                <Input id="username" className="ltr pr-10" value={username} autoFocus required autoComplete="username" onChange={e => setUsername(e.target.value)} />
              </div>
            </Field>
            <Field label="رمز عبور">
              <div className="relative">
                <LockKeyhole className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted" />
                <Input id="password" type="password" className="ltr pr-10" value={password} required autoComplete="current-password" onChange={e => setPassword(e.target.value)} />
              </div>
            </Field>
            {error && <div className="rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger" data-testid="login-error">{error}</div>}
            <Button type="submit" size="lg" className="w-full" loading={submitting}>ورود <ArrowLeft className="size-4" /></Button>
          </form>
          <p className="mt-8 text-center text-sm text-muted">
            هنوز سازمانتان در {BRAND.name} نیست؟ <Link to="/request" className="font-semibold text-brand hover:underline">درخواست استفاده بدهید</Link>
          </p>
        </div>
      </div>
      <div className="relative hidden overflow-hidden bg-[linear-gradient(150deg,#0b9c96_0%,#07605c_55%,#0a2a29_100%)] lg:flex lg:flex-col lg:items-center lg:justify-center lg:p-12">
        <div className="absolute inset-0 opacity-30 [background:radial-gradient(circle_at_20%_20%,#e8a417_0,transparent_35%)]" />
        <RouteIllustration />
        <div className="relative mt-10 max-w-md text-center text-white">
          <div className="text-2xl font-extrabold leading-relaxed">هر مرسوله، یک پرونده‌ی کامل.</div>
          <p className="mt-3 text-white/75">سفارش، ناوگان، دفتر گردش کالا و پیگیری لحظه‌ای — همه در یک سامانه، جدا برای هر سازمان.</p>
        </div>
      </div>
    </div>
  );
}
