import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { CheckCircle2, XCircle } from "lucide-react";

type Toast = { id: number; message: string; error: boolean };
type ToastApi = { success: (message: string) => void; error: (message: string) => void };

const ToastContext = createContext<ToastApi | null>(null);
let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((message: string, error: boolean) => {
    const id = nextId++;
    setToasts(list => [...list, { id, message, error }]);
    setTimeout(() => setToasts(list => list.filter(t => t.id !== id)), error ? 6000 : 3500);
  }, []);

  const api = useMemo<ToastApi>(() => ({ success: m => push(m, false), error: m => push(m, true) }), [push]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed bottom-5 left-5 z-[60] flex max-w-[90vw] flex-col gap-2" role="status" aria-live="polite">
        {toasts.map(t => (
          <div key={t.id} data-testid="toast"
            className={`lt-toast pointer-events-auto flex items-center gap-2.5 rounded-xl border px-4 py-3 text-sm font-medium shadow-float animate-rise ${
              t.error ? "border-danger/30 bg-danger-soft text-danger" : "border-success/30 bg-success-soft text-success"}`}>
            {t.error ? <XCircle className="size-4 shrink-0" /> : <CheckCircle2 className="size-4 shrink-0" />}
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}
