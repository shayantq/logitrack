import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { BookOpen, Boxes, FileSpreadsheet, FileText, Package, Palette, PiggyBank, ShoppingCart, Wallet } from "lucide-react";
import { useMe } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { useAsyncExport, useWarehouses } from "@/hooks/data";
import { ORDER_STATUS } from "@/lib/labels";
import { Badge, Button, Card, Field, PageHeader, Select } from "@/ui/primitives";
import { PeriodPicker, usePeriod } from "./period";

type ReportKey = "inventory" | "orders" | "ledger" | "finance" | "reorder" | "capital";
type Uses = "period" | "warehouse" | "status";

const REPORTS: { key: ReportKey; title: string; text: string; icon: ReactNode; uses: Uses[]; adminOnly?: boolean; file: string }[] = [
  { key: "inventory", title: "موجودی انبار", icon: <Boxes className="size-5" />, uses: ["warehouse"], file: "Pasineh_Inventory",
    text: "موجودی هر کالا در هر انبار، نقطه سفارش، وضعیت (ناموجود/کم) و ارزش ریالی موجودی با قیمت روز." },
  { key: "orders", title: "سفارش‌ها", icon: <Package className="size-5" />, uses: ["period", "status"], file: "Pasineh_Orders",
    text: "سفارش‌های بازه بر اساس روز تحویل: مشتری، مقصد، اقلام، وزن، مبلغ کالا، کرایه، راننده و وضعیت." },
  { key: "ledger", title: "دفتر گردش کالا", icon: <BookOpen className="size-5" />, uses: ["period", "warehouse"], file: "Pasineh_Ledger",
    text: "هر ورود، خروج، انتقال، ضایعات و انبارگردانی با مانده بعد از گردش و ثبت‌کننده." },
  { key: "finance", title: "مالی حمل‌ونقل", icon: <Wallet className="size-5" />, uses: ["period"], adminOnly: true, file: "Pasineh_Transport_Finance",
    text: "کرایه سفرهای تحویل‌شده، سهم سازمان و رانندگان، به تفکیک راننده، استان مقصد و ماه — با جزئیات هر سفر." },
  { key: "reorder", title: "نقطه سفارش و پیشنهاد خرید", icon: <ShoppingCart className="size-5" />, uses: ["warehouse"], file: "Pasineh_Reorder_Points",
    text: "نقطه سفارش فرمول و فعلی، موجودی اطمینان، فروش روزانه، روزهای پوشش و مقدار پیشنهادی خرید هر کالا." },
  { key: "capital", title: "برآورد سرمایه خرید", icon: <PiggyBank className="size-5" />, uses: ["warehouse"], adminOnly: true, file: "Pasineh_Purchase_Capital_Plan",
    text: "نقدینگی لازم برای خرید کالا در ۶ ماه آینده، ماه‌به‌ماه و به تفکیک کالا — با پیش‌بینی فروش و تورم بها." },
];
const USE_LABEL: Record<Uses, string> = { period: "بازه تاریخ", warehouse: "انبار", status: "وضعیت سفارش" };

export default function ReportsPage() {
  const me = useMe();
  const toast = useToast();
  const isAdmin = me.role === "org_admin";
  const { data: warehouses = [] } = useWarehouses();
  const [period, setPeriod] = usePeriod();
  const [warehouse, setWarehouse] = useState("");
  const [status, setStatus] = useState("");
  const exporter = useAsyncExport(toast.error, () => toast.success("گزارش آماده و دانلود شد."));
  const myWarehouse = warehouses.find(w => w.id === me.warehouse_id)?.name;

  function run(r: (typeof REPORTS)[number], format: "excel" | "pdf") {
    const body: Record<string, unknown> = { report: r.key, format };
    if (r.uses.includes("period")) Object.assign(body, { date_from: period.from, date_to: period.to });
    if (r.uses.includes("warehouse") && warehouse) body.warehouse_id = Number(warehouse);
    if (r.uses.includes("status") && status) body.status = status;
    exporter.run("/reports/generate", `${r.file}.${format === "pdf" ? "pdf" : "xlsx"}`, body, `${r.key}-${format}`);
  }

  return (
    <>
      <PageHeader eyebrow="گزارش‌ها" title="گزارش‌های اکسل و PDF"
        subtitle="همه فایل‌ها با نام، لوگو و رنگ سازمان شما، تاریخ شمسی و راست‌به‌چپ ساخته می‌شوند — آماده چاپ و ارسال."
        actions={isAdmin ? <Link to="/app/organization" className="inline-flex items-center gap-1.5 text-sm font-medium text-brand hover:underline"><Palette className="size-4" />لوگو و رنگ سربرگ</Link> : undefined} />
      <Card className="mb-6 p-4">
        <div className="flex flex-wrap items-end gap-4">
          <Field label="بازه تاریخ"><PeriodPicker value={period} onChange={setPeriod} /></Field>
          <Field label="انبار" className="w-52">
            {isAdmin ? (
              <Select value={warehouse} onChange={e => setWarehouse(e.target.value)} aria-label="انبار" data-testid="report-warehouse">
                <option value="">همه انبارها</option>{warehouses.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
              </Select>
            ) : <div className="flex h-10 items-center rounded-xl border border-border bg-surface-2 px-3.5 text-sm text-text-2">{myWarehouse ?? "انبار شما"}</div>}
          </Field>
          <Field label="وضعیت سفارش" className="w-52">
            <Select value={status} onChange={e => setStatus(e.target.value)} aria-label="وضعیت سفارش" data-testid="report-status">
              <option value="">همه وضعیت‌ها</option>
              {Object.entries(ORDER_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </Select>
          </Field>
        </div>
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        {REPORTS.filter(r => isAdmin || !r.adminOnly).map(r => (
          <Card key={r.key} className="flex flex-col p-5 transition-shadow duration-200 hover:shadow-md" data-testid={`report-card-${r.key}`}>
            <div className="flex items-start gap-3">
              <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand-strong">{r.icon}</div>
              <div className="min-w-0 flex-1">
                <h2 className="font-bold text-text">{r.title}</h2>
                <p className="mt-1 text-sm leading-6 text-muted">{r.text}</p>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {r.uses.map(u => <Badge key={u} tone="muted">{USE_LABEL[u]}</Badge>)}
              {(r.key === "finance" || r.key === "capital" || r.key === "reorder") && <Link to={r.key === "finance" ? "/app/finance" : r.key === "capital" ? "/app/capital" : "/app/reorder"} className="text-xs font-medium text-brand hover:underline">نمایش داشبورد ←</Link>}
            </div>
            <div className="mt-4 flex gap-2 border-t border-border pt-4">
              <Button size="sm" variant="secondary" icon={<FileSpreadsheet className="size-4" />} data-testid={`report-excel-${r.key}`}
                loading={exporter.running === `${r.key}-excel`} disabled={!!exporter.running && exporter.running !== `${r.key}-excel`}
                onClick={() => run(r, "excel")}>اکسل</Button>
              <Button size="sm" variant="secondary" icon={<FileText className="size-4" />} data-testid={`report-pdf-${r.key}`}
                loading={exporter.running === `${r.key}-pdf`} disabled={!!exporter.running && exporter.running !== `${r.key}-pdf`}
                onClick={() => run(r, "pdf")}>PDF</Button>
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
