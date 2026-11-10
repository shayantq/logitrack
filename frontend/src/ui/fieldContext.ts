import { createContext, useContext, useId, useLayoutEffect } from "react";

export const FieldContext = createContext<{ id: string; labelId: string; describedBy?: string; invalid: boolean; clearError?: () => void; register: (id: string) => () => void } | null>(null);
export const FormFeedbackContext = createContext<{ errors: Record<string, string>; clear: (name: string) => void } | null>(null);
/** هر کنترل شناسه مستقل دارد؛ فیلدهای مرکب مثل روز/ماه/سال هم ID تکراری نمی‌سازند. */
export function useField(explicitId?: string) {
  const field = useContext(FieldContext);
  const generatedId = useId();
  const id = explicitId ?? `${field?.id ?? "control"}-${generatedId}`;
  const register = field?.register;
  useLayoutEffect(() => register?.(id), [register, id]);
  return field ? { ...field, id } : null;
}
export const describedBy = (...ids: (string | undefined)[]) => ids.filter(Boolean).join(" ") || undefined;
