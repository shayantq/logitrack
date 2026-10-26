/**
 * برچسب و بارکد (فصل ۲۷): چاپ برچسب PDF (۱۰۰×۶۰ میلی‌متر) با Code128 و QR برای کالا، محل و بسته‌های سفارش.
 * اولین چاپ هر برچسب آزاد است؛ چاپ دوباره همان برچسب دلیل و مجوز جدا می‌خواهد و در سابقه و گزارش فعالیت می‌ماند.
 */
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Printer, Search, Tags } from "lucide-react";
import { api, authFetch, unwrap } from "@/api/client";
import { useCan } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { useProducts } from "@/hooks/data";
import { faDateTime, faNumber } from "@/lib/format";
import { promptDialog } from "@/ui/dialogs";
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, PageHeader, SegmentedControl, Table, TableSkeleton } from "@/ui/primitives";
import { WarehousePicker, useWarehouseChoice } from "../warehouse/shared";

type Kind = "product" | "location" | "package";
const KINDS: Record<Kind, string> = { product: "کالا", location: "محل", package: "بسته" };
type Row = { id: number; code: string; title: string; sub?: string };

async function printPdf(body: { label_type: Kind; ids: number[]; copies: number; reason?: string | null }) {
  const r = await authFetch("/labels/print", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) {
    const detail = (await r.json().catch(() => null)) as { detail?: string } | null;
    throw Object.assign(new Error(detail?.detail ?? "چاپ برچسب ناموفق بود."), { status: r.status });
  }
  const url = URL.createObjectURL(await r.blob());
  window.open(url, "_blank", "noopener");
  return url;
}

export default function LabelsPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const canReprint = useCan("labels.reprint");
  const [kind, setKind] = useState<Kind>("location");
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [copies, setCopies] = useState("1");
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const choice = useWarehouseChoice();
  const wid = choice.value ? Number(choice.value) : null;
  const { data: products = [] } = useProducts();
  const locations = useQuery({
    queryKey: ["locations", wid], enabled: kind === "location" && !!wid,
    queryFn: () => unwrap(api.GET("/warehouses/{warehouse_id}/locations", { params: { path: { warehouse_id: wid! } } })),
  });
  const queue = useQuery({
    queryKey: ["packing-queue", wid], enabled: kind === "package",
    queryFn: () => unwrap(api.GET("/shipping/queue", { params: { query: { warehouse_id: wid } } })),
  });
  const history = useQuery({ queryKey: ["label-history"], queryFn: () => unwrap(api.GET("/labels/history", { params: { query: { limit: 50 } } })) });
  const printed = useMemo(() => new Set((history.data ?? []).filter(h => h.label_type === kind).map(h => h.target_id)), [history.data, kind]);

  const rows: Row[] = kind === "product" ? products.map(p => ({ id: p.id, code: p.barcode || p.sku, title: p.name, sub: p.sku }))
    : kind === "location" ? (locations.data ?? []).filter(l => l.is_leaf).map(l => ({ id: l.id, code: l.barcode, title: l.code, sub: l.location_type_label }))
      : (queue.data ?? []).filter(o => o.fulfillment_state === "packed").map(o => ({ id: o.id, code: o.tracking_code, title: `سفارش ${o.tracking_code}`, sub: o.destination_city ?? undefined }));
  const filtered = rows.filter(r => !q.trim() || `${r.code} ${r.title} ${r.sub ?? ""}`.toUpperCase().includes(q.trim().toUpperCase()));
  const toggle = (id: number) => setPicked(s => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const switchKind = (k: Kind) => { setKind(k); setPicked(new Set()); };

  async function run() {
    setBusy(true);
    try {
      let ids = [...picked];
      if (kind === "package") {
        // هر سفارش انتخاب‌شده ← همه بسته‌هایش
        const slips = await Promise.all(ids.map(id => unwrap(api.GET("/shipping/orders/{order_id}/packing-slip", { params: { path: { order_id: id } } }))));
        ids = slips.flatMap(s => s.packages.map(p => p.id));
      }
      const body = { label_type: kind, ids, copies: Math.max(1, Number(copies) || 1) };
      try {
        await printPdf(body);
      } catch (e) {
        const err = e as Error & { status?: number };
        if (err.status === 400 && err.message.includes("دلیل")) {
          const reason = await promptDialog({ title: "چاپ مجدد برچسب", label: "دلیل چاپ مجدد", placeholder: "مثلاً برچسب قبلی پاره شد", required: true, confirmLabel: "چاپ مجدد" });
          if (!reason) return;
          await printPdf({ ...body, reason });
        } else throw err;
      }
      toast.success("برچسب‌ها آماده شد (در زبانه جدید).");
      queryClient.invalidateQueries({ queryKey: ["label-history"] });
      setPicked(new Set());
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader eyebrow="انبار" title="برچسب و بارکد"
        subtitle="برچسب PDF با بارکد Code128 و QR — همان کدهایی که اسکن جانمایی، پیکینگ و انبارگردانی می‌پذیرد" />
      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-3 border-b border-border p-4">
          <SegmentedControl value={kind} onChange={switchKind} options={(Object.keys(KINDS) as Kind[]).map(k => ({ value: k, label: KINDS[k] }))} />
          {kind !== "product" && <div className="w-56"><WarehousePicker choice={choice} testId="labels-warehouse" /></div>}
          <label className="relative min-w-48 flex-1">
            <Search className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="جست‌وجوی کد یا نام" className="h-10 w-full rounded-xl border border-border bg-surface pe-3 ps-9 text-sm outline-none focus:border-brand" />
          </label>
          <Field label="تعداد نسخه" className="w-28"><Input type="number" min={1} max={50} value={copies} onChange={e => setCopies(e.target.value)} data-testid="labels-copies" /></Field>
          <Button icon={<Printer className="size-4" />} disabled={!picked.size} loading={busy} onClick={run} data-testid="labels-print">
            چاپ {picked.size ? faNumber(picked.size) : ""} برچسب</Button>
        </div>
        {(kind === "location" && locations.isLoading) || (kind === "package" && queue.isLoading) ? <TableSkeleton /> : !filtered.length ? (
          <EmptyState icon={<Tags className="size-5" />} title={kind === "package" ? "سفارش بسته‌بندی‌شده‌ای نیست" : "موردی پیدا نشد"} />
        ) : (
          <Table testId="labels-table">
            <thead><tr><th className="w-10"><input type="checkbox" aria-label="انتخاب همه" checked={filtered.every(r => picked.has(r.id))}
              onChange={e => setPicked(e.target.checked ? new Set(filtered.map(r => r.id)) : new Set())} /></th><th>{KINDS[kind]}</th><th>کد بارکد</th><th>سابقه</th></tr></thead>
            <tbody>{filtered.slice(0, 300).map(r => (
              <tr key={r.id} className="clickable" onClick={() => toggle(r.id)} data-testid="label-row" data-code={r.code}>
                <td><input type="checkbox" checked={picked.has(r.id)} onChange={() => toggle(r.id)} onClick={e => e.stopPropagation()} aria-label={r.title} /></td>
                <td>{r.title}{r.sub && <div className="text-xs text-muted">{r.sub}</div>}</td>
                <td className="font-mono text-xs ltr text-start">{r.code}</td>
                <td>{printed.has(r.id) ? <Badge tone={canReprint ? "warning" : "muted"}>{canReprint ? "چاپ‌شده — مجدد با دلیل" : "چاپ‌شده"}</Badge> : <Badge tone="success">چاپ نشده</Badge>}</td>
              </tr>
            ))}</tbody>
          </Table>
        )}
      </Card>
      <Card>
        <CardHeader title="سابقه چاپ" icon={<Printer className="size-4" />} />
        {!history.data?.length ? <EmptyState title="هنوز برچسبی چاپ نشده" /> : (
          <Table testId="label-history">
            <thead><tr><th>نوع</th><th>کد</th><th>نسخه</th><th>چاپ مجدد</th><th>دلیل</th><th>کاربر</th><th>زمان</th></tr></thead>
            <tbody>{history.data.map(h => (
              <tr key={h.id}>
                <td>{KINDS[h.label_type as Kind]}</td><td className="font-mono text-xs ltr text-start">{h.target_code}</td>
                <td className="tnum">{faNumber(h.copies)}</td><td>{h.is_reprint ? <Badge tone="warning">بله</Badge> : "—"}</td>
                <td className="max-w-56 text-xs text-text-2">{h.reason ?? "—"}</td><td className="text-xs">{h.printed_by ?? "—"}</td>
                <td className="whitespace-nowrap text-xs text-text-2">{faDateTime(h.printed_at)}</td>
              </tr>
            ))}</tbody>
          </Table>
        )}
      </Card>
    </>
  );
}
