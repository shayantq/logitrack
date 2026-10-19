/** صفحه «سوالات متداول»: دسته‌بندی، جست‌وجو و لینک مستقیم به هر پرسش (/faq#q-<id>) */
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import * as Accordion from "@radix-ui/react-accordion";
import { ChevronDown, Link2, Search, SearchX, X } from "lucide-react";
import { BRAND } from "@/brand";
import { faNumber } from "@/lib/format";
import { cn } from "@/ui/primitives";
import { useToast } from "@/components/Toast";
import { FAQ_CATEGORIES, type FaqItem } from "./content/faq";
import { InfoLayout } from "./InfoLayout";

/** یکسان‌سازی متن فارسی برای جست‌وجو (ی/ک عربی، نیم‌فاصله، اعراب) */
const norm = (s: string) => s.toLowerCase()
  .replace(/[يى]/g, "ی").replace(/ك/g, "ک").replace(/[‌‍ً-ٟ]/g, " ").replace(/\s+/g, " ").trim();

export default function FaqPage() {
  const { hash } = useLocation();
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [open, setOpen] = useState<string[]>([]);

  // لینک مستقیم به یک پرسش: همان را باز و به آن اسکرول کن
  useEffect(() => {
    const id = hash.startsWith("#q-") ? hash.slice(3) : null;
    if (!id) return;
    // فیلتر/جست‌وجوی فعلی نباید پرسش مقصد را پنهان کند
    setQuery(""); setCategory(null);
    setOpen(o => (o.includes(id) ? o : [...o, id]));
    requestAnimationFrame(() => document.getElementById(`q-${id}`)?.scrollIntoView({ block: "center" }));
  }, [hash]);

  const terms = norm(query).split(" ").filter(Boolean);
  const matches = (item: FaqItem) => terms.every(t => norm(`${item.q} ${item.a}`).includes(t));
  const groups = useMemo(() => FAQ_CATEGORIES
    .filter(c => !category || c.id === category)
    .map(c => ({ ...c, items: c.items.filter(matches) }))
    .filter(c => c.items.length > 0),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [query, category]);
  const total = groups.reduce((n, c) => n + c.items.length, 0);
  const allCount = FAQ_CATEGORIES.reduce((n, c) => n + c.items.length, 0);

  const copyLink = (id: string) => {
    const url = `${location.origin}/faq#q-${id}`;
    navigator.clipboard?.writeText(url).then(() => toast.success("لینک این پرسش کپی شد."), () => {});
  };

  return (
    <InfoLayout title="سوالات متداول" testId="faq-page" eyebrow="سوالات متداول"
      heading={<>هر سؤالی درباره {BRAND.nameFa} دارید،<br className="hidden sm:block" /> احتمالاً پاسخش این‌جاست.</>}
      lead={`${faNumber(allCount)} پرسش پرتکرار سازمان‌ها، از ثبت درخواست تا کمیسیون رانندگان و امنیت داده‌ها.`}
      hero={
        <label className="relative block max-w-xl">
          <Search className="pointer-events-none absolute start-4 top-1/2 size-5 -translate-y-1/2 text-muted" />
          <input value={query} onChange={e => setQuery(e.target.value)} placeholder="جست‌وجو در پرسش‌ها؛ مثلاً «کمیسیون» یا «مدارک»"
            className="h-14 w-full rounded-2xl border border-border-strong bg-surface pe-12 ps-12 text-base shadow-[var(--shadow)] outline-none transition focus:border-brand focus:ring-4 focus:ring-brand/15"
            data-testid="faq-search" />
          {query && (
            <button type="button" onClick={() => setQuery("")} aria-label="پاک کردن" className="absolute end-3 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-text">
              <X className="size-4" />
            </button>
          )}
        </label>
      }>
      <section className="mx-auto grid max-w-7xl grid-cols-[minmax(0,1fr)] gap-10 px-4 py-16 sm:px-6 sm:py-20 lg:grid-cols-[minmax(0,1fr)_minmax(0,3fr)]">
        {/* دسته‌ها: روی دسکتاپ کنار صفحه ثابت، روی موبایل نوار افقی قابل اسکرول */}
        <aside className="min-w-0 lg:sticky lg:top-24 lg:h-fit">
          <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-2 lg:mx-0 lg:flex-col lg:overflow-visible lg:px-0" data-testid="faq-categories">
            <CategoryButton active={!category} onClick={() => setCategory(null)} label="همه پرسش‌ها" count={allCount} />
            {FAQ_CATEGORIES.map(c => (
              <CategoryButton key={c.id} active={category === c.id} onClick={() => setCategory(category === c.id ? null : c.id)}
                label={c.title} count={c.items.length} icon={<c.icon className="size-4" />} id={c.id} />
            ))}
          </div>
        </aside>

        <div className="min-w-0">
          {query && <p className="mb-6 text-sm text-muted" data-testid="faq-result-count">{total ? `${faNumber(total)} پرسش پیدا شد` : ""}</p>}
          {total === 0 ? (
            <div className="card animate-fade flex flex-col items-center gap-3 px-6 py-14 text-center" data-testid="faq-empty">
              <span className="grid size-12 place-items-center rounded-2xl bg-surface-2 text-muted"><SearchX className="size-6" /></span>
              <div className="font-bold">پرسشی با این عبارت پیدا نشد</div>
              <p className="max-w-sm text-sm leading-7 text-text-2">
                عبارت دیگری را امتحان کنید، یا سؤالتان را به <a href={`mailto:${BRAND.supportEmail}`} className="font-mono text-brand ltr">{BRAND.supportEmail}</a> بفرستید.
              </p>
            </div>
          ) : (
            <Accordion.Root type="multiple" value={open} onValueChange={setOpen} dir="rtl" className="space-y-12">
              {groups.map(c => (
                <div key={c.id} className="animate-fade">
                  <div className="mb-4 flex items-center gap-3" id={`cat-${c.id}`}>
                    <span className="grid size-10 place-items-center rounded-xl bg-brand-soft text-brand"><c.icon className="size-5" /></span>
                    <h2 className="text-xl font-black tracking-tight sm:text-2xl">{c.title}</h2>
                  </div>
                  <div className="divide-y divide-border rounded-2xl border border-border bg-surface px-5 sm:px-6">
                    {c.items.map(item => (
                      <Accordion.Item key={item.id} value={item.id} id={`q-${item.id}`} className="scroll-mt-28" data-testid="faq-item">
                        <Accordion.Header className="flex items-center gap-2">
                          <Accordion.Trigger className="group flex flex-1 items-center gap-4 py-5 text-right font-bold leading-7 transition hover:text-brand data-[state=open]:text-brand">
                            <span className="flex-1">{item.q}</span>
                            <ChevronDown className="size-5 shrink-0 text-muted transition-transform duration-300 group-data-[state=open]:rotate-180" />
                          </Accordion.Trigger>
                        </Accordion.Header>
                        <Accordion.Content className="accordion-content overflow-hidden">
                          <p className="pb-4 leading-8 text-text-2">{item.a}</p>
                          <button type="button" onClick={() => copyLink(item.id)} className="mb-5 inline-flex items-center gap-1.5 text-xs text-muted transition hover:text-brand">
                            <Link2 className="size-3.5" />کپی لینک این پرسش
                          </button>
                        </Accordion.Content>
                      </Accordion.Item>
                    ))}
                  </div>
                </div>
              ))}
            </Accordion.Root>
          )}
          <p className="mt-12 text-sm leading-7 text-muted">
            برای جزئیات حقوقی، <Link to="/terms" className="font-medium text-brand hover:underline">قوانین و مقررات</Link> و برای آشنایی بیشتر با ما، صفحه <Link to="/about" className="font-medium text-brand hover:underline">درباره ما</Link> را ببینید.
          </p>
        </div>
      </section>
    </InfoLayout>
  );
}

function CategoryButton({ active, onClick, label, count, icon, id }: { active: boolean; onClick: () => void; label: string; count: number; icon?: React.ReactNode; id?: string }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active} data-category={id ?? "all"}
      className={cn("flex shrink-0 items-center gap-2.5 rounded-xl px-3.5 py-2.5 text-sm transition lg:w-full",
        active ? "bg-brand text-brand-ink shadow-sm" : "bg-surface-2 text-text-2 hover:bg-surface hover:text-text lg:bg-transparent")}>
      {icon}<span className="whitespace-nowrap">{label}</span>
      <span className={cn("ms-auto rounded-md px-1.5 font-mono text-[11px] tnum", active ? "bg-white/20" : "bg-surface text-muted")}>{faNumber(count)}</span>
    </button>
  );
}
