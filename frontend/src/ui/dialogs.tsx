/**
 * پنجره‌های «تأیید» و «پرسش» هم‌شکل بقیه سامانه — جایگزین confirm() و prompt() خاکستری مرورگر.
 *   if (await confirmDialog({ title: "حذف شود؟", danger: true })) ...
 *   const reason = await promptDialog({ title: "دلیل رد", minLength: 3 });   // null = انصراف
 */
import { createContext, useCallback, useContext, useRef, useState, type FormEvent, type ReactNode } from "react";
import { AlertTriangle, HelpCircle } from "lucide-react";
import { Modal } from "./overlays";
import { Button, Field, Input, Textarea, cn } from "./primitives";

type ConfirmOptions = { title: string; text?: ReactNode; confirmLabel?: string; cancelLabel?: string; danger?: boolean };
type PromptOptions = {
  title: string; text?: ReactNode; label?: string; placeholder?: string; initial?: string; confirmLabel?: string;
  minLength?: number; maxLength?: number; required?: boolean; multiline?: boolean; danger?: boolean;
};
type Pending =
  | { kind: "confirm"; options: ConfirmOptions; resolve: (ok: boolean) => void }
  | { kind: "prompt"; options: PromptOptions; resolve: (value: string | null) => void };
type Api = { confirm: (o: ConfirmOptions) => Promise<boolean>; prompt: (o: PromptOptions) => Promise<string | null> };

const DialogsContext = createContext<Api | null>(null);
// برای صدا زدن از هر جای کد (بدون hook)؛ DialogsProvider هنگام رندر آن را تنظیم می‌کند
let globalApi: Api | null = null;
export const confirmDialog = (o: ConfirmOptions) => globalApi ? globalApi.confirm(o) : Promise.resolve(window.confirm(o.title));
export const promptDialog = (o: PromptOptions) => globalApi ? globalApi.prompt(o) : Promise.resolve(window.prompt(o.title));

export function DialogsProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null);
  const [text, setText] = useState("");
  const settled = useRef(false);

  const confirm = useCallback((options: ConfirmOptions) => new Promise<boolean>(resolve => {
    settled.current = false;
    setPending({ kind: "confirm", options, resolve });
  }), []);
  const prompt = useCallback((options: PromptOptions) => new Promise<string | null>(resolve => {
    settled.current = false;
    setText(options.initial ?? "");
    setPending({ kind: "prompt", options, resolve });
  }), []);

  const close = (result: boolean | string | null) => {
    if (!pending || settled.current) return;
    settled.current = true;
    if (pending.kind === "confirm") pending.resolve(result === true);
    else pending.resolve(typeof result === "string" ? result : null);
    setPending(null);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (pending?.kind === "prompt") close(text.trim());
    else close(true);
  };

  globalApi = { confirm, prompt };
  const o = pending?.options;
  const danger = !!o?.danger;
  const isPrompt = pending?.kind === "prompt";
  const p = isPrompt ? (o as PromptOptions) : null;
  return (
    <DialogsContext.Provider value={{ confirm, prompt }}>
      {children}
      <Modal open={!!pending} onClose={() => close(isPrompt ? null : false)} size="sm" testId={isPrompt ? "prompt-dialog" : "confirm-dialog"}
        title={<span className="flex items-center gap-2.5">
          <span className={cn("grid size-9 shrink-0 place-items-center rounded-xl", danger ? "bg-danger-soft text-danger" : "bg-brand-soft text-brand")}>
            {danger ? <AlertTriangle className="size-[18px]" /> : <HelpCircle className="size-[18px]" />}
          </span>{o?.title}
        </span>}
        footer={<>
          <Button variant="secondary" onClick={() => close(isPrompt ? null : false)} data-testid="dialog-cancel">{(o as ConfirmOptions)?.cancelLabel ?? "انصراف"}</Button>
          <Button type="submit" form="app-dialog-form" variant={danger ? "danger" : "primary"} data-testid="dialog-ok">{o?.confirmLabel ?? (isPrompt ? "ثبت" : "تأیید")}</Button>
        </>}>
        <form id="app-dialog-form" onSubmit={submit} className="space-y-4">
          {(o?.text || !p) && (
            <div className="text-sm leading-7 text-text-2" data-testid="dialog-text">
              {o?.text ?? (danger ? "این کار برگشت‌پذیر نیست." : "آیا از انجام این کار مطمئن هستید؟")}
            </div>
          )}
          {p && (
            <Field label={p.label ?? ""}>
              {p.multiline
                ? <Textarea autoFocus rows={3} required={p.required ?? !!p.minLength} minLength={p.minLength} maxLength={p.maxLength} placeholder={p.placeholder}
                    value={text} onChange={e => setText(e.target.value)} data-testid="prompt-input" />
                : <Input autoFocus required={p.required ?? !!p.minLength} minLength={p.minLength} maxLength={p.maxLength} placeholder={p.placeholder}
                    value={text} onChange={e => setText(e.target.value)} data-testid="prompt-input" />}
            </Field>
          )}
        </form>
      </Modal>
    </DialogsContext.Provider>
  );
}

export function useDialogs(): Api {
  const api = useContext(DialogsContext);
  if (!api) throw new Error("DialogsProvider missing");
  return api;
}
