/** قالب مشترک صفحه‌های اطلاع‌رسانی (درباره ما، سوالات متداول، قوانین): سربرگ، بخش آغازین، محتوا، دعوت پایانی و پانویس */
import { useEffect, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Mail, Phone } from "lucide-react";
import { BRAND } from "@/brand";
import { buttonClass } from "@/ui/primitives";
import { PublicFooter, PublicHeader } from "./chrome";

export function InfoLayout({ title, eyebrow, heading, lead, children, testId, cta = true, hero }: {
  title: string; eyebrow: string; heading: ReactNode; lead: ReactNode; children: ReactNode; testId: string;
  /** نوار دعوت پایانی */
  cta?: boolean;
  /** محتوای اضافه زیر متن آغازین (مثل جست‌وجو) */
  hero?: ReactNode;
}) {
  useEffect(() => { document.title = `${title} — ${BRAND.nameFa}`; }, [title]);
  return (
    <div className="min-h-svh bg-bg text-text" data-testid={testId}>
      <PublicHeader />
      <main>
        <section className="relative overflow-hidden border-b border-border bg-bg-2 pb-16 pt-32 sm:pb-20 sm:pt-40">
          <HeroBackdrop />
          <div className="stagger relative mx-auto max-w-7xl px-4 sm:px-6">
            <div className="eyebrow mb-5">{eyebrow}</div>
            <h1 className="max-w-3xl text-4xl font-black leading-[1.2] tracking-tight sm:text-6xl">{heading}</h1>
            <p className="mt-6 max-w-2xl text-lg leading-9 text-text-2">{lead}</p>
            {hero && <div className="mt-8">{hero}</div>}
          </div>
        </section>
        {children}
        {cta && <ContactStrip />}
      </main>
      <PublicFooter />
    </div>
  );
}

/** شبکه محو و مسیر نقطه‌چین متحرک — همان زبان تصویری صفحه اصلی */
function HeroBackdrop() {
  return (
    <svg className="pointer-events-none absolute inset-0 size-full text-brand" aria-hidden="true">
      <defs>
        <pattern id="info-grid" width="56" height="56" patternUnits="userSpaceOnUse">
          <path d="M56 0H0v56" fill="none" stroke="currentColor" strokeWidth="1" opacity=".07" />
        </pattern>
        <linearGradient id="info-fade" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="white" stopOpacity="1" /><stop offset="1" stopColor="white" stopOpacity="0" />
        </linearGradient>
        <mask id="info-mask"><rect width="100%" height="100%" fill="url(#info-fade)" /></mask>
      </defs>
      <rect width="100%" height="100%" fill="url(#info-grid)" mask="url(#info-mask)" />
      <path d="M-40 300 C 220 300, 300 150, 560 170 S 900 320, 1600 110" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="8 12" opacity=".35" className="cta-route" />
    </svg>
  );
}

function ContactStrip() {
  return (
    <section className="px-4 pb-24 sm:px-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 rounded-[28px] border border-border bg-surface p-8 shadow-[var(--shadow)] sm:p-10 lg:flex-row lg:items-center">
        <div className="flex-1">
          <h2 className="text-2xl font-black tracking-tight sm:text-3xl">آماده‌اید سفارش‌ها را منظم کنید؟</h2>
          <p className="mt-3 leading-8 text-text-2">۳۰ روز رایگان امتحان کنید، یا اگر سؤالی دارید با ما تماس بگیرید.</p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <a href={`tel:${BRAND.phone}`} className={buttonClass("secondary", "lg")}><Phone className="size-4" /><span className="text-sm">{BRAND.phoneDisplay}</span></a>
          <a href={`mailto:${BRAND.supportEmail}`} className={buttonClass("secondary", "lg")}><Mail className="size-4" /><span className="font-mono text-sm ltr">{BRAND.supportEmail}</span></a>
          <Link to="/request?plan=trial" className={buttonClass("primary", "lg")}>شروع رایگان<ArrowLeft className="size-4" /></Link>
        </div>
      </div>
    </section>
  );
}
