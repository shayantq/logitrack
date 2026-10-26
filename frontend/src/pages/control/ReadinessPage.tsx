/**
 * آمادگی راه‌اندازی (فصل‌های ۳۲ تا ۳۵): امتیاز آمادگی، بررسی‌های خودکار سلامت داده، موارد دستی با ثبت «کی و چرا»،
 * و ابزار مهاجرت داده (ورود محل‌ها و موجودی اول دوره از اکسل با پیش‌نمایش و ثبت همه یا هیچ).
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Download, FileUp, Rocket, XCircle } from "lucide-react";
import { api, authFetch, errorMessage, unwrap, type Schemas } from "@/api/client";
import { useToast } from "@/components/Toast";
import { faDateTime, faNumber } from "@/lib/format";
import { promptDialog } from "@/ui/dialogs";
import { FileField } from "@/ui/file";
import { Badge, Button, Card, CardHeader, ErrorState, PageHeader, SegmentedControl, Skeleton, cn } from "@/ui/primitives";

type Report = Schemas["DataImportReport"];
const STATUS = {
  pass: { icon: CheckCircle2, cls: "text-success", label: "آماده" },
  warn: { icon: AlertTriangle, cls: "text-warning", label: "نیاز به توجه" },
  fail: { icon: XCircle, cls: "text-danger", label: "مانع شروع" },
} as const;

export default function ReadinessPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const q = useQuery({ queryKey: ["readiness"], queryFn: () => unwrap(api.GET("/readiness/")) });
  const mark = useMutation({
    mutationFn: ({ key, done, note }: { key: string; done: boolean; note: string | null }) =>
      unwrap(api.PUT("/readiness/manual/{key}", { params: { path: { key } }, body: { done, note } })),
    onSuccess: d => { queryClient.setQueryData(["readiness"], d); toast.success("چک‌لیست به‌روز شد."); },
    onError: e => toast.error(errorMessage(e)),
  });

  if (q.isLoading) return <Skeleton className="h-96" />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const d = q.data;
  return (
    <>
      <PageHeader eyebrow="تنظیمات" title="آمادگی راه‌اندازی"
        subtitle="پیش از شروع کار واقعی: سلامت داده، موجودی اول دوره، برچسب‌ها، مجوزها، آموزش، تأیید بکاپ و امضای شروع"
        actions={<Button size="sm" variant="secondary" onClick={() => q.refetch()} loading={q.isFetching}>بررسی دوباره</Button>} />
      <div className="mb-5 grid gap-4 lg:grid-cols-3">
        <Card className="flex items-center gap-5 p-5 lg:col-span-1" data-testid="readiness-score" data-ready={d.ready}>
          <div className="relative grid size-24 shrink-0 place-items-center">
            <svg viewBox="0 0 36 36" className="absolute inset-0 -rotate-90">
              <circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--border)" strokeWidth="3" />
              <circle cx="18" cy="18" r="15.5" fill="none" stroke={d.ready ? "var(--success)" : "var(--brand)"} strokeWidth="3" strokeLinecap="round"
                strokeDasharray={`${(d.score / 100) * 97.4} 97.4`} className="transition-all duration-700" />
            </svg>
            <span className="text-2xl font-extrabold tnum">{faNumber(d.score)}٪</span>
          </div>
          <div>
            <div className="font-bold">{d.ready ? "آماده شروع رسمی ✓" : "در حال آماده‌سازی"}</div>
            <div className="mt-1 text-sm text-muted">{faNumber(d.passed)} از {faNumber(d.total)} مورد</div>
            {d.blockers.length > 0 && <div className="mt-2 text-xs text-danger">مانع: {d.blockers.join("، ")}</div>}
          </div>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader title="بررسی خودکار" subtitle={`آخرین بررسی ${faDateTime(d.checked_at)}`} icon={<Rocket className="size-4" />} />
          <ul className="divide-y divide-border" data-testid="readiness-checks">
            {d.checks.map(c => {
              const s = STATUS[c.status];
              const Icon = s.icon;
              return (
                <li key={c.key} className="flex items-start gap-3 px-5 py-3" data-testid="readiness-check" data-key={c.key} data-status={c.status}>
                  <Icon className={cn("mt-0.5 size-5 shrink-0", s.cls)} aria-label={s.label} />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold">{c.label} <span className="text-xs font-normal text-muted">· {c.group}</span></div>
                    <div className="text-xs text-text-2">{c.detail}</div>
                  </div>
                  {c.path && c.status !== "pass" && <Link to={c.path} className="shrink-0 text-xs font-medium text-brand hover:underline">رفع ←</Link>}
                </li>
              );
            })}
          </ul>
        </Card>
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader title="چک‌لیست دستی" subtitle="هر تیک با نام، زمان و توضیح در گزارش فعالیت ثبت می‌شود" icon={<CheckCircle2 className="size-4" />} />
          <ul className="divide-y divide-border" data-testid="readiness-manual">
            {d.manual.map(m => (
              <li key={m.key} className="flex items-start gap-3 px-5 py-3" data-testid="manual-item" data-key={m.key} data-done={m.done}>
                <input type="checkbox" className="mt-1 size-4" checked={m.done} disabled={mark.isPending} aria-label={m.label}
                  onChange={async e => {
                    const done = e.target.checked;
                    const note = await promptDialog({ title: m.label, label: "توضیح (اختیاری)", required: false, confirmLabel: done ? "ثبت انجام" : "برگرداندن" });
                    if (note !== null) mark.mutate({ key: m.key, done, note: note || null });
                  }} />
                <div className="min-w-0 flex-1">
                  <div className={cn("text-sm", m.done ? "font-medium text-text" : "text-text-2")}>{m.label} <Badge tone="muted">{m.group}</Badge></div>
                  {m.updated_at && <div className="mt-0.5 text-xs text-muted">{m.updated_by} · {faDateTime(m.updated_at)}{m.note ? ` — ${m.note}` : ""}</div>}
                </div>
              </li>
            ))}
          </ul>
        </Card>
        <ImportCard />
      </div>
    </>
  );
}

function ImportCard() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<"locations" | "opening">("opening");
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState<"preview" | "apply" | "template" | null>(null);

  async function send(dryRun: boolean) {
    if (!file) return;
    setBusy(dryRun ? "preview" : "apply");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("dry_run", String(dryRun));
      const r = await authFetch(`/readiness/import/${kind}`, { method: "POST", body: form });
      const data = await r.json();
      if (!r.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "ورود ناموفق بود.");
      setReport(data as Report);
      if (!dryRun) {
        toast.success(kind === "opening" ? `موجودی اول دوره ثبت شد (${(data as Report).document_code}).` : `${faNumber((data as Report).create ?? 0)} محل ساخته شد.`);
        queryClient.invalidateQueries({ queryKey: ["readiness"] });
        setFile(null);
      }
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function template() {
    setBusy("template");
    try {
      const r = await authFetch(`/readiness/import/${kind}/template`);
      if (!r.ok) throw new Error("دریافت قالب ناموفق بود.");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(await r.blob());
      a.download = kind === "opening" ? "Pasineh_Opening_Balance_Template.xlsx" : "Pasineh_Locations_Template.xlsx";
      a.click();
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }
  return (
    <Card data-testid="readiness-import">
      <CardHeader title="مهاجرت داده از سیستم قبلی" subtitle="پیش‌نمایش بدون ذخیره، سپس ثبت همه یا هیچ" icon={<FileUp className="size-4" />} />
      <div className="space-y-4 p-5">
        <SegmentedControl value={kind} onChange={k => { setKind(k); setReport(null); }}
          options={[{ value: "opening", label: "موجودی اول دوره" }, { value: "locations", label: "محل‌های انبار" }]} />
        <p className="text-xs leading-6 text-text-2">{kind === "opening"
          ? "هر ردیف: انبار، کد کالا، مقدار، و در صورت نیاز محل، بچ، انقضا، سریال و وضعیت کیفی. یک سند «موجودی اول دوره» ساخته می‌شود؛ همان فایل دوباره ثبت نمی‌شود."
          : "هر ردیف: انبار، کد محل، سطح و محل مادر، نوع و ظرفیت. محل‌های موجود رد می‌شوند؛ مادرها قبل از فرزندها ساخته می‌شوند."}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="ghost" icon={<Download className="size-4" />} loading={busy === "template"} onClick={template} data-testid="import-template">قالب اکسل</Button>
          <FileField file={file} onChange={f => { setFile(f); setReport(null); }} accept=".xlsx" testId="import-file" />
          <Button size="sm" variant="secondary" disabled={!file} loading={busy === "preview"} onClick={() => send(true)} data-testid="import-preview">پیش‌نمایش</Button>
          <Button size="sm" disabled={!file || !report || report.error_count > 0 || report.applied} loading={busy === "apply"} onClick={() => send(false)} data-testid="import-apply">ثبت نهایی</Button>
        </div>
        {report && (
          <div className="rounded-xl border border-border p-3 text-sm" data-testid="import-report" data-errors={report.error_count} data-applied={report.applied}>
            <div className="flex flex-wrap gap-2">
              <Badge tone="info">{faNumber(report.rows)} ردیف</Badge>
              <Badge tone={report.error_count ? "danger" : "success"}>{report.error_count ? `${faNumber(report.error_count)} خطا` : "بدون خطا"}</Badge>
              {report.units != null && <Badge tone="muted">{faNumber(report.units)} واحد</Badge>}
              {report.create != null && <Badge tone="muted">{faNumber(report.create)} محل جدید · {faNumber(report.skip ?? 0)} موجود</Badge>}
              {report.applied && <Badge tone="success">ثبت شد{report.document_code ? ` — ${report.document_code}` : ""}</Badge>}
            </div>
            {report.errors.length > 0 && <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto text-xs text-danger">
              {report.errors.map((e, i) => <li key={i}>ردیف {faNumber(e.line)}: {e.message}</li>)}</ul>}
            {!report.errors.length && <ul className="mt-2 max-h-40 space-y-0.5 overflow-y-auto text-xs text-text-2">
              {report.preview.map(p => <li key={p.line}>ردیف {faNumber(p.line)}: {p.summary}</li>)}</ul>}
          </div>
        )}
        <p className="rounded-xl bg-surface-2 p-3 text-xs leading-6 text-text-2">
          <b>تأیید بکاپ:</b> روی سرور <code className="ltr">bash scripts/verify-backup.sh</code> آخرین بکاپ شبانه را در یک دیتابیس موقت بازیابی
          و تعداد ردیف‌ها را با دیتابیس اصلی مقایسه می‌کند؛ بعد از موفقیت، مورد «بکاپ بازیابی آزمایشی شد» را تیک بزنید.</p>
      </div>
    </Card>
  );
}
