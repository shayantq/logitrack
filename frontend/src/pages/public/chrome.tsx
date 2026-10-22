/** سربرگ و پانویس صفحات عمومی */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { ArrowLeft, LogIn, Menu as MenuIcon, PackageSearch, X } from "lucide-react";
import { BRAND } from "@/brand";
import { Logo, ThemeToggle } from "@/ui/brand";
import { buttonClass, cn } from "@/ui/primitives";
import { ScrollTrigger, gsap, useReducedMotion } from "./motion";

/** صفحه‌های اطلاع‌رسانی (جدا از بخش‌های صفحه اصلی) */
export const SITE_PAGES = [
  { to: "/about", label: "درباره ما" },
  { to: "/pricing", label: "تعرفه‌ها" },
  { to: "/faq", label: "سوالات متداول" },
  { to: "/terms", label: "قوانین و مقررات" },
  { to: "/privacy", label: "حریم خصوصی" },
];

export const LANDING_NAV = [
  { href: "#problem", label: "چرا پسینه؟" },
  { href: "#inventory", label: "انبار" },
  { href: "#product", label: "محصول" },
  { href: "#how", label: "شروع کار" },
  { href: "#faq", label: "پرسش‌ها" },
];

/**
 * سربرگ ثابت: نام بخش فعلی (از data-section بخش‌ها) و نوار پیشرفت اسکرول.
 * در صفحات دیگر (مثل فرم درخواست) فقط لوگو و دکمه‌ها نمایش داده می‌شود.
 */
export function PublicHeader({ landing = false }: { landing?: boolean }) {
  const bar = useRef<HTMLDivElement>(null);
  const [section, setSection] = useState<string | null>(null);
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      ScrollTrigger.create({
        start: 0, end: "max",
        onUpdate: self => {
          if (bar.current) bar.current.style.transform = `scaleX(${self.progress})`;
          setScrolled(self.scroll() > 24);
        },
      });
      if (!landing) return;
      document.querySelectorAll<HTMLElement>("[data-section]").forEach(el => {
        ScrollTrigger.create({
          trigger: el, start: "top 45%", end: "bottom 45%",
          onToggle: self => { if (self.isActive) setSection(el.dataset.section ?? null); },
        });
      });
    });
    return () => ctx.revert();
  }, [landing]);

  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener("hashchange", close);
    return () => window.removeEventListener("hashchange", close);
  }, [open]);

  return (
    <header className={cn("fixed inset-x-0 top-0 z-50 transition-colors duration-300",
      scrolled || open ? "border-b border-border bg-bg/80 backdrop-blur-xl" : "border-b border-transparent")}>
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6">
        <Link to="/" aria-label={BRAND.name}><Logo /></Link>
        {landing && (
          <div className="hidden min-w-0 items-center gap-2 text-sm text-muted md:flex" data-testid="section-indicator">
            <span className="live-dot" />
            <SectionName key={section} value={section ?? "سفر یک سفارش"} />
          </div>
        )}
        <nav className={cn("hidden items-center gap-1", landing ? "ms-auto lg:flex" : "ms-auto md:flex")}>
          {landing && LANDING_NAV.map(n => (
            <a key={n.href} href={n.href} className="rounded-lg px-3 py-2 text-sm text-text-2 transition hover:bg-surface-2 hover:text-text">{n.label}</a>
          ))}
          {landing && <Link to="/pricing" className="rounded-lg px-3 py-2 text-sm text-text-2 transition hover:bg-surface-2 hover:text-text" data-testid="nav-pricing-landing">تعرفه‌ها</Link>}
          {!landing && SITE_PAGES.slice(0, 2).map(p => (
            <NavLink key={p.to} to={p.to} data-testid={`nav-${p.to.slice(1)}`}
              className={({ isActive }) => cn("rounded-lg px-3 py-2 text-sm transition hover:bg-surface-2 hover:text-text", isActive ? "font-semibold text-brand" : "text-text-2")}>{p.label}</NavLink>
          ))}
        </nav>
        <div className={cn("flex items-center gap-1.5", landing ? "ms-auto lg:ms-2" : "ms-auto md:ms-2")}>
          <ThemeToggle />
          {/* نمایش/عدم نمایش روی والد، تا با display خودِ دکمه تداخل نکند */}
          {/* پیگیری سفارش روی موبایل هم همیشه در دسترس است (بیشتر مشتری‌ها با گوشی می‌آیند) */}
          <Link to="/track" className={buttonClass("ghost", "md", "px-2.5 sm:px-4")} data-testid="nav-track" aria-label="پیگیری سفارش">
            <PackageSearch className="size-4" /><span className="hidden sm:inline">پیگیری سفارش</span>
          </Link>
          <div className="hidden items-center gap-1.5 sm:flex">
            <Link to="/app/login" className={buttonClass("ghost")}><LogIn className="size-4" />ورود</Link>
            <Link to="/request?plan=trial" className={buttonClass("primary")} data-testid="cta-request">شروع رایگان<ArrowLeft className="size-4" /></Link>
          </div>
          <div className="sm:hidden">
            <button className={buttonClass("ghost", "icon")} onClick={() => setOpen(o => !o)} aria-label="منو" data-testid="mobile-menu">
              {open ? <X className="size-5" /> : <MenuIcon className="size-5" />}
            </button>
          </div>
        </div>
      </div>
      {open && (
        <div className="border-t border-border px-4 pb-5 pt-3 sm:hidden">
          {landing && LANDING_NAV.map(n => <a key={n.href} href={n.href} onClick={() => setOpen(false)} className="block rounded-lg px-3 py-2.5 text-text-2 hover:bg-surface-2">{n.label}</a>)}
          <Link to="/track" className="block rounded-lg px-3 py-2.5 text-text-2 hover:bg-surface-2">پیگیری سفارش</Link>
          {SITE_PAGES.map(p => <Link key={p.to} to={p.to} onClick={() => setOpen(false)} className="block rounded-lg px-3 py-2.5 text-text-2 hover:bg-surface-2">{p.label}</Link>)}
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Link to="/app/login" className={buttonClass("secondary")}>ورود</Link>
            <Link to="/request?plan=trial" className={buttonClass("primary")}>شروع رایگان</Link>
          </div>
        </div>
      )}
      <div ref={bar} className="absolute inset-x-0 bottom-0 h-0.5 origin-right scale-x-0 bg-linear-to-l from-brand to-accent" />
    </header>
  );
}

/** «[02] انبار» ← شماره با فونت مونو، نام با فونت فارسی (فاصله بین حروف، اتصال حروف فارسی را می‌شکند) */
function SectionName({ value }: { value: string }) {
  return <span className="animate-rise truncate font-medium text-text-2">{value}</span>;
}

/**
 * پانویس با نام بزرگ برند که هم‌زمان با رسیدن به انتهای صفحه، از چپ به راست پر می‌شود.
 * پیشرفت مستقیم از فاصله تا انتهای صفحه حساب می‌شود (نه موقعیت‌های ذخیره‌شده ScrollTrigger که با تغییر
 * چیدمان صفحه کهنه می‌شدند و باعث می‌شد نوشته تا آخرین لحظه خالی بماند و یک‌باره پر شود).
 */
export function PublicFooter() {
  const word = useRef<HTMLSpanElement>(null);
  const reduced = useReducedMotion();
  useEffect(() => {
    const el = word.current;
    if (!el) return;
    if (reduced) { el.style.clipPath = "none"; return; }
    let frame = 0;
    const update = () => {
      frame = 0;
      const vh = window.innerHeight;
      const top = el.getBoundingClientRect().top;
      // چند پیکسل آخر (اسکرول کسری مرورگرها) = انتهای صفحه، تا نوشته در انتها کامل پر شود
      const left = document.documentElement.scrollHeight - vh - window.scrollY;
      const remaining = left < 3 ? 0 : left;
      const range = vh - (top - remaining);          // مسافت اسکرول از ورود نوشته به صفحه تا انتهای صفحه
      let p: number;
      if (range < 80) p = top < vh ? 1 : 0;          // صفحه کوتاه: نوشته از اول در دید است ← یک‌باره و نرم پر شود
      else p = Math.min(1, Math.max(0, (vh - top) / range));
      el.dataset.progress = p.toFixed(2);
      el.style.transitionDuration = range < 80 ? "1.2s" : "";
      el.style.clipPath = `inset(-10% ${((1 - p) * 100).toFixed(2)}% -10% 0)`;
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(update); };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    const resize = new ResizeObserver(schedule);
    resize.observe(document.body);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      resize.disconnect();
    };
  }, [reduced]);

  return (
    <footer className="relative overflow-hidden border-t border-border bg-bg-2">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-14 sm:grid-cols-3 sm:px-6 lg:grid-cols-5">
        <div className="sm:col-span-3 lg:col-span-2">
          <Logo />
          <p className="mt-4 max-w-sm text-sm leading-7 text-muted">{BRAND.nameFa} — {BRAND.tagline}. سامانه‌ای برای ثبت سفارش، مدیریت موجودی انبار، ناوگان و رانندگان، در یک جای واحد.</p>
        </div>
        <div>
          <div className="eyebrow mb-4">صفحه‌ها</div>
          <ul className="space-y-2.5 text-sm text-text-2">
            {LANDING_NAV.map(n => <li key={n.href}><a href={`/${n.href}`} className="inline-block py-1 hover:text-brand">{n.label}</a></li>)}
          </ul>
        </div>
        <div>
          <div className="eyebrow mb-4">{BRAND.nameFa}</div>
          <ul className="space-y-2.5 text-sm text-text-2" data-testid="footer-site-pages">
            {SITE_PAGES.map(p => <li key={p.to}><Link to={p.to} className="inline-block py-1 hover:text-brand">{p.label}</Link></li>)}
          </ul>
        </div>
        <div>
          <div className="eyebrow mb-4">شروع</div>
          <ul className="space-y-2.5 text-sm text-text-2">
            <li><Link to="/request" className="inline-block py-1 hover:text-brand">درخواست دسترسی سازمان</Link></li>
            <li><Link to="/track" className="inline-block py-1 hover:text-brand">پیگیری سفارش</Link></li>
            <li><Link to="/request#status" className="inline-block py-1 hover:text-brand">پیگیری درخواست سازمان</Link></li>
            <li><Link to="/app/login" className="inline-block py-1 hover:text-brand">ورود به پنل</Link></li>
            <li><a href={`mailto:${BRAND.supportEmail}`} className="inline-block py-1 font-mono text-xs hover:text-brand ltr">{BRAND.supportEmail}</a></li>
            <li><a href={`tel:${BRAND.phone}`} className="inline-block py-1 hover:text-brand" data-testid="footer-phone">{BRAND.phoneDisplay}</a></li>
          </ul>
        </div>
      </div>
      <div className="relative mx-auto max-w-7xl select-none px-4 sm:px-6" aria-hidden="true">
        <div className="relative -mb-[0.18em] text-[17vw] font-black leading-[1.15] tracking-tighter ltr xl:text-[15rem]">
          <span className="block text-transparent [-webkit-text-stroke:1px_var(--border-strong)]">{BRAND.name.toUpperCase()}</span>
          <span ref={word} data-testid="footer-wordmark" style={{ clipPath: "inset(-10% 100% -10% 0)" }}
            className="absolute inset-0 block bg-linear-to-r from-brand via-brand to-accent bg-clip-text text-transparent transition-[clip-path] duration-300 ease-out">{BRAND.name.toUpperCase()}</span>
        </div>
      </div>
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-6 text-xs text-muted sm:px-6">
        <span>© {new Date().getFullYear()} {BRAND.name}</span>
        <span className="font-mono">v2 · multi-tenant</span>
      </div>
    </footer>
  );
}
