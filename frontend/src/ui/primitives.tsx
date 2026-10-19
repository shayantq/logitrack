/** اجزای پایه رابط کاربری — همه بر پایه توکن‌های رنگی (روشن/تاریک خودکار) */
import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";

export function cn(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------- Button
type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "outline-danger" | "soft";
const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-brand text-brand-ink hover:bg-brand-strong shadow-sm",
  secondary: "border border-border-strong bg-surface text-text hover:bg-surface-2",
  ghost: "text-text-2 hover:bg-surface-2 hover:text-text",
  danger: "bg-danger text-white hover:opacity-90",
  "outline-danger": "border border-danger/40 text-danger hover:bg-danger-soft",
  soft: "bg-brand-soft text-brand-strong hover:brightness-95",
};
const BUTTON_SIZES = { sm: "h-8 px-3 text-xs gap-1.5", md: "h-10 px-4 text-sm gap-2", lg: "h-12 px-6 text-base gap-2", icon: "size-9" };

/** کلاس‌های دکمه برای لینک‌هایی که باید شبیه دکمه باشند */
export function buttonClass(variant: ButtonVariant = "primary", size: keyof typeof BUTTON_SIZES = "md", className?: string) {
  return cn("inline-flex shrink-0 items-center justify-center rounded-xl font-medium transition-all active:scale-[.98]",
    BUTTON_VARIANTS[variant], BUTTON_SIZES[size], className);
}

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant; size?: keyof typeof BUTTON_SIZES; loading?: boolean; icon?: ReactNode;
}>(function Button({ variant = "primary", size = "md", loading, icon, className, children, disabled, ...props }, ref) {
  return (
    <button ref={ref} disabled={disabled || loading}
      className={buttonClass(variant, size, cn("disabled:pointer-events-none disabled:opacity-50", className))}
      {...props}>
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
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
const FIELD_BASE = "w-full rounded-xl border border-border-strong bg-surface px-3.5 text-sm text-text placeholder:text-muted/70 transition focus:border-brand focus:ring-4 focus:ring-brand/15 focus:outline-none disabled:opacity-60";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...props }, ref) {
  return <input ref={ref} className={cn(FIELD_BASE, "h-10", className)} {...props} />;
});
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...props }, ref) {
  return <textarea ref={ref} className={cn(FIELD_BASE, "py-2.5", className)} {...props} />;
});

export function Field({ label, hint, error, children, className }: { label: ReactNode; hint?: ReactNode; error?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1.5 block text-sm font-medium text-text-2">{label}</span>
      {children}
      {error ? <span className="mt-1 block text-xs text-danger">{error}</span> : hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export function Checkbox({ label, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-text-2">
      <input type="checkbox" className="size-4 rounded accent-[var(--brand)]" {...props} />
      {label}
    </label>
  );
}

// ---------------------------------------------------------------- Feedback
export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-5 animate-spin text-brand", className)} />;
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn("relative overflow-hidden rounded-lg bg-surface-2", className)}>
      <div className="absolute inset-0 translate-x-full animate-[shimmer_1.4s_infinite] bg-gradient-to-l from-transparent via-border/60 to-transparent" />
    </div>
  );
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-3 p-5" data-testid="loading">
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

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
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
    <div className="inline-flex rounded-xl border border-border bg-surface-2 p-1">
      {options.map(o => (
        <button key={o.value} type="button" onClick={() => onChange(o.value)}
          className={cn("rounded-lg px-3 py-1.5 text-xs font-medium transition",
            value === o.value ? "bg-surface text-text shadow-sm" : "text-muted hover:text-text")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
