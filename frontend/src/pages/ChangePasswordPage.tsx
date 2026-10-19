/** تغییر اجباری رمز بعد از ورود با رمز موقتی که ادمین سازمان ساخته — تا عوض نشود، پنل باز نمی‌شود. */
import { Link, Navigate, useNavigate } from "react-router-dom";
import { KeyRound, LogOut } from "lucide-react";
import { homePathFor, useAuth } from "@/auth/AuthContext";
import { PasswordChangeForm } from "@/components/PasswordChangeForm";
import { Logo, ThemeToggle } from "@/ui/brand";
import { Button, Card } from "@/ui/primitives";

export default function ChangePasswordPage() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  if (!me) return null;
  if (!me.must_change_password) return <Navigate to={homePathFor(me)} replace />;

  return (
    <div className="flex min-h-screen flex-col px-6 py-6 sm:px-12">
      <div className="flex items-center justify-between">
        <Link to="/"><Logo /></Link>
        <ThemeToggle />
      </div>
      <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center py-12">
        <Card className="p-6 sm:p-8" data-testid="force-password-change">
          <div className="grid size-12 place-items-center rounded-2xl bg-brand-soft text-brand"><KeyRound className="size-6" /></div>
          <h1 className="mt-4 text-2xl font-extrabold tracking-tight">رمز عبور تازه انتخاب کنید</h1>
          <p className="mt-2 text-sm leading-7 text-muted">
            {me.full_name || me.username} عزیز، رمزی که با آن وارد شدید موقت است و ادمین سازمان آن را ساخته. برای امنیت حسابتان،
            پیش از ادامه یک رمز جدید که فقط خودتان می‌دانید انتخاب کنید.
          </p>
          <PasswordChangeForm className="mt-6" oldLabel="رمز موقت" submitLabel="ذخیره و ادامه"
            onDone={() => navigate(homePathFor({ ...me, must_change_password: false }), { replace: true })} />
        </Card>
        <Button variant="ghost" size="sm" className="mx-auto mt-4" icon={<LogOut className="size-4" />} onClick={logout}>خروج</Button>
      </div>
    </div>
  );
}
