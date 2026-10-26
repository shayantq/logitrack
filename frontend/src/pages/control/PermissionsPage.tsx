/**
 * مجوزهای نقش‌ها (فصل ۲۲): ماتریس مجوزهای ریز هر نقش در سازمان. هر تغییر با دلیل در گزارش فعالیت ثبت می‌شود و
 * بلافاصله سمت سرور اعمال می‌شود؛ مجوزهایی که برای نقشی مجاز نیستند قفل‌اند و «مدیریت مجوزها» از ادمین گرفته نمی‌شود.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Lock, RotateCcw, ShieldAlert } from "lucide-react";
import { api, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useToast } from "@/components/Toast";
import { promptDialog } from "@/ui/dialogs";
import { Badge, Button, Card, ErrorState, PageHeader, TableSkeleton, cn } from "@/ui/primitives";

type Matrix = Schemas["PermissionMatrix"];

export default function PermissionsPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const q = useQuery({ queryKey: ["permissions"], queryFn: () => unwrap(api.GET("/permissions/")) });
  const done = (m: Matrix) => { queryClient.setQueryData(["permissions"], m); queryClient.invalidateQueries({ queryKey: ["me"] }); };
  const update = useMutation({
    mutationFn: ({ role, key, allowed, reason }: { role: "org_admin" | "warehouse_manager"; key: string; allowed: boolean; reason: string }) =>
      unwrap(api.PUT("/permissions/{role}/{key}", { params: { path: { role, key } }, body: { allowed, reason } })),
    onSuccess: m => { done(m); toast.success("مجوز تغییر کرد و در گزارش فعالیت ثبت شد."); },
    onError: e => toast.error(errorMessage(e)),
  });
  const reset = useMutation({
    mutationFn: (reason: string) => unwrap(api.POST("/permissions/reset", { body: { reason } })),
    onSuccess: m => { done(m); toast.success("همه مجوزها به پیش‌فرض برگشت."); },
    onError: e => toast.error(errorMessage(e)),
  });
  const ask = async (title: string) => promptDialog({ title, label: "دلیل (در گزارش فعالیت ثبت می‌شود)", placeholder: "مثلاً سرپرست شیفت شب", required: true, confirmLabel: "ثبت" });

  if (q.isLoading) return <TableSkeleton />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const groups = [...new Set(q.data.permissions.map(p => p.group))];
  return (
    <>
      <PageHeader eyebrow="تنظیمات" title="مجوزهای نقش‌ها"
        subtitle="چه کسی چه کاری می‌تواند بکند — بررسی همیشه سمت سرور است؛ هر تغییر با دلیل ثبت می‌شود"
        actions={<Button variant="secondary" size="sm" icon={<RotateCcw className="size-4" />} loading={reset.isPending} data-testid="permissions-reset"
          onClick={async () => { const r = await ask("بازگشت همه مجوزها به پیش‌فرض"); if (r) reset.mutate(r); }}>پیش‌فرض</Button>} />
      <p className="mb-4 flex items-start gap-2 rounded-xl bg-info-soft/60 px-4 py-3 text-sm text-text-2">
        <ShieldAlert className="mt-0.5 size-4 shrink-0 text-info" />
        مجوزهای «حساس» (اصلاح موجودی، برگشت سند، امحا، تأیید انبارگردانی، چاپ مجدد برچسب، ورود داده) همیشه با دلیل در گزارش فعالیت ثبت می‌شوند.
      </p>
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="table-base" data-testid="permissions-table">
            <thead><tr><th>مجوز</th>{q.data.roles.map(r => <th key={r.code} className="w-36 text-center">{r.label}</th>)}</tr></thead>
            <tbody>
              {groups.map(g => [
                <tr key={g}><td colSpan={q.data!.roles.length + 1} className="bg-surface-2 text-xs font-semibold text-muted">{g}</td></tr>,
                ...q.data!.permissions.filter(p => p.group === g).map(p => (
                  <tr key={p.key} data-testid="permission-row" data-key={p.key}>
                    <td><div className="font-medium">{p.label}{p.sensitive && <Badge tone="warning" className="ms-2">حساس</Badge>}</div>
                      <div className="font-mono text-[11px] text-muted ltr text-start">{p.key}</div></td>
                    {q.data!.roles.map(r => {
                      const cell = p.roles[r.code];
                      return (
                        <td key={r.code} className="text-center">
                          {!cell.editable ? (
                            <span className="inline-flex items-center gap-1 text-xs text-muted" title={cell.allowed ? "همیشه فعال" : "برای این نقش ممکن نیست"}>
                              <Lock className="size-3.5" />{cell.allowed ? "همیشه" : "—"}</span>
                          ) : (
                            <button type="button" role="switch" aria-checked={cell.allowed} aria-label={`${p.label} — ${r.label}`}
                              data-testid="permission-toggle" data-role={r.code} disabled={update.isPending}
                              onClick={async () => {
                                const reason = await ask(`${cell.allowed ? "گرفتن" : "دادن"} «${p.label}» ${cell.allowed ? "از" : "به"} ${r.label}`);
                                if (reason) update.mutate({ role: r.code as "org_admin", key: p.key, allowed: !cell.allowed, reason });
                              }}
                              className={cn("relative inline-flex h-6 w-11 items-center rounded-full transition-colors duration-200",
                                cell.allowed ? "bg-brand" : "bg-border")}>
                              <span className={cn("inline-block size-5 rounded-full bg-white shadow transition-transform duration-200",
                                cell.allowed ? "-translate-x-0.5" : "-translate-x-[1.35rem]")} />
                            </button>
                          )}
                          {cell.customized && <div className="mt-1 text-[10px] text-warning">تغییر سازمان</div>}
                        </td>
                      );
                    })}
                  </tr>
                )),
              ])}
            </tbody>
          </table>
        </div>
      </Card>
      <p className="mt-3 flex items-center gap-1.5 text-xs text-muted"><KeyRound className="size-3.5" />راننده‌ها فقط به پنل راننده دسترسی دارند و در این جدول نیستند.</p>
    </>
  );
}
