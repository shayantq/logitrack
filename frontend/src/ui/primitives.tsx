/** اجزای پایه رابط کاربری — همه بر پایه توکن‌های رنگی (روشن/تاریک خودکار) */
import { forwardRef, useCallback, useContext, useEffect, useId, useImperativeHandle, useRef, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";
import { faNumber } from "@/lib/format";
import { describedBy, FieldContext, FormFeedbackContext, useField } from "./fieldContext";

export function cn(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------- Button
type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "outline-danger" | "soft";
const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-brand text-brand-ink hover:bg-brand-strong shadow-sm",
  secondary: "border border-border-strong bg-surface text-text hover:bg-surface-2",
  ghost: "text-text-2 hover:bg-surface-2 hover:text-text",
  danger: "bg-danger text-danger-ink hover:opacity-90",
  "outline-danger": "border border-danger/40 text-danger hover:bg-danger-soft",
  soft: "bg-brand-soft text-brand-strong hover:brightness-95",
};
const BUTTON_SIZES = { sm: "h-8 px-3 text-xs gap-1.5", md: "h-10 px-4 text-sm gap-2", lg: "h-12 px-6 text-base gap-2", icon: "size-9" };

/** کلاس‌های دکمه برای لینک‌هایی که باید شبیه دکمه باشند */
export function buttonClass(variant: ButtonVariant = "primary", size: keyof typeof BUTTON_SIZES = "md", className?: string) {
  return cn("ui-button inline-flex shrink-0 items-center justify-center rounded-xl font-medium transition-colors active:scale-[.98] motion-reduce:active:scale-100",
    BUTTON_VARIANTS[variant], BUTTON_SIZES[size], className);
}

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant; size?: keyof typeof BUTTON_SIZES; loading?: boolean; icon?: ReactNode;
}>(function Button({ variant = "primary", size = "md", loading, icon, className, children, disabled, ...props }, ref) {
  return (
    <button ref={ref} disabled={disabled || loading} aria-busy={loading || undefined}
      className={buttonClass(variant, size, cn("disabled:pointer-events-none disabled:opacity-50", className))}
      {...props}>
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

// ---------------------------------------------------------------- Badge
export type Tone = "brand" | "accent" | "success" | "warning" | "danger" | "info" | "violet" | "orange" | "pink" | "muted";
const TONES: Record<Tone, string> = {
  brand: "bg-brand-soft text-brand-strong", accent: "bg-accent-soft text-brand-strong", success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning", danger: "bg-danger-soft text-danger", info: "bg-info-soft text-info",
  violet: "bg-violet-soft text-violet", orange: "bg-orange-soft text-orange", pink: "bg-pink-soft text-pink",
  muted: "bg-surface-2 text-muted border border-border",
};
/** کلاس پس‌زمینه ملایم + متن هر tone (همان رنگ Badge) */
export function toneClass(tone: Tone): string {
  return TONES[tone];
}
/** رنگ اصلی هر tone به‌صورت متغیر CSS (برای نمودار، نوار و هاله رنگی) */
export function toneColor(tone: Tone): string {
  return tone === "muted" ? "var(--muted)" : `var(--${tone})`;
}
export function Badge({ tone = "muted", children, dot, className }: { tone?: Tone; children: ReactNode; dot?: boolean; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium", TONES[tone], className)}>
      {dot && <span className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

// ---------------------------------------------------------------- Card
export function Card({ children, className, ...props }: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("card", className)} {...props}>{children}</div>;
}
export function CardHeader({ title, subtitle, actions, icon, tone = "brand" }: {
  title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; icon?: ReactNode; tone?: Tone;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
      <div className="flex min-w-0 items-center gap-3">
        {icon && <span className={cn("grid size-9 shrink-0 place-items-center rounded-xl", TONES[tone])}>{icon}</span>}
        <div className="min-w-0">
          <h3 className="font-semibold text-text">{title}</h3>
          {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- Form fields
// فهرست انتخاب سفارشی (به‌جای <select> پیش‌فرض مرورگر)
export { Select } from "./select";
const FIELD_BASE = "ui-field w-full rounded-xl border border-border-strong bg-surface px-3.5 text-sm text-text placeholder:text-muted transition focus:border-brand focus:ring-4 focus:ring-brand/15 focus:outline-none disabled:opacity-60";

/**
 * پیام فارسی به‌جای پیام انگلیسی مرورگر برای قاعده‌هایی که خود فیلد دارد (required، type، min، max، طول، pattern).
 * پیام قالب (pattern) همان title فیلد است که با پیام سرور یکی است (lib/validation.ts).
 */
export function persianValidity(el: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, title?: string): string {
  const v = el.validity;
  if (v.valueMissing) return el instanceof HTMLSelectElement ? "یکی از گزینه‌ها را انتخاب کنید." : "این فیلد را پر کنید.";
  if (v.patternMismatch) return title || "قالب این مقدار درست نیست.";
  if (v.typeMismatch) return el.type === "email" ? "نشانی ایمیل درست نیست (مثل name@example.com)." : el.type === "url" ? "نشانی اینترنتی درست نیست (با https:// شروع کنید)." : "این مقدار درست نیست.";
  if (v.badInput) return "فقط عدد وارد کنید.";
  if (el instanceof HTMLInputElement) {
    if (v.rangeUnderflow) return `مقدار نباید کمتر از ${faNumber(Number(el.min))} باشد.`;
    if (v.rangeOverflow) return `مقدار نباید بیشتر از ${faNumber(Number(el.max))} باشد.`;
    if (v.stepMismatch) return !el.step || el.step === "1" ? "فقط عدد صحیح وارد کنید." : `مقدار باید مضربی از ${faNumber(Number(el.step))} باشد.`;
  }
  if (!(el instanceof HTMLSelectElement)) {
    if (v.tooShort) return `دست‌کم ${faNumber(el.minLength)} نویسه وارد کنید.`;
    if (v.tooLong) return `حداکثر ${faNumber(el.maxLength)} نویسه مجاز است.`;
  }
  return v.valid ? "" : "این مقدار درست نیست.";
}

/** پیام مرورگر را فارسی می‌کند؛ پیام قبلی اول پاک می‌شود تا وضعیت واقعی فیلد سنجیده شود */
function explainInvalid(el: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, title?: string) {
  el.setCustomValidity("");
  if (!el.validity.valid) el.setCustomValidity(persianValidity(el, title));
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, onInvalid, onInput, ...props }, ref) {
  const field = useField(props.id);
  const inner = useRef<HTMLInputElement>(null);
  useImperativeHandle(ref, () => inner.current as HTMLInputElement);
  // مقدار تازه (تایپ، اسکن یا پر شدن خودکار) پیام قبلی را پاک می‌کند تا فرم گیر نکند
  useEffect(() => { inner.current?.setCustomValidity(""); }, [props.value]);
  return <input ref={inner} className={cn(FIELD_BASE, "h-10", className)} {...props}
    id={props.id ?? field?.id} aria-labelledby={props["aria-labelledby"] ?? (props["aria-label"] ? undefined : field?.labelId)}
    aria-describedby={describedBy(props["aria-describedby"], field?.describedBy)} aria-invalid={props["aria-invalid"] ?? (field?.invalid || undefined)}
    onInvalid={e => { explainInvalid(e.currentTarget, props.title); onInvalid?.(e); }}
    onInput={e => { e.currentTarget.setCustomValidity(""); onInput?.(e); }} />;
});
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, onInvalid, onInput, ...props }, ref) {
  const field = useField(props.id);
  const inner = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => inner.current as HTMLTextAreaElement);
  useEffect(() => { inner.current?.setCustomValidity(""); }, [props.value]);
  return <textarea ref={inner} className={cn(FIELD_BASE, "py-2.5", className)} {...props}
    id={props.id ?? field?.id} aria-labelledby={props["aria-labelledby"] ?? (props["aria-label"] ? undefined : field?.labelId)}
    aria-describedby={describedBy(props["aria-describedby"], field?.describedBy)} aria-invalid={props["aria-invalid"] ?? (field?.invalid || undefined)}
    onInvalid={e => { explainInvalid(e.currentTarget); onInvalid?.(e); }}
    onInput={e => { e.currentTarget.setCustomValidity(""); onInput?.(e); }} />;
});

export function Field({ label, hint, error: explicitError, name, children, className }: { label: ReactNode; hint?: ReactNode; error?: ReactNode; name?: string; children: ReactNode; className?: string }) {
  const feedback = useContext(FormFeedbackContext);
  const error = explicitError ?? (name ? feedback?.errors[name] : undefined);
  const clearError = () => { if (name) feedback?.clear(name); };
  const id = useId();
  const controls = useRef(new Set<string>());
  const [controlId, setControlId] = useState<string>();
  const register = useCallback((nextId: string) => {
    controls.current.add(nextId);
    setControlId(controls.current.values().next().value);
    return () => { controls.current.delete(nextId); setControlId(controls.current.values().next().value); };
  }, []);
  return (
    <div className={cn("block", className)} data-field-root data-error-field={name} onInput={clearError} onChange={clearError}>
      <label htmlFor={controlId} id={`${id}-label`} className="mb-1.5 block text-sm font-medium text-text-2">{label}</label>
      <FieldContext.Provider value={{ id, labelId: `${id}-label`, describedBy: describedBy(hint ? `${id}-hint` : undefined, error ? `${id}-error` : undefined), invalid: !!error, clearError, register }}>{children}</FieldContext.Provider>
      {hint && <span id={`${id}-hint`} className="mt-1 block text-xs text-muted">{hint}</span>}
      {error && <span id={`${id}-error`} className="mt-1 block text-xs text-danger">{error}</span>}
    </div>
  );
}

export function Checkbox({ label, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }) {
  return (
    <label className="ui-checkbox inline-flex cursor-pointer items-center gap-2 text-sm text-text-2">
      <input type="checkbox" className="size-4 rounded accent-[var(--brand)]" {...props} />
      {label}
    </label>
  );
}

// ---------------------------------------------------------------- Feedback
export function Spinner({ className }: { className?: string }) {
  return <span role="status"><Loader2 aria-hidden className={cn("size-5 animate-spin text-brand", className)} /><span className="sr-only">در حال بارگذاری…</span></span>;
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div aria-hidden="true" className={cn("relative overflow-hidden rounded-lg bg-surface-2", className)}>
      <div className="absolute inset-0 translate-x-full animate-[shimmer_1.4s_infinite] motion-reduce:hidden bg-gradient-to-l from-transparent via-border/60 to-transparent" />
    </div>
  );
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-3 p-5" data-testid="loading" role="status" aria-label="در حال دریافت فهرست">
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-10" />)}
    </div>
  );
}

export function EmptyState({ icon, title, text, action }: { icon?: ReactNode; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="animate-fade flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      {icon && <div className="grid size-12 place-items-center rounded-2xl bg-brand-soft text-brand">{icon}</div>}
      <div className="font-semibold">{title}</div>
      {text && <p className="max-w-sm text-sm text-muted">{text}</p>}
      {action}
    </div>
  );
}

/** فهرستی که به سقف سرور رسیده است: کاربر باید بداند ردیف‌های بیشتری هست. */
export function TruncationNotice({ count, limit }: { count: number; limit: number }) {
  if (count < limit) return null;
  return (
    <p className="border-t border-border bg-warning-soft/40 px-4 py-2.5 text-xs text-text-2" data-testid="list-truncated">
      فقط {limit.toLocaleString("fa-IR")} ردیف نمایش داده شده و این فهرست کامل نیست. برای دیدن بقیه، فیلتر را دقیق‌تر کنید.
    </p>
  );
}

export type SortState<K extends string> = { key: K; dir: "asc" | "desc" } | null;

/** ستون قابل مرتب‌سازی. کلیک سوم مرتب‌سازی پیش‌فرض را برمی‌گرداند. */
export function SortHeader<K extends string>({ label, column, sort, onSort }: { label: ReactNode; column: K; sort: SortState<K>; onSort: (next: SortState<K>) => void }) {
  const active = sort?.key === column;
  const next = (): SortState<K> => !active ? { key: column, dir: "asc" } : sort?.dir === "asc" ? { key: column, dir: "desc" } : null;
  return (
    <th aria-sort={active ? (sort?.dir === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" onClick={() => onSort(next())} className="inline-flex items-center gap-1 font-inherit hover:text-brand" data-testid={`sort-${column}`}>
        {label}<span aria-hidden className="text-[10px]">{active ? (sort?.dir === "asc" ? "▲" : "▼") : "↕"}</span>
      </button>
    </th>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const denied = (error as { status?: number } | null)?.status === 403;
  if (denied) {
    return (
      <div className="animate-fade m-5 rounded-xl border border-border bg-surface-2 px-4 py-3 text-sm text-text-2" data-testid="permission-denied">
        {error instanceof Error && error.message ? error.message : "به این بخش دسترسی ندارید."}
      </div>
    );
  }
  return (
    <div className="animate-fade m-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
      <span>{error instanceof Error ? error.message : "خطا در دریافت اطلاعات."}</span>
      {onRetry && <Button size="sm" variant="outline-danger" onClick={onRetry}>تلاش دوباره</Button>}
    </div>
  );
}

// ---------------------------------------------------------------- Layout helpers
/** رنگ هر بخش پنل — همان رنگ گروه در منوی کناری (AppShell) */
export const SECTION_TONE: Record<string, Tone> = {
  "نمای کلی": "brand", "عملیات": "brand", "انبار": "info", "گزارش‌ها": "violet", "تیم": "orange",
  "تنظیمات": "pink", "راننده": "brand", "پلتفرم": "violet",
};

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: string }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow && <div className="eyebrow mb-2" style={{ "--eyebrow": toneColor(SECTION_TONE[eyebrow] ?? "brand") } as React.CSSProperties}>{eyebrow}</div>}
        <h1 className="text-2xl font-extrabold tracking-tight text-text md:text-3xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function StatCard({ label, value, icon, tone = "brand", hint }: { label: string; value: ReactNode; icon?: ReactNode; tone?: Tone; hint?: ReactNode }) {
  const color = toneColor(tone);
  return (
    <Card className="relative overflow-hidden p-5" data-tone={tone}>
      {/* نوار رنگی بالا و هاله ملایم: هر کارت با رنگ معنایی خودش از بقیه جدا می‌شود */}
      <span aria-hidden className="absolute inset-x-0 top-0 h-1" style={{ background: `linear-gradient(to left, ${color}, color-mix(in oklab, ${color} 25%, transparent))` }} />
      <span aria-hidden className="pointer-events-none absolute -left-10 -top-10 size-32 rounded-full opacity-[0.09] blur-2xl" style={{ background: color }} />
      <div className="relative flex items-start justify-between gap-3">
        <div className="text-sm text-muted">{label}</div>
        {icon && <div className={cn("grid size-9 place-items-center rounded-xl", TONES[tone])}>{icon}</div>}
      </div>
      <div className="relative mt-3 text-3xl font-extrabold tracking-tight tnum">{value}</div>
      {hint && <div className="relative mt-1 text-xs text-muted">{hint}</div>}
    </Card>
  );
}

/** نمایش «برچسب: مقدار» */
export function DataList({ items, columns = 2 }: { items: [string, ReactNode][]; columns?: 2 | 3 }) {
  return (
    <dl className={cn("grid gap-x-6 gap-y-4", columns === 3 ? "sm:grid-cols-3" : "sm:grid-cols-2")} data-testid="data-list">
      {items.map(([title, value]) => (
        <div key={title}>
          <dt className="text-xs text-muted">{title}</dt>
          <dd className="mt-0.5 text-sm font-medium text-text">{value === null || value === undefined || value === "" ? "—" : value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Table({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <div className="animate-fade overflow-x-auto">
      <table className="table-base" data-testid={testId}>{children}</table>
    </div>
  );
}

export function SegmentedControl<T extends string>({ value, options, onChange }: {
  value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void;
}) {
  return (
    <div className="ui-segmented inline-flex flex-wrap rounded-xl border border-border bg-surface-2 p-1" role="group">
      {options.map(o => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}
          className={cn("rounded-lg px-3 py-1.5 text-xs font-medium transition",
            value === o.value ? "bg-surface text-text shadow-sm" : "text-muted hover:text-text")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
