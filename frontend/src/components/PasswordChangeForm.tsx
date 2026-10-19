/**
 * تغییر رمز خودم — در پروفایل راننده، منوی کاربر و صفحه «تغییر اجباری رمز» بعد از رمز موقت.
 * سرور با تغییر رمز همه نشست‌های قبلی را می‌بندد و برای همین نشست توکن تازه برمی‌گرداند.
 */
import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage, tokenStore, unwrap } from "@/api/client";
import { useToast } from "@/components/Toast";
import { Button, Field, Input, cn } from "@/ui/primitives";

export function PasswordChangeForm({ onDone, columns = 1, submitLabel = "تغییر رمز", oldLabel = "رمز فعلی", className }: {
  onDone?: () => void; columns?: 1 | 3; submitLabel?: string; oldLabel?: string; className?: string;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ old_password: "", new_password: "", repeat: "" });
  const change = useMutation({
    mutationFn: () => unwrap(api.PUT("/users/me/password", { body: { old_password: form.old_password, new_password: form.new_password } })),
    onSuccess: async res => {
      tokenStore.set(res.access_token);
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      toast.success("رمز عبور تغییر کرد.");
      setForm({ old_password: "", new_password: "", repeat: "" });
      onDone?.();
    },
    onError: e => toast.error(errorMessage(e)),
  });
  const mismatch = form.repeat !== "" && form.repeat !== form.new_password;
  const same = form.new_password !== "" && form.new_password === form.old_password;

  return (
    <form className={className} data-testid="password-form" onSubmit={(e: FormEvent) => { e.preventDefault(); if (!mismatch && !same) change.mutate(); }}>
      <div className={cn("grid gap-4", columns === 3 && "sm:grid-cols-3")}>
        <Field label={oldLabel}><Input type="password" required className="ltr" autoComplete="current-password" data-testid="password-old"
          value={form.old_password} onChange={e => setForm(f => ({ ...f, old_password: e.target.value }))} /></Field>
        <Field label="رمز جدید" hint="حداقل ۶ کاراکتر" error={same ? "رمز جدید باید با رمز فعلی فرق داشته باشد" : undefined}>
          <Input type="password" required minLength={6} maxLength={72} className="ltr" autoComplete="new-password" data-testid="password-new"
            value={form.new_password} onChange={e => setForm(f => ({ ...f, new_password: e.target.value }))} />
        </Field>
        <Field label="تکرار رمز جدید" error={mismatch ? "با رمز جدید یکی نیست" : undefined}>
          <Input type="password" required className="ltr" autoComplete="new-password" data-testid="password-repeat"
            value={form.repeat} onChange={e => setForm(f => ({ ...f, repeat: e.target.value }))} />
        </Field>
      </div>
      <div className="mt-4"><Button type="submit" size="sm" loading={change.isPending} disabled={mismatch || same} data-testid="password-submit">{submitLabel}</Button></div>
    </form>
  );
}
