/** ابزارهای حرکت صفحه اصلی: GSAP + ScrollTrigger، با احترام به «کاهش حرکت» سیستم‌عامل */
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { faNumber } from "@/lib/format";
import { cn } from "@/ui/primitives";

gsap.registerPlugin(ScrollTrigger);
// روی دستگاه‌های کند، انیمیشن‌های ظاهر شدن با زمان واقعی تمام شوند (نه آهسته‌تر از آن)
gsap.ticker.lagSmoothing(0);
export { gsap, ScrollTrigger };

const REDUCED = "(prefers-reduced-motion: reduce)";

export function useReducedMotion() {
  const [reduced, setReduced] = useState(() => window.matchMedia(REDUCED).matches);
  useEffect(() => {
    const media = window.matchMedia(REDUCED);
    const onChange = () => setReduced(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

/**
 * پیشرفت اسکرولِ یک بخش بلند (۰ تا ۱) با کمی نرمی (scrub).
 * بخش داخلی با position: sticky ثابت می‌ماند و فقط محتوا عوض می‌شود — «به‌جای اسکرول، متن ظاهر می‌شود».
 */
export function useScrubProgress(ref: RefObject<HTMLElement | null>, onProgress: (p: number) => void, { smooth = 0.6, start = "top top", end = "bottom bottom", disabled = false } = {}) {
  const callback = useRef(onProgress);
  callback.current = onProgress;
  useLayoutEffect(() => {
    if (disabled || !ref.current) return;
    const proxy = { p: 0 };
    const ctx = gsap.context(() => {
      gsap.to(proxy, {
        p: 1, ease: "none",
        scrollTrigger: { trigger: ref.current, start, end, scrub: smooth },
        onUpdate: () => callback.current(proxy.p),
      });
    });
    return () => ctx.revert();
  }, [ref, smooth, start, end, disabled]);
}

/** پیشرفت به‌صورت state — برای بخش‌های کوچک که رندر دوباره ارزان است (با گرد کردن برای کم کردن رندرها) */
export function useProgressState(ref: RefObject<HTMLElement | null>, options?: Parameters<typeof useScrubProgress>[2], step = 0.01) {
  const [progress, setProgress] = useState(options?.disabled ? 1 : 0);
  useScrubProgress(ref, p => setProgress(Math.round(p / step) * step), options);
  return progress;
}

/** آیا عنصر در دید است؟ (برای شروع/توقف انیمیشن‌های پیوسته) */
export function useInView<T extends Element>(ref: RefObject<T | null>, rootMargin = "0px") {
  const [inView, setInView] = useState(false);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { rootMargin });
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [ref, rootMargin]);
  return inView;
}

/** متنی که کلمه‌به‌کلمه با اسکرول پررنگ می‌شود */
export function ScrubText({ text, className }: { text: string; className?: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const reduced = useReducedMotion();
  useLayoutEffect(() => {
    if (reduced || !ref.current) return;
    const ctx = gsap.context(() => {
      gsap.fromTo(ref.current!.querySelectorAll("[data-word]"), { opacity: 0.14 }, {
        opacity: 1, stagger: 0.08, ease: "none",
        scrollTrigger: { trigger: ref.current, start: "top 85%", end: "bottom 45%", scrub: 0.4 },
      });
    }, ref);
    return () => ctx.revert();
  }, [reduced, text]);
  return (
    <p ref={ref} className={className}>
      {text.split(" ").map((word, i) => <span key={i} data-word className="inline-block">{word}&nbsp;</span>)}
    </p>
  );
}

/** ظاهر شدن نرم فرزندان هنگام ورود به دید */
export function Reveal({ children, className, stagger = 0.08, y = 28, as: Tag = "div" }: { children: ReactNode; className?: string; stagger?: number; y?: number; as?: "div" | "ul" | "ol" }) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  useLayoutEffect(() => {
    if (reduced || !ref.current) return;
    const ctx = gsap.context(() => {
      gsap.from(ref.current!.children, {
        y, opacity: 0, duration: 0.9, ease: "power3.out", stagger,
        scrollTrigger: { trigger: ref.current, start: "top 85%", once: true },
      });
    }, ref);
    return () => ctx.revert();
  }, [reduced, stagger, y]);
  return <Tag ref={ref as never} className={className}>{children}</Tag>;
}

/** شمارنده کیلومترشمار: هر رقم یک ستون ۰ تا ۹ است که می‌چرخد */
const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
export function Odometer({ value, className, minDigits = 1 }: { value: number; className?: string; minDigits?: number }) {
  const digits = Math.max(0, Math.round(value)).toString().padStart(minDigits, "0").split("");
  return (
    <span className={cn("inline-flex overflow-hidden tnum ltr", className)} aria-label={faNumber(value)}>
      {digits.map((d, i) => {
        const fromEnd = digits.length - i;
        return (
          <span key={fromEnd} className="relative inline-block h-[1em] w-[0.62em] overflow-hidden leading-none" aria-hidden="true">
            <span className="absolute inset-x-0 top-0 flex flex-col transition-transform duration-[1400ms] ease-[cubic-bezier(.2,.8,.2,1)]"
              style={{ transform: `translateY(-${Number(d) * 10}%)` }}>
              {FA_DIGITS.split("").map(f => <span key={f} className="h-[1em] text-center">{f}</span>)}
            </span>
          </span>
        );
      })}
    </span>
  );
}

/** عدد شمارشی که هنگام ورود به دید از صفر بالا می‌رود */
export function CountUp({ to, suffix = "", className }: { to: number; suffix?: string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const reduced = useReducedMotion();
  const [value, setValue] = useState(reduced ? to : 0);
  useLayoutEffect(() => {
    if (reduced || !ref.current) { setValue(to); return; }
    const proxy = { v: 0 };
    const ctx = gsap.context(() => {
      gsap.to(proxy, {
        v: to, duration: 1.8, ease: "power2.out", onUpdate: () => setValue(Math.round(proxy.v)),
        scrollTrigger: { trigger: ref.current, start: "top 90%", once: true },
      });
    });
    return () => ctx.revert();
  }, [to, reduced]);
  return <span ref={ref} className={cn("tnum", className)}>{faNumber(value)}{suffix}</span>;
}

/** نشانگر بخش به سبک [۰۲] — برای سربرگ‌های بخش */
export function SectionTag({ label }: { label: string }) {
  return (
    <div className="mb-5">
      <span className="inline-flex items-center gap-2 rounded-full border border-brand/20 bg-brand-soft/70 px-3 py-1 text-xs font-semibold text-brand-strong">
        <span className="size-1.5 rounded-full bg-brand" />{label}
      </span>
    </div>
  );
}

export const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
/** نگاشت خطی بازه [a, b] به [۰، ۱] */
export const range = (v: number, a: number, b: number) => clamp01((v - a) / (b - a));
