/**
 * جستجوی سراسری (Ctrl+K یا «/»): سفارش، کالا، محموله، انتقال، تیکت، راننده و خودرو در یک ورودی.
 * نتایج گروه‌بندی‌شده‌اند؛ اگر ورودی دقیقاً یک شناسه باشد (کد رهگیری، بارکد، پلاک، …) Enter مستقیم به همان رکورد می‌رود.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import { Boxes, CornerDownLeft, Building2, LifeBuoy, Package, Search, Truck, UserRound, Warehouse, ArrowLeftRight, type LucideIcon } from "lucide-react";
import { api, unwrap, type Schemas } from "@/api/client";
import { Tooltip } from "@/ui/overlays";
import { Button, Spinner, cn } from "@/ui/primitives";

type Hit = Schemas["SearchHit"];

const ICONS: Record<string, LucideIcon> = {
  order: Package, product: Boxes, shipment: Truck, transfer: ArrowLeftRight, ticket: LifeBuoy, driver: UserRound,
  vehicle: Truck, organization: Building2,
};

function useDebounced(value: string, ms = 250) {
  const [v, setV] = useState(value);
  useEffect(() => { const t = window.setTimeout(() => setV(value), ms); return () => window.clearTimeout(t); }, [value, ms]);
  return v;
}

/** میان‌بر در هر صفحه: Ctrl/⌘+K همیشه، «/» وقتی فوکوس در فیلد متنی نیست */
function useShortcut(open: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing = !!target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); open(); }
      else if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); open(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
}

export function GlobalSearch() {
  const [open, setOpen] = useState(false);
  useShortcut(() => setOpen(true));
  return (
    <>
      <Tooltip content="جستجو (Ctrl+K)">
        <Button variant="ghost" size="icon" className="size-11 lg:size-10" onClick={() => setOpen(true)} aria-label="جستجوی سراسری" data-testid="search-open">
          <Search className="size-5" />
        </Button>
      </Tooltip>
      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50 backdrop-blur-[2px] data-[state=open]:animate-fade" />
          <Dialog.Content dir="rtl" data-testid="search-dialog" aria-describedby={undefined}
            className="fixed inset-x-3 top-[8dvh] z-50 mx-auto flex max-h-[80dvh] max-w-xl flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-float data-[state=open]:animate-[rise_.2s_cubic-bezier(.2,.7,.2,1)]">
            <Dialog.Title className="sr-only">جستجوی سراسری</Dialog.Title>
            {open && <SearchBody onDone={() => setOpen(false)} />}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}

function SearchBody({ onDone }: { onDone: () => void }) {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const q = useDebounced(text.trim());
  const result = useQuery({
    queryKey: ["global-search", q],
    queryFn: () => unwrap(api.GET("/search", { params: { query: { q } } })),
    enabled: q.length >= 2,
    placeholderData: keepPreviousData,
    staleTime: 10_000,
  });
  const data = q.length >= 2 ? result.data : undefined;
  const flat = useMemo(() => {
    const hits: (Hit & { type: string })[] = [];
    if (data?.exact) hits.push({ ...data.exact, type: "exact" });
    for (const g of data?.groups ?? []) for (const h of g.hits) if (!(data?.exact && h.link === data.exact.link)) hits.push({ ...h, type: g.type });
    return hits;
  }, [data]);

  useEffect(() => setActive(0), [data]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const go = (hit: Hit) => { onDone(); navigate(hit.link); };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(i => Math.min(i + 1, Math.max(flat.length - 1, 0))); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(i => Math.max(i - 1, 0)); }
    else if (e.key === "Enter" && flat[active]) { e.preventDefault(); go(flat[active]); }
  };

  let index = -1;
  const row = (hit: Hit, type: string) => {
    index += 1;
    const i = index;
    const Icon = ICONS[type] ?? Warehouse;
    return (
      <button key={`${type}-${hit.id}-${hit.link}`} type="button" data-index={i} role="option" aria-selected={active === i}
        onMouseMove={() => setActive(i)} onClick={() => go(hit)} data-testid="search-hit"
        className={cn("flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-start transition-colors duration-150",
          active === i ? "bg-brand-soft" : "hover:bg-surface-2")}>
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-2 text-muted"><Icon className="size-4" /></span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold">{hit.label}</span>
          {hit.sub && <span className="block truncate text-xs text-muted">{hit.sub}</span>}
        </span>
        {active === i && <CornerDownLeft className="size-4 shrink-0 text-muted" />}
      </button>
    );
  };

  return (
    <>
      <div className="flex items-center gap-3 border-b border-border px-4">
        <Search className="size-5 shrink-0 text-muted" />
        <input autoFocus value={text} onChange={e => setText(e.target.value)} onKeyDown={onKey} data-testid="search-input"
          role="combobox" aria-expanded={flat.length > 0} aria-controls="search-results" aria-label="جستجو"
          placeholder="کد سفارش، کالا یا بارکد، پلاک، تیکت، راننده…"
          className="h-14 min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted" />
        {result.isFetching && <Spinner className="size-4" />}
      </div>
      <div ref={listRef} id="search-results" role="listbox" className="flex-1 overflow-y-auto p-2">
        {q.length < 2 ? (
          <p className="px-3 py-6 text-center text-sm text-muted">دست‌کم دو حرف بنویسید. با کلیدهای جهت حرکت کنید و Enter بزنید.</p>
        ) : data && flat.length === 0 ? (
          <p className="px-3 py-6 text-center text-sm text-muted" data-testid="search-empty">نتیجه‌ای پیدا نشد.</p>
        ) : data ? <>
          {data.exact && <section className="mb-1">
            <h3 className="px-3 pb-1 pt-2 text-xs font-semibold text-muted">تطابق دقیق</h3>
            {row(data.exact, data.groups.find(g => g.hits.some(h => h.link === data.exact!.link))?.type ?? "order")}
          </section>}
          {data.groups.map(g => {
            const hits = g.hits.filter(h => !(data.exact && h.link === data.exact.link));
            if (!hits.length) return null;
            return (
              <section key={g.type} className="mb-1" data-testid={`search-group-${g.type}`}>
                <h3 className="px-3 pb-1 pt-2 text-xs font-semibold text-muted">{g.title}</h3>
                {hits.map(h => row(h, g.type))}
              </section>
            );
          })}
        </> : null}
      </div>
    </>
  );
}
