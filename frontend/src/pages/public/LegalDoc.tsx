/** صفحه‌های حقوقی (قوانین، حریم خصوصی): بندهای شماره‌دار با فهرست مطالب ثابت و نشانگر بخش فعلی */
import { useEffect, useState, type ReactNode } from "react";
import { FileText, Printer } from "lucide-react";
import { cn } from "@/ui/primitives";
import { InfoLayout } from "./InfoLayout";

export type Clause = { id: string; title: string; body: ReactNode };

export const P = ({ children }: { children: ReactNode }) => <p className="leading-8 text-text-2">{children}</p>;
export const L = ({ items }: { items: ReactNode[] }) => (
  <ul className="space-y-2.5">
    {items.map((it, i) => <li key={i} className="flex gap-3 leading-8 text-text-2"><span className="mt-3 size-1.5 shrink-0 rounded-full bg-brand" />{it}</li>)}
  </ul>
);

export function LegalDoc({ clauses, title, heading, lead, updated, prefix }: {
  clauses: Clause[]; title: string; heading: ReactNode; lead: string; updated: string;
  /** پیشوند testid ها (terms-toc، terms-clause و ...) */
  prefix: string;
}) {
  const [active, setActive] = useState(clauses[0].id);

  // بخشی که در دید است در فهرست مطالب پررنگ شود
  useEffect(() => {
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(e => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (visible) setActive(visible.target.id);
    }, { rootMargin: "-20% 0px -65% 0px" });
    clauses.forEach(c => { const el = document.getElementById(c.id); if (el) observer.observe(el); });
    return () => observer.disconnect();
  }, [clauses]);

  return (
    <InfoLayout title={title} testId={`${prefix}-page`} eyebrow={title} heading={heading} lead={lead}
      hero={
        <div className="flex flex-wrap items-center gap-3 text-sm text-muted">
          <span className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3.5 py-1.5"><FileText className="size-4 text-brand" />آخرین به‌روزرسانی: {updated}</span>
          <button type="button" onClick={() => window.print()} className="inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 transition hover:bg-surface hover:text-text"><Printer className="size-4" />چاپ</button>
        </div>
      }>
      <section className="mx-auto grid max-w-7xl grid-cols-[minmax(0,1fr)] gap-12 px-4 py-16 sm:px-6 sm:py-20 lg:grid-cols-[minmax(0,1fr)_minmax(0,3fr)]">
        <nav className="hidden lg:sticky lg:top-24 lg:block lg:h-fit" aria-label="فهرست مطالب" data-testid={`${prefix}-toc`}>
          <div className="eyebrow mb-4">فهرست مطالب</div>
          <ol className="space-y-0.5 border-s border-border">
            {clauses.map((c, i) => (
              <li key={c.id}>
                <a href={`#${c.id}`} onClick={e => { e.preventDefault(); document.getElementById(c.id)?.scrollIntoView({ behavior: "smooth" }); history.replaceState(null, "", `#${c.id}`); }}
                  className={cn("-ms-px flex gap-3 border-s-2 py-1.5 ps-4 text-sm transition",
                    active === c.id ? "border-brand font-semibold text-brand" : "border-transparent text-text-2 hover:text-text")}>
                  <span className="font-mono text-xs opacity-60 tnum">{String(i + 1).padStart(2, "0")}</span>{c.title}
                </a>
              </li>
            ))}
          </ol>
        </nav>
        <article className="max-w-3xl space-y-14">
          {clauses.map((c, i) => (
            <section key={c.id} id={c.id} className="scroll-mt-28" data-testid={`${prefix}-clause`}>
              <h2 className="mb-5 flex items-baseline gap-3 text-xl font-black tracking-tight sm:text-2xl">
                <span className="font-mono text-sm text-brand tnum">{String(i + 1).padStart(2, "0")}</span>{c.title}
              </h2>
              <div className="space-y-4">{c.body}</div>
            </section>
          ))}
        </article>
      </section>
    </InfoLayout>
  );
}
