/**
 * عملیات گروهی با پیش‌نمایش: اول سرور بدون تغییر بررسی می‌کند (چند سطر قابل اجرا، نامعتبر با دلیل، بدون دسترسی)،
 * بعد با تأیید کاربر سطر به سطر با همان قواعد عملیات تکی اجرا می‌شود و نتیجه هر سطر نمایش داده می‌شود.
 * عملیات غیرقابل‌بازگشت (مثل بستن تیکت) عبارت تأیید تایپی می‌خواهد.
 */
import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, ShieldAlert, XCircle } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { faNumber } from "@/lib/format";
import { Modal } from "@/ui/overlays";
import { Badge, Button, ErrorState, Field, Input, Skeleton } from "@/ui/primitives";

type Result = Schemas["BulkOut"];
export const CONFIRM_TEXT = "تأیید";

export type BulkRequest = {
  endpoint: "/orders/bulk" | "/tickets/bulk";
  action: string;
  ids: number[];
  params?: Record<string, unknown>;
  title: string;
  typedConfirm?: boolean;
};

const STATUS: Record<string, { label: string; tone: "success" | "warning" | "danger" | "muted" }> = {
  ok: { label: "قابل اجرا", tone: "success" }, done: { label: "انجام شد", tone: "success" },
  invalid: { label: "نامعتبر", tone: "warning" }, failed: { label: "ناموفق", tone: "danger" },
  unauthorized: { label: "بدون دسترسی", tone: "muted" },
};

export function BulkActionModal({ request, onClose, onDone }: { request: BulkRequest | null; onClose: () => void; onDone: () => void }) {
  const [confirm, setConfirm] = useState("");
  const call = (dry_run: boolean) => {
    const body = { action: request!.action, ids: request!.ids, params: { ...request!.params, ...(dry_run ? {} : { confirm }) }, dry_run };
    return request!.endpoint === "/orders/bulk"
      ? unwrap(api.POST("/orders/bulk", { body }))
      : unwrap(api.POST("/tickets/bulk", { body }));
  };
  const preview = useMutation({ mutationFn: () => call(true) });
  const execute = useMutation({ mutationFn: () => call(false), onSuccess: onDone });

  useEffect(() => {
    setConfirm("");
    execute.reset();
    if (request) preview.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request]);

  const result: Result | undefined = execute.data ?? preview.data;
  const done = !!execute.data;
  const blocked = !!request?.typedConfirm && confirm.trim() !== CONFIRM_TEXT;

  return (
    <Modal open={!!request} onClose={onClose} title={request?.title ?? ""} size="lg" testId="bulk-modal"
      description={done ? "نتیجه اجرا برای هر سطر" : "پیش‌نمایش — هنوز چیزی تغییر نکرده است."}
      footer={done ? <Button onClick={onClose} data-testid="bulk-close">بستن</Button> : <>
        <Button variant="ghost" onClick={onClose}>انصراف</Button>
        <Button onClick={() => execute.mutate()} loading={execute.isPending} data-testid="bulk-run"
          disabled={!result || result.valid === 0 || blocked} variant={request?.typedConfirm ? "danger" : "primary"}>
          اجرا برای {faNumber(result?.valid ?? 0)} مورد
        </Button>
      </>}>
      {preview.isPending ? <Skeleton className="h-32" /> : preview.error ? <ErrorState error={preview.error} onRetry={() => preview.mutate()} /> : result && (
        <div className="space-y-4" data-testid="bulk-summary" data-valid={result.valid} data-invalid={result.invalid} data-unauthorized={result.unauthorized}>
          <div className="grid grid-cols-3 gap-3 text-center">
            <Summary icon={<CheckCircle2 className="size-4 text-success" />} label={done ? "انجام شد" : "قابل اجرا"} value={result.valid} />
            <Summary icon={<XCircle className="size-4 text-warning" />} label={done ? "ناموفق" : "نامعتبر"} value={result.invalid} />
            <Summary icon={<ShieldAlert className="size-4 text-muted" />} label="بدون دسترسی" value={result.unauthorized} />
          </div>
          {execute.error && <p className="rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger">{errorMessage(execute.error)}</p>}
          <ul className="max-h-72 divide-y divide-border overflow-y-auto rounded-xl border border-border text-sm">
            {result.results.map(r => (
              <li key={r.id} className="flex items-center justify-between gap-3 px-4 py-2" data-testid="bulk-row" data-status={r.status}>
                <span className="font-mono text-xs ltr">{r.label}</span>
                <span className="flex min-w-0 items-center gap-2">
                  {r.reason && <span className="truncate text-xs text-muted">{r.reason}</span>}
                  <Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge>
                </span>
              </li>
            ))}
          </ul>
          {request?.typedConfirm && !done && (
            <Field label={`این کار برگشت‌پذیر نیست؛ برای ادامه «${CONFIRM_TEXT}» را بنویسید`}>
              <Input value={confirm} onChange={e => setConfirm(e.target.value)} data-testid="bulk-confirm" />
            </Field>
          )}
        </div>
      )}
    </Modal>
  );
}

function Summary({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  return (
    <div className="rounded-xl border border-border px-3 py-3">
      <div className="flex items-center justify-center gap-1.5 text-xs text-muted">{icon}{label}</div>
      <div className="mt-1 text-xl font-bold">{faNumber(value)}</div>
    </div>
  );
}
