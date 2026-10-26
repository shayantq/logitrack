/**
 * نوار وضعیت اتصال (فصل ۲۱): وقتی اینترنت قطع می‌شود بالای صفحه پیام می‌دهد و ثبت‌ها را تا وصل شدن نگه نمی‌دارد —
 * ثبت‌های ناتمام با همان کلید یکتایی دوباره فرستاده می‌شوند (سرور سند تکراری نمی‌سازد). با وصل شدن دوباره،
 * داده‌های صفحه خودکار تازه می‌شوند.
 */
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Wifi, WifiOff } from "lucide-react";
import { cn } from "@/ui/primitives";

export function OfflineBanner() {
  const queryClient = useQueryClient();
  const [online, setOnline] = useState(() => typeof navigator === "undefined" || navigator.onLine !== false);
  const [restored, setRestored] = useState(false);
  useEffect(() => {
    const down = () => { setOnline(false); setRestored(false); };
    const up = () => {
      setOnline(true);
      setRestored(true);
      queryClient.invalidateQueries();
      window.setTimeout(() => setRestored(false), 3000);
    };
    window.addEventListener("offline", down);
    window.addEventListener("online", up);
    return () => { window.removeEventListener("offline", down); window.removeEventListener("online", up); };
  }, [queryClient]);
  if (online && !restored) return null;
  return (
    <div role="status" data-testid="offline-banner" data-online={online}
      className={cn("sticky top-0 z-50 flex items-center justify-center gap-2 px-4 py-2 text-center text-xs font-medium text-white transition-colors",
        online ? "bg-success" : "bg-danger")}>
      {online ? <Wifi className="size-4" /> : <WifiOff className="size-4" />}
      {online ? "اتصال برقرار شد؛ اطلاعات صفحه تازه شد." : "اتصال اینترنت قطع است — تغییرات تا وصل شدن ثبت نمی‌شوند؛ ثبت‌های نیمه‌کاره بعداً بدون تکرار فرستاده می‌شوند."}
    </div>
  );
}
