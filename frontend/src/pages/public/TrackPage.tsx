/**
 * پیگیری عمومی سفارش (/track و /track/:code) — بدون ورود، به‌روزرسانی خودکار هر ۱۵ ثانیه.
 * با کد فقط اطلاعات عمومی؛ با ۴ رقم آخر موبایل گیرنده، نشانی، اقلام و لینک نظرسنجی.
 */
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Check, Clock, KeyRound, Lock, MapPin, MapPinned, Package, PackageSearch, RefreshCw, Star, Truck, X } from "lucide-react";
import { api, errorMessage, unwrap } from "@/api/client";
import { BRAND } from "@/brand";
import { RouteView } from "@/components/map/RouteCard";
import { VEHICLE_TYPES } from "@/lib/labels";
import { faNumber, faShortDateTime, latinDigits } from "@/lib/format";
import { Button, Input, Spinner, buttonClass, cn } from "@/ui/primitives";
import { PublicFooter, PublicHeader } from "./chrome";
import { SupportRequest } from "./SupportRequest";

const REFRESH_MS = 15_000;
const FAILED = ["failed", "canceled", "expired"];

export default function TrackPage() {
  const { code: routeCode = "" } = useParams();
  const navigate = useNavigate();
  const [input, setInput] = useState(routeCode);
  const [phone, setPhone] = useState("");
  const [verifiedPhone, setVerifiedPhone] = useState<string | null>(null);
  const code = routeCode.trim().toUpperCase();
  useEffect(() => { document.title = `پیگیری سفارش — ${BRAND.name}`; setInput(routeCode); setVerifiedPhone(null); }, [routeCode]);

  const query = useQuery({
    queryKey: ["track", code, verifiedPhone],
    queryFn: () => unwrap(api.GET("/public/track/{code}", { params: { path: { code }, query: verifiedPhone ? { phone: verifiedPhone } : {} } })),
    enabled: !!code, retry: false,
    // به‌روزرسانی خودکار تا وقتی سفارش به پایان نرسیده
    refetchInterval: q => (q.state.data?.is_final ? false : REFRESH_MS),
  });
  const [phoneError, setPhoneError] = useState<string | null>(null);
  async function verify(e: FormEvent) {
    e.preventDefault();
    const digits = latinDigits(phone.trim());
    setPhoneError(null);
    try {
      await unwrap(api.GET("/public/track/{code}", { params: { path: { code }, query: { phone: digits } } }));
      setVerifiedPhone(digits);
    } catch (err) { setPhoneError(errorMessage(err)); }
  }
  const t = query.data;
  const failed = t && FAILED.includes(t.status);

  return (
    <div className="min-h-svh bg-bg text-text">
      <PublicHeader />
      <main className="stagger mx-auto max-w-3xl px-4 pb-20 pt-28 sm:px-6">
        <div className="mb-8 text-center">
          <div className="eyebrow mb-3 justify-center">پیگیری سفارش</div>
          <h1 className="text-3xl font-black sm:text-4xl">سفارش شما کجاست؟</h1>
          <p className="mt-3 text-muted">کد پیگیری‌ای را که فروشنده برایتان فرستاده وارد کنید.</p>
        </div>
        <form className="mx-auto flex max-w-lg gap-2" onSubmit={e => { e.preventDefault(); if (input.trim()) navigate(`/track/${latinDigits(input.trim()).toUpperCase()}`); }}>
          <Input className="ltr h-12 flex-1 text-center font-mono text-lg tracking-widest" placeholder="LT-XXXXXXXX" value={input} onChange={e => setInput(e.target.value)} data-testid="track-input" />
          <Button type="submit" size="lg" icon={<PackageSearch className="size-5" />} data-testid="track-submit">پیگیری</Button>
        </form>

        {code && (
          <div className="mt-10">
            {query.isLoading ? <div className="grid place-items-center py-16"><Spinner className="size-7" /></div> : query.error ? (
              <div className="card p-8 text-center" data-testid="track-error">
                <X className="mx-auto size-10 text-danger" />
                <p className="mt-3 font-semibold">{errorMessage(query.error)}</p>
              </div>
            ) : t && (
              <div className="stagger space-y-5" data-testid="track-result" data-status={t.status}>
                <div className="card overflow-hidden">
                  <div className={cn("p-6", failed ? "bg-danger-soft" : t.status === "delivered" ? "bg-success-soft" : "bg-linear-to-l from-brand-soft to-transparent")}>
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="text-sm text-muted">{t.organization_name}</div>
                        <div className="font-mono text-xl font-black ltr">{t.tracking_code}</div>
                      </div>
                      {!t.is_final && (
                        <span className="flex items-center gap-1.5 rounded-full bg-surface/70 px-3 py-1 text-xs text-muted" data-testid="track-live">
                          <RefreshCw className={cn("size-3.5", query.isFetching && "animate-spin")} />به‌روزرسانی خودکار
                        </span>
                      )}
                    </div>
                    <p className={cn("mt-4 text-lg font-bold", failed ? "text-danger" : t.status === "delivered" ? "text-success" : "")} data-testid="track-status-text">{t.status_text}</p>
                  </div>

                  {/* مراحل */}
                  <ol className="grid grid-cols-5 gap-1 px-4 py-6 sm:px-6" data-testid="track-steps">
                    {t.steps.map((s, i) => (
                      <li key={s.key} className="relative flex flex-col items-center text-center">
                        {i > 0 && <span className={cn("absolute left-1/2 top-4 h-0.5 w-full", s.done ? "bg-brand" : "bg-border")} />}
                        <span className={cn("relative z-10 grid size-8 place-items-center rounded-full border-2 transition",
                          s.done ? "border-brand bg-brand text-brand-ink" : "border-border-strong bg-surface text-muted")}>
                          {s.done ? <Check className="size-4" strokeWidth={3} /> : <span className="text-xs">{faNumber(i + 1)}</span>}
                        </span>
                        <span className={cn("mt-2 text-[11px] font-semibold sm:text-xs", !s.done && "text-muted")}>{s.label}</span>
                        {s.at && <span className="mt-0.5 text-[10px] text-muted">{faShortDateTime(s.at)}</span>}
                      </li>
                    ))}
                  </ol>

                  <dl className="grid gap-4 border-t border-border p-6 text-sm sm:grid-cols-3">
                    <div className="flex gap-2"><Clock className="mt-0.5 size-4 text-muted" /><div><dt className="text-xs text-muted">بازه تحویل</dt>
                      <dd className="font-semibold">{faShortDateTime(t.delivery_window_start)} تا {faShortDateTime(t.delivery_window_end).split(" ").pop()}</dd></div></div>
                    <div className="flex gap-2"><MapPin className="mt-0.5 size-4 text-muted" /><div><dt className="text-xs text-muted">مقصد</dt>
                      <dd className="font-semibold">{[t.destination_province, t.destination_city].filter(Boolean).join(" / ")}</dd></div></div>
                    <div className="flex gap-2"><Truck className="mt-0.5 size-4 text-muted" /><div><dt className="text-xs text-muted">راننده</dt>
                      <dd className="font-semibold" data-testid="track-driver">{t.driver?.first_name
                        ? `${t.driver.first_name} — ${VEHICLE_TYPES[t.driver.vehicle_type ?? ""] ?? ""}` : "هنوز تعیین نشده"}</dd></div></div>
                  </dl>
                </div>

                {/* مسیر روی نقشه ایران (مرحله ۱۰) */}
                {t.route && (
                  <div className="card p-6" data-testid="track-route">
                    <h3 className="mb-4 flex items-center gap-2 font-bold"><MapPinned className="size-5 text-brand" />مسیر سفارش روی نقشه</h3>
                    <RouteView route={t.route} status={t.status} id={t.tracking_code} />
                  </div>
                )}

                {/* جزئیات محرمانه */}
                {t.verified && t.details ? (
                  <div className="card p-6" data-testid="track-details">
                    <h2 className="mb-4 flex items-center gap-2 font-bold"><Package className="size-5 text-brand" />جزئیات سفارش</h2>
                    <dl className="grid gap-3 text-sm sm:grid-cols-2">
                      <div><dt className="text-xs text-muted">تحویل‌گیرنده</dt><dd className="font-semibold">{t.details.recipient_name}</dd></div>
                      <div><dt className="text-xs text-muted">وزن کل</dt><dd className="font-semibold">{faNumber(t.details.total_weight_kg)} کیلوگرم</dd></div>
                      <div className="sm:col-span-2"><dt className="text-xs text-muted">نشانی</dt><dd className="font-semibold">{t.details.destination_address}</dd></div>
                    </dl>
                    <ul className="mt-4 divide-y divide-border rounded-xl border border-border text-sm">
                      {t.details.items.map((it, i) => <li key={i} className="flex justify-between px-4 py-2.5"><span>{it.name}</span><span className="tnum text-muted">× {faNumber(it.quantity)}</span></li>)}
                    </ul>
                    {t.details.rating_token && (
                      <Link to={`/rate/${t.details.rating_token}`} className={buttonClass("primary", "md", "mt-5 w-full")} data-testid="track-rate"><Star className="size-4" />نظر خود را درباره راننده ثبت کنید</Link>
                    )}
                  </div>
                ) : null}
                {t.verified && t.details && verifiedPhone ? (
                  <SupportRequest code={t.tracking_code} phone={verifiedPhone} />
                ) : (
                  <form className="card flex flex-wrap items-end gap-3 p-5" onSubmit={verify} data-testid="track-verify">
                    <div className="min-w-48 flex-1">
                      <div className="mb-1.5 flex items-center gap-1.5 text-sm font-semibold"><Lock className="size-4 text-muted" />نشانی، اقلام و ثبت نظر</div>
                      <p className="text-xs text-muted">برای حفظ حریم شما، ۴ رقم آخر موبایل گیرنده را وارد کنید (گیرنده: {t.recipient_masked ?? "—"}).</p>
                    </div>
                    <Input className="ltr w-28 text-center font-mono tracking-[0.4em]" maxLength={4} inputMode="numeric" placeholder="۱۲۳۴" value={phone}
                      onChange={e => setPhone(e.target.value)} data-testid="track-phone" />
                    <Button type="submit" variant="secondary" icon={<KeyRound className="size-4" />} disabled={latinDigits(phone).length !== 4} data-testid="track-verify-submit">نمایش</Button>
                    {phoneError && <p className="w-full text-sm text-danger" data-testid="track-phone-error">{phoneError}</p>}
                  </form>
                )}
              </div>
            )}
          </div>
        )}
      </main>
      <PublicFooter />
    </div>
  );
}
