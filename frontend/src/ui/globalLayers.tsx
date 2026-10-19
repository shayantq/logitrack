/**
 * دو لایه سراسری که ظاهر پیش‌فرض مرورگر را با ظاهر سامانه عوض می‌کنند:
 * - TitleTooltips: هر عنصری که title دارد (مثل دکمه تم) به‌جای راهنمای زرد/خاکستری کروم، راهنمای هم‌رنگ تم می‌گیرد.
 * - ValidationBubbles: پیام «Please fill out this field» کروم ← پیام فارسی کنار همان فیلد.
 */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { AlertCircle } from "lucide-react";
import { faNumber } from "@/lib/format";
import { cn } from "./primitives";

type Tip = { text: string; x: number; y: number; below: boolean };

export function TitleTooltips() {
  const [tip, setTip] = useState<Tip | null>(null);
  useEffect(() => {
    let timer = 0;
    let current: HTMLElement | null = null;
    const hide = () => { window.clearTimeout(timer); current = null; setTip(null); };
    const show = (el: HTMLElement, delay: number) => {
      // title مرورگر حذف و در data-tip نگه داشته می‌شود تا راهنمای پیش‌فرض ظاهر نشود
      const title = el.getAttribute("title");
      if (title) {
        el.setAttribute("data-tip", title);
        el.removeAttribute("title");
        if (!el.getAttribute("aria-label") && !el.textContent?.trim()) el.setAttribute("aria-label", title);
      }
      const text = el.getAttribute("data-tip");
      if (!text) return;
      current = el;
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        if (current !== el || !el.isConnected) return;
        const r = el.getBoundingClientRect();
        const below = r.top < 44;
        setTip({ text, x: r.left + r.width / 2, y: below ? r.bottom + 8 : r.top - 8, below });
      }, delay);
    };
    const over = (e: Event) => {
      const el = (e.target as Element | null)?.closest?.<HTMLElement>("[title],[data-tip]");
      if (!el) { if (current) hide(); return; }
      if (el !== current) show(el, 350);
    };
    const focus = (e: FocusEvent) => {
      const el = (e.target as Element | null)?.closest?.<HTMLElement>("[title],[data-tip]");
      if (el && el.matches(":focus-visible")) show(el, 0);
    };
    document.addEventListener("pointerover", over, true);
    document.addEventListener("focusin", focus, true);
    document.addEventListener("focusout", hide, true);
    document.addEventListener("pointerdown", hide, true);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("blur", hide);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("pointerover", over, true);
      document.removeEventListener("focusin", focus, true);
      document.removeEventListener("focusout", hide, true);
      document.removeEventListener("pointerdown", hide, true);
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("blur", hide);
    };
  }, []);

  if (!tip) return null;
  return createPortal(
    <div role="tooltip" data-testid="app-tooltip" dir="rtl"
      style={{ left: Math.min(Math.max(tip.x, 80), window.innerWidth - 80), top: tip.y }}
      className={cn("pointer-events-none fixed z-[90] max-w-64 -translate-x-1/2 rounded-lg bg-text px-2.5 py-1.5 text-center text-xs font-medium leading-5 text-bg shadow-float animate-pop",
        !tip.below && "-translate-y-full")}>
      {tip.text}
    </div>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
type FieldElement = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

function messageFor(el: FieldElement): string {
  const v = el.validity;
  const input = el as HTMLInputElement;
  if (v.valueMissing) {
    if (el instanceof HTMLSelectElement || el.closest("[data-select-root]")) return "یک گزینه را از فهرست انتخاب کنید.";
    if (el.closest("[data-date-field]")) return "تاریخ را انتخاب کنید.";
    if (el.closest("[data-time-field]")) return "ساعت را انتخاب کنید.";
    if (input.type === "checkbox") return "برای ادامه این گزینه را تیک بزنید.";
    if (input.type === "file") return "فایل را انتخاب کنید.";
    return "این فیلد را پر کنید.";
  }
  if (v.typeMismatch) return input.type === "email" ? "ایمیل معتبر وارد کنید (مثل name@example.com)." : input.type === "url" ? "نشانی معتبر وارد کنید." : "مقدار واردشده معتبر نیست.";
  if (v.tooShort) return `حداقل ${faNumber(input.minLength)} کاراکتر وارد کنید (الان ${faNumber(input.value.length)}).`;
  if (v.tooLong) return `حداکثر ${faNumber(input.maxLength)} کاراکتر مجاز است.`;
  if (v.rangeUnderflow) return `مقدار باید حداقل ${faNumber(Number(input.min))} باشد.`;
  if (v.rangeOverflow) return `مقدار باید حداکثر ${faNumber(Number(input.max))} باشد.`;
  if (v.stepMismatch) return "مقدار واردشده مجاز نیست.";
  if (v.badInput) return "یک عدد معتبر وارد کنید.";
  if (v.patternMismatch) return el.getAttribute("data-tip") || el.getAttribute("title") || "قالب واردشده درست نیست.";
  return el.validationMessage || "مقدار این فیلد معتبر نیست.";
}

type Bubble = { text: string; x: number; y: number; width: number };

export function ValidationBubbles() {
  const [bubble, setBubble] = useState<Bubble | null>(null);
  useEffect(() => {
    let first = true;
    let anchor: HTMLElement | null = null;
    let timer = 0;
    const clear = () => {
      anchor?.removeAttribute("data-invalid");
      anchor = null;
      setBubble(null);
    };
    const place = () => {
      if (!anchor?.isConnected) return clear();
      const r = anchor.getBoundingClientRect();
      setBubble(b => b && { ...b, x: r.right, y: r.bottom + 6, width: r.width });
    };
    const onInvalid = (e: Event) => {
      e.preventDefault();                       // پیام پیش‌فرض کروم نمایش داده نشود
      if (!first) return;                       // در یک ارسال فقط اولین فیلد نامعتبر
      first = false;
      window.setTimeout(() => { first = true; }, 0);
      const el = e.target as FieldElement;
      clear();
      anchor = el.closest<HTMLElement>("[data-field-root]") ?? el;
      anchor.setAttribute("data-invalid", "");
      const focusTarget = anchor.querySelector<HTMLElement>("[data-focus-target]") ?? el;
      anchor.scrollIntoView({ block: "center", behavior: "smooth" });
      focusTarget.focus({ preventScroll: true });
      const r = anchor.getBoundingClientRect();
      setBubble({ text: messageFor(el), x: r.right, y: r.bottom + 6, width: r.width });
      window.clearTimeout(timer);
      timer = window.setTimeout(clear, 6000);
    };
    const onEdit = (e: Event) => { if (anchor && anchor.contains(e.target as Node)) clear(); };
    document.addEventListener("invalid", onInvalid, true);
    document.addEventListener("input", onEdit, true);
    document.addEventListener("change", onEdit, true);
    document.addEventListener("click", onEdit, true);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("invalid", onInvalid, true);
      document.removeEventListener("input", onEdit, true);
      document.removeEventListener("change", onEdit, true);
      document.removeEventListener("click", onEdit, true);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, []);

  if (!bubble) return null;
  return createPortal(
    <div role="alert" data-testid="validation-bubble" dir="rtl"
      style={{ left: Math.max(8, bubble.x - Math.max(bubble.width, 220)), top: bubble.y, width: Math.max(bubble.width, 220) }}
      className="pointer-events-none fixed z-[95] flex justify-end">
      <div className="relative flex items-start gap-2 rounded-xl border border-danger/30 bg-surface px-3 py-2 text-xs font-medium leading-5 text-danger shadow-float animate-pop">
        <span className="absolute -top-1.5 end-4 size-3 rotate-45 border-s border-t border-danger/30 bg-surface" />
        <AlertCircle className="mt-0.5 size-4 shrink-0" />{bubble.text}
      </div>
    </div>,
    document.body,
  );
}
