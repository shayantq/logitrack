/** بخش‌های «چرا پسینه» (گفتگوی تیم با جواب‌های فوری ← پرونده کامل سفارش) و «انبار» (دفتر گردش زنده) */
import { useEffect, useRef, useState } from "react";
import { ArrowDownLeft, ArrowUpRight, Check, CheckCheck, Lock, MessagesSquare, RotateCcw, Truck } from "lucide-react";
import { faNumber } from "@/lib/format";
import { cn } from "@/ui/primitives";
import { Odometer, Reveal, ScrubText, SectionTag, useInView, useProgressState, useReducedMotion } from "../motion";

// ------------------------------------------------------------------ [01] چرا پسینه
// تیمی که با پسینه کار می‌کند: هر سؤال در چند ثانیه از روی پنل جواب داده می‌شود
const CHAT = [
  { me: false, text: "سفارش فروشگاه سعادت‌آباد به کجا رسید؟", time: "۰۹:۰۲" },
  { me: true, text: "تو پنل دیدم: در مسیره، حدود ۱۰:۳۰ می‌رسه 👌", time: "۰۹:۰۳" },
  { me: false, text: "عالی. موجودی دستمال کاغذی برای سفارش‌های فردا کافیه؟", time: "۰۹:۰۵" },
  { me: true, text: "۱٬۱۷۴ کارتن داریم؛ سامانه برای خرید بعدی هم یادآوری کرده", time: "۰۹:۰۶" },
  { me: false, text: "تحویل سعادت‌آباد ثبت شد؟", time: "۱۰:۳۹" },
  { me: true, text: "بله، ۱۰:۳۸ تحویل شد و مشتری ۵ ستاره داد ⭐", time: "۱۰:۴۰" },
];
const RECORD = [
  ["کد رهگیری", "LT-2481-K7", true],
  ["وضعیت", "در مسیر مقصد", false],
  ["خودرو / راننده", "۲۲ ع ۳۴۵ ایران ۱۰ · D-07", false],
  ["اقلام", "۳ کارتن · ۴۲ کیلوگرم", false],
  ["بازه تحویل", "امروز ۱۰ تا ۱۲", false],
  ["آخرین تغییر", "۱۰:۰۵ — توسط راننده", false],
] as const;

export function ProblemSection() {
  const section = useRef<HTMLElement>(null);
  const reduced = useReducedMotion();
  const p = useProgressState(section, { smooth: 0.5, start: "top top", end: "bottom bottom", disabled: reduced });
  const swap = p > 0.55;

  return (
    <section ref={section} id="problem" data-section="چرا پسینه؟" className={cn("relative", reduced ? "" : "h-[280vh]")}>
      {/* موبایل: فاصله‌ها و ارتفاع گفتگو کمتر تا کل بخش در یک صفحه جا شود و زیر سربرگ نرود */}
      <div className={cn("flex min-h-svh items-center pb-8 pt-20 lg:py-24", !reduced && "sticky top-0 h-svh")}>
        <div className="mx-auto grid w-full max-w-7xl items-center gap-6 px-4 sm:px-6 lg:grid-cols-2 lg:gap-16">
          <div>
            <SectionTag label="چرا پسینه؟" />
            <h2 className="text-3xl font-black leading-tight tracking-tight sm:text-5xl">
              {swap ? <span key="b" className="animate-rise block">یک سفارش،<br /><span className="text-brand">یک پرونده کامل.</span></span>
                : <span key="a" className="animate-rise block">هر سؤال تیم،<br /><span className="text-brand">جوابش آماده است.</span></span>}
            </h2>
            <p className="mt-4 max-w-lg text-base leading-7 text-text-2 sm:mt-6 sm:text-lg sm:leading-8">
              {swap
                ? "کد رهگیری، وضعیت، خودرو، راننده و تاریخچه هر سفارش در یک جاست و همه اعضای تیم همان اطلاعات به‌روز را می‌بینند."
                : "وقتی سفارش، موجودی و رانندگان در یک سامانه ثبت می‌شوند، تیم شما به‌جای تماس و پیگیری، جواب را همان لحظه در پنل می‌بیند."}
            </p>
            <div className="mt-5 flex gap-6 text-sm sm:mt-8 [@media(max-height:700px)]:hidden">
              <span className={cn("flex items-center gap-2 transition-colors", swap ? "text-muted" : "font-semibold text-brand")}><MessagesSquare className="size-4" />هماهنگی سریع تیم</span>
              <span className={cn("flex items-center gap-2 transition-colors", swap ? "font-semibold text-brand" : "text-muted")}><CheckCheck className="size-4" />پرونده کامل سفارش</span>
            </div>
          </div>

          <div className="relative mx-auto h-[max(220px,40svh)] w-full max-w-md sm:h-[440px]" data-testid="problem-visual">
            {/* گفتگوی تیم: پیام‌ها مثل پیام‌رسان واقعی از پایین اضافه و قدیمی‌ها به بالا رانده می‌شوند —
                هیچ‌وقت از کارت بیرون نمی‌زنند (قبلاً پیام آخر از لبه پایین کارت بیرون می‌افتاد) */}
            <div data-testid="problem-chat" className={cn("absolute inset-0 flex flex-col overflow-hidden rounded-[28px] border border-border bg-surface p-4 shadow-[var(--shadow-lg)] transition-all duration-700",
              swap && "-rotate-3 scale-90 opacity-30 blur-[2px]")}>
              <div className="mb-3 flex shrink-0 items-center gap-3 border-b border-border pb-3">
                <div className="grid size-9 place-items-center rounded-full bg-brand-soft text-sm">📦</div>
                <div className="min-w-0"><div className="truncate text-sm font-bold">تیم عملیات پخش</div><div className="flex items-center gap-1 truncate text-xs text-success"><CheckCheck className="size-3.5" />همه پیام‌ها پاسخ داده شد</div></div>
              </div>
              <div className="relative min-h-0 flex-1 overflow-hidden [mask-image:linear-gradient(to_bottom,transparent,black_14%)]">
                <div className="absolute inset-x-0 bottom-0 space-y-2">
                  {CHAT.map((m, i) => {
                    const shown = reduced || p > 0.04 + i * 0.075;
                    return (
                      <div key={i} className={cn("grid transition-all duration-500", shown ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0")}>
                        <div className={cn("flex min-h-0 overflow-hidden", m.me ? "justify-start" : "justify-end")}>
                          <div className={cn("max-w-[82%] break-words rounded-2xl px-3 py-2 text-sm leading-6", m.me ? "rounded-tr-sm bg-brand-soft text-text" : "rounded-tl-sm bg-surface-2 text-text")}>
                            {m.text}<div className="mt-0.5 text-left text-[11px] text-muted">{m.time}</div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
            {/* سابقه ساختاریافته */}
            <div className={cn("absolute inset-x-2 top-3 overflow-hidden rounded-3xl border border-border bg-surface shadow-[var(--shadow-lg)] transition-all duration-700 sm:top-8",
              swap ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-10 opacity-0")}>
              <div className="flex items-center justify-between border-b border-border px-5 py-3 sm:py-4">
                <span className="flex items-center gap-2 font-bold"><Truck className="size-5 text-brand" />سفارش</span>
                <span className="rounded-full bg-brand-soft px-2.5 py-1 text-xs font-semibold text-brand-strong">در مسیر</span>
              </div>
              <dl className="divide-y divide-border">
                {RECORD.map(([k, v, mono], i) => (
                  <div key={k} className={cn("flex items-center justify-between gap-3 px-5 py-2 text-sm transition-all duration-500 sm:py-3",
                    reduced || p > 0.6 + i * 0.05 ? "opacity-100" : "opacity-0")}>
                    <dt className="text-muted">{k}</dt>
                    <dd className={cn("font-semibold", mono && "font-mono ltr")}>{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ [02] انبار
type Move = { id: number; type: keyof typeof MOVE_STYLE; product: string; qty: number; who: string };
const MOVE_STYLE = {
  receipt: { label: "ورود کالا", icon: ArrowDownLeft, cls: "bg-success-soft text-success" },
  order_out: { label: "خروج بابت سفارش", icon: ArrowUpRight, cls: "bg-info-soft text-info" },
  order_return: { label: "برگشت از سفارش", icon: RotateCcw, cls: "bg-brand-soft text-brand-strong" },
};
const SCRIPT: Omit<Move, "id">[] = [
  { type: "order_out", product: "کارتن دستمال کاغذی", qty: -12, who: "سفارش LT-2481" },
  { type: "receipt", product: "کارتن دستمال کاغذی", qty: 60, who: "انباردار — رسید ۴۴۱" },
  { type: "order_out", product: "کارتن دستمال کاغذی", qty: -8, who: "سفارش LT-2486" },
  { type: "order_return", product: "کارتن دستمال کاغذی", qty: 8, who: "لغو LT-2486" },
  { type: "order_out", product: "کارتن دستمال کاغذی", qty: -20, who: "سفارش LT-2490" },
  { type: "order_out", product: "کارتن دستمال کاغذی", qty: -5, who: "سفارش LT-2493" },
];

export function InventorySection() {
  const card = useRef<HTMLDivElement>(null);
  const inView = useInView(card);
  const reduced = useReducedMotion();
  const [moves, setMoves] = useState<Move[]>(() => SCRIPT.slice(0, 3).map((m, i) => ({ ...m, id: i })).reverse());
  const [stock, setStock] = useState(1240);
  const next = useRef(3);

  useEffect(() => {
    if (!inView || reduced) return;
    const timer = setInterval(() => {
      const m = SCRIPT[next.current % SCRIPT.length];
      setMoves(list => [{ ...m, id: next.current }, ...list].slice(0, 5));
      setStock(s => s + m.qty);
      next.current += 1;
    }, 2400);
    return () => clearInterval(timer);
  }, [inView, reduced]);

  return (
    <section id="inventory" data-section="انبار" className="relative overflow-hidden py-28 sm:py-36">
      <div className="mx-auto grid max-w-7xl items-center gap-14 px-4 sm:px-6 lg:grid-cols-2">
        <div>
          <SectionTag label="انبار" />
          <ScrubText className="text-3xl font-black leading-tight tracking-tight sm:text-5xl" text="موجودی انبار، همیشه دقیق." />
          <Reveal className="mt-8 space-y-5">
            {[
              [Lock, "هر تغییر، ثبت و ماندگار", "هر ورود و خروج کالا با علت، مقدار و نام ثبت‌کننده در دفتر گردش می‌ماند."],
              [ArrowUpRight, "هماهنگ با سفارش‌ها", "ثبت سفارش موجودی را کم می‌کند و لغو آن، کالا را خودکار به انبار برمی‌گرداند."],
              [Check, "چند انبار، یک نگاه", "موجودی همه انبارها یک‌جا، با هشدار خودکار وقتی کالایی رو به اتمام است."],
            ].map(([Icon, title, text]) => {
              const I = Icon as typeof Lock;
              return (
                <div key={title as string} className="flex gap-4">
                  <div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-brand-soft text-brand"><I className="size-5" /></div>
                  <div><h3 className="font-bold">{title as string}</h3><p className="mt-1 leading-7 text-text-2">{text as string}</p></div>
                </div>
              );
            })}
          </Reveal>
        </div>

        <div ref={card} className="card overflow-hidden" data-testid="ledger-demo">
          <div className="flex flex-wrap items-end justify-between gap-4 border-b border-border p-6">
            <div>
              <div className="text-sm text-muted">کارتن دستمال کاغذی · انبار مرکزی</div>
              <div className="mt-2 flex items-baseline gap-2 text-5xl font-black tracking-tight">
                <Odometer value={stock} minDigits={4} /><span className="text-base font-medium text-muted">عدد</span>
              </div>
            </div>
            <span className="flex items-center gap-2 rounded-full bg-success-soft px-3 py-1.5 text-xs font-semibold text-success"><span className="live-dot" />زنده</span>
          </div>
          <ul className="divide-y divide-border">
            {moves.map(m => {
              const style = MOVE_STYLE[m.type];
              return (
                <li key={m.id} className="flex animate-rise items-center gap-3 px-6 py-3.5">
                  <span className={cn("grid size-9 place-items-center rounded-xl", style.cls)}><style.icon className="size-4" /></span>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold">{style.label}</div>
                    <div className="truncate text-xs text-muted">{m.who}</div>
                  </div>
                  <span className={cn("font-mono text-sm font-bold ltr tnum", m.qty > 0 ? "text-success" : "text-info")}>{m.qty > 0 ? "+" : "−"}{faNumber(Math.abs(m.qty))}</span>
                </li>
              );
            })}
          </ul>
          <div className="border-t border-border bg-surface-2 px-6 py-3 text-sm text-text-2">هیچ عددی دستی عوض نمی‌شود؛ هر اصلاح هم یک ردیف جدید است.</div>
        </div>
      </div>
    </section>
  );
}

