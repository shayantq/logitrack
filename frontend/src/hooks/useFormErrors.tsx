import { useCallback, useRef, useState, type RefObject } from "react";
import { ApiError, errorMessage } from "@/api/client";
import { persianValidity } from "@/ui/primitives";

/** فقط پیام و مسیر فیلد نگهداری می‌شود؛ مقادیر فرم در ذخیره‌سازی مرورگر نوشته نمی‌شوند. */
export function useFormErrors(form: RefObject<HTMLFormElement>) {
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const summary = useRef<HTMLDivElement>(null);
  const focusSummary = () => requestAnimationFrame(() => summary.current?.focus());
  const clear = useCallback((field: string) => setErrors(prev => {
    if (!prev[field]) return prev;
    const next = { ...prev }; delete next[field]; return next;
  }), []);
  const reset = () => { setErrors({}); setMessage(""); };
  const rootFor = (field: string) => [...(form.current?.querySelectorAll<HTMLElement>("[data-error-field]") ?? [])].find(el => el.dataset.errorField === field);
  const labelFor = (field: string) => rootFor(field)?.querySelector("label")?.textContent?.replace(/\s*\*$/, "") ?? "فیلد";
  const focusField = (field: string) => {
    const root = rootFor(field);
    const id = root?.querySelector("label")?.htmlFor;
    const target = (id ? document.getElementById(id) : null) ?? root?.querySelector<HTMLElement>("[data-focus-target], input:not([aria-hidden]), textarea, button");
    target?.focus(); target?.scrollIntoView({ block: "center", behavior: "smooth" });
  };
  const validate = () => {
    const next: Record<string, string> = {};
    for (const el of Array.from(form.current?.elements ?? [])) {
      if (!(el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement) || !el.willValidate) continue;
      el.setCustomValidity("");
      if (el.validity.valid) continue;
      const field = el.closest<HTMLElement>("[data-error-field]")?.dataset.errorField;
      if (field) next[field] = persianValidity(el, el.title);
    }
    setErrors(next); setMessage("");
    if (Object.keys(next).length) { focusSummary(); return false; }
    return true;
  };
  const serverError = (error: unknown) => {
    const next: Record<string, string> = {};
    if (error instanceof ApiError) for (const item of error.validationErrors) {
      const path = (item.loc ?? []).filter((part, index) => index !== 0 || part !== "body").join(".");
      // خطای مدل/ریشه فقط در خلاصه می‌آید؛ لینک شکسته ساخته نمی‌شود.
      if (rootFor(path)) next[path] = (item.msg ?? "این مقدار درست نیست.").replace(/^Value error, /, "");
    }
    setErrors(next); setMessage(errorMessage(error)); focusSummary();
  };
  const feedback = <div ref={summary} tabIndex={-1} role="alert" data-testid="form-errors" hidden={!message && !Object.keys(errors).length}
    className="mb-5 rounded-xl border border-danger/40 bg-danger-soft p-4 text-sm text-danger">
    <p className="font-semibold">ثبت انجام نشد؛ موارد زیر را بررسی کنید.</p>
    {message && <p className="mt-2">{message}</p>}
    {!!Object.keys(errors).length && <ul className="mt-2 space-y-1">{Object.entries(errors).map(([field, text]) => <li key={field}>
      <button type="button" className="text-start underline" onClick={() => focusField(field)}>{labelFor(field)}: {text}</button>
    </li>)}</ul>}
  </div>;
  return { errors, clear, reset, validate, serverError, feedback };
}
