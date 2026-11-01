/** زمان دریافت داده: عدد بدون زمان معلوم نیست مال کی است. «زنده» نمی‌گوییم چون داده با فاصله خوانده می‌شود. */
import { Clock } from "lucide-react";
import { faShortDateTime } from "@/lib/format";
import { cn } from "@/ui/primitives";

export function UpdatedAt({ at, label = "به‌روزرسانی", className }: { at?: number | string | null; label?: string; className?: string }) {
  if (!at) return null;
  const value = typeof at === "number" ? new Date(at).toISOString() : at;
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs text-muted", className)} data-testid="updated-at">
      <Clock className="size-3.5" aria-hidden />{label}: {faShortDateTime(value)}
    </span>
  );
}
