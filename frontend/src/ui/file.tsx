/**
 * انتخاب فایل فارسی — جایگزین دکمه پیش‌فرض کروم («Choose File / No file chosen»).
 * خود input در DOM می‌ماند (پنهان) تا دسترس‌پذیری، کشیدن‌ورهاکردن پنجره فایل و setInputFiles تست‌ها کار کند.
 */
import { useEffect, useRef, type ReactNode } from "react";
import { Paperclip, X } from "lucide-react";
import { cn } from "./primitives";

const sizeText = (bytes: number) =>
  bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toLocaleString("fa-IR", { maximumFractionDigits: 1 })} مگابایت`
    : `${Math.max(1, Math.round(bytes / 1024)).toLocaleString("fa-IR")} کیلوبایت`;

export function FileField({ file, onChange, accept, testId, placeholder = "فایلی انتخاب نشده", button = "انتخاب فایل", icon, className, disabled }: {
  file: File | null; onChange: (file: File | null) => void; accept?: string; testId?: string;
  placeholder?: string; button?: string; icon?: ReactNode; className?: string; disabled?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  // وقتی والد فایل را پاک کرد (مثلاً بعد از آپلود)، انتخاب همان فایل دوباره هم onChange بدهد
  useEffect(() => { if (!file && input.current) input.current.value = ""; }, [file]);

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <label className={cn("group flex min-w-0 flex-1 cursor-pointer items-center gap-3 rounded-xl border border-dashed border-border-strong bg-surface px-3 py-2 transition",
        "hover:border-brand hover:bg-brand-soft/40 focus-within:border-brand focus-within:ring-4 focus-within:ring-brand/15", disabled && "pointer-events-none opacity-60")}>
        <input ref={input} type="file" accept={accept} className="sr-only" data-testid={testId} disabled={disabled}
          onChange={e => onChange(e.target.files?.[0] ?? null)} />
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-2 text-muted transition group-hover:text-brand">{icon ?? <Paperclip className="size-4" />}</span>
        <span className="min-w-0 flex-1">
          {file ? (
            <>
              <span className="block truncate text-sm font-medium text-text ltr text-end" data-testid={testId ? `${testId}-name` : undefined}>{file.name}</span>
              <span className="block text-xs text-muted">{sizeText(file.size)}</span>
            </>
          ) : <span className="block text-sm text-muted">{placeholder}</span>}
        </span>
        <span className="shrink-0 rounded-lg bg-surface-2 px-2.5 py-1 text-xs font-medium text-text transition group-hover:bg-brand group-hover:text-white">{file ? "تغییر" : button}</span>
      </label>
      {file && !disabled && (
        <button type="button" aria-label="حذف فایل انتخاب‌شده" onClick={() => onChange(null)}
          className="grid size-9 shrink-0 place-items-center rounded-lg text-muted transition hover:bg-danger-soft hover:text-danger">
          <X className="size-4" />
        </button>
      )}
    </div>
  );
}
