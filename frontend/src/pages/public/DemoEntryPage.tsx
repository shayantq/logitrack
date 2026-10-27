/**
 * ورود به نسخه نمایشی خصوصی با لینک مخفی /app/d/<توکن> — بدون فرم ورود، مستقیم داشبورد ادمین سازمان فرضی.
 * توکن نادرست هیچ نشانه‌ای از وجود دمو نمی‌دهد و به صفحه اصلی می‌رود.
 */
import { useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { tokenStore } from "@/api/client";
import { DEMO_LINK_KEY } from "@/auth/AuthContext";
import { Spinner } from "@/ui/primitives";

export default function DemoEntryPage() {
  const { token = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    (async () => {
      try {
        const response = await fetch("/demo/session", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }),
        });
        if (!response.ok) throw new Error(String(response.status));
        const body = await response.json();
        tokenStore.set(body.access_token);
        try {
          localStorage.setItem(DEMO_LINK_KEY, token);
          localStorage.setItem("tours-off", "1");        // پیام خوش‌آمد دمو جای راهنمای خودکار را می‌گیرد
        } catch { /* */ }
        queryClient.clear();
        window.location.replace("/app");                  // بارگذاری تازه با توکن دمو
      } catch {
        navigate("/", { replace: true });
      }
    })();
  }, [token, navigate, queryClient]);

  return <div className="grid min-h-dvh place-items-center bg-bg"><Spinner /></div>;
}
