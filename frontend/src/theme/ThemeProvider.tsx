import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";

export type ThemePreference = "light" | "dark" | "system";
type ThemeState = {
  preference: ThemePreference; resolved: "light" | "dark"; setPreference: (p: ThemePreference) => void;
  /** تغییر با یک کلیک بین روز و شب؛ origin = نقطه کلیک برای انیمیشن دایره‌ای */
  toggle: (origin?: { x: number; y: number }) => void;
};

const ThemeContext = createContext<ThemeState | null>(null);
const STORAGE_KEY = "theme";

function systemTheme(): "light" | "dark" {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function readPreference(): ThemePreference {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPref] = useState<ThemePreference>(readPreference);
  const [system, setSystem] = useState<"light" | "dark">(systemTheme);
  const resolved = preference === "system" ? system : preference;

  // دنبال کردن تغییر تم سیستم‌عامل وقتی کاربر «مطابق سیستم» را انتخاب کرده
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setSystem(media.matches ? "dark" : "light");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
    // نوار بالای مرورگر موبایل (Android Chrome / Safari) هم‌رنگ پس‌زمینه سایت
    document.querySelectorAll('meta[name="theme-color"]').forEach(m => { m.setAttribute("content", resolved === "dark" ? "#091540" : "#f7fbfc"); m.removeAttribute("media"); });
    window.dispatchEvent(new CustomEvent("themechange", { detail: resolved }));
  }, [resolved]);

  const setPreference = useCallback((p: ThemePreference) => {
    setPref(p);
    try { localStorage.setItem(STORAGE_KEY, p); } catch { /* حالت خصوصی مرورگر */ }
  }, []);

  const toggle = useCallback((origin?: { x: number; y: number }) => {
    const next = resolved === "dark" ? "light" : "dark";
    const apply = () => {
      document.documentElement.dataset.theme = next;   // همان لحظه، تا عکس «بعد» انیمیشن درست گرفته شود
      flushSync(() => setPreference(next));
    };
    const doc = document as Document & { startViewTransition?: (cb: () => void) => { ready: Promise<void> } };
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!doc.startViewTransition || reduced) { apply(); return; }
    // تم جدید از محل کلیک به‌صورت دایره‌ای پخش می‌شود (Chrome/Edge)؛ مرورگرهای دیگر بی‌انیمیشن عوض می‌شوند
    const x = origin?.x ?? window.innerWidth / 2;
    const y = origin?.y ?? 0;
    const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
    doc.startViewTransition(apply).ready.then(() => {
      document.documentElement.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
        { duration: 550, easing: "cubic-bezier(.4,0,.2,1)", pseudoElement: "::view-transition-new(root)" },
      );
    }).catch(() => {});
  }, [resolved, setPreference]);

  return <ThemeContext.Provider value={{ preference, resolved, setPreference, toggle }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside ThemeProvider");
  return ctx;
}
