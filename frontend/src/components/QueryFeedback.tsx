import { ErrorState } from "@/ui/primitives";
import { UpdatedAt } from "./UpdatedAt";

/** خطای تازه‌سازی، دادهٔ آخرین دریافت موفق را از کاربر نمی‌گیرد. */
export function QueryFeedback({ error, retry, updatedAt }: { error: unknown; retry: () => void; updatedAt?: number }) {
  if (!error) return null;
  return <div role="status" aria-live="polite">
    <ErrorState error={error} onRetry={retry} />
    {updatedAt ? <p className="mx-5 mb-3 text-xs text-muted">اطلاعات قبلی نمایش داده می‌شود. <UpdatedAt at={updatedAt} label="آخرین دریافت موفق" /></p> : null}
  </div>;
}
