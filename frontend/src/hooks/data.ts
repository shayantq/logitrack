/** داده‌های پرتکرار — با کش مشترک TanStack Query (هر صفحه همان داده را دوباره نمی‌گیرد) */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, authFetch, unwrap } from "@/api/client";

export const useProducts = () =>
  useQuery({ queryKey: ["products"], queryFn: () => unwrap(api.GET("/inventory/products")) });

export const useWarehouses = () =>
  useQuery({ queryKey: ["warehouses"], queryFn: () => unwrap(api.GET("/warehouses/")), staleTime: 60_000 });

export const useVehicles = (enabled = true) =>
  useQuery({ queryKey: ["vehicles"], queryFn: () => unwrap(api.GET("/vehicles/")), enabled });

export const useUsers = (enabled = true) =>
  useQuery({ queryKey: ["users"], queryFn: () => unwrap(api.GET("/users/")), enabled });

export const useProvinces = () =>
  useQuery({
    queryKey: ["provinces"],
    queryFn: async () => {
      const res = await fetch("/organization-requests/form-options");
      return ((await res.json()) as { provinces: string[] }).provinces;
    },
    staleTime: Infinity,
  });

type ExportPath =
  | "/reports/export/orders/excel" | "/reports/export/orders/pdf"
  | "/reports/export/inventory/excel" | "/reports/export/inventory/pdf"
  | "/reports/generate";

/**
 * خروجی Excel/PDF که در Celery ساخته می‌شود: شروع ← پایش وضعیت ← دانلود فایل.
 * سرور خیلی سریع پاسخ می‌دهد و ساخت فایل در پس‌زمینه انجام می‌شود.
 * `key` برای وقتی است که چند دکمه یک مسیر را با پارامترهای مختلف صدا می‌زنند (مثلاً /reports/generate).
 */
export function useAsyncExport(onError: (message: string) => void, onDone: () => void) {
  const [running, setRunning] = useState<string | null>(null);

  async function run(path: ExportPath, filename: string, body?: Record<string, unknown>, key: string = path) {
    setRunning(key);
    try {
      const startRes = await authFetch(path, body
        ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
        : { method: "POST" });
      if (!startRes.ok) {
        const detail = await startRes.json().catch(() => null) as { detail?: unknown } | null;
        throw new Error(typeof detail?.detail === "string" ? detail.detail : "خطا در شروع تولید گزارش.");
      }
      const { task_id } = (await startRes.json()) as { task_id: string };
      for (let attempt = 0; attempt < 60; attempt++) {
        await new Promise(r => setTimeout(r, attempt < 4 ? 600 : 1000));
        const statusRes = await authFetch(`/reports/task-status/${task_id}`);
        if (!statusRes.ok) continue;
        const { status } = (await statusRes.json()) as { status: string };
        if (status === "failed") throw new Error("تولید گزارش با خطا مواجه شد.");
        if (status === "success") {
          const fileRes = await authFetch(`/reports/task-result/${task_id}`);
          if (!fileRes.ok) throw new Error("خطا در دریافت فایل نهایی.");
          // نام فایل سرور تاریخ شمسی تهیه را هم دارد
          const served = /filename="([^"]+)"/.exec(fileRes.headers.get("Content-Disposition") ?? "")?.[1];
          const link = document.createElement("a");
          link.href = URL.createObjectURL(await fileRes.blob());
          link.download = served ?? filename;
          document.body.appendChild(link);
          link.click();
          link.remove();
          onDone();
          return;
        }
      }
      throw new Error("تولید گزارش بیش از حد انتظار طول کشید.");
    } catch (e) {
      onError(e instanceof Error ? e.message : "خطا در تولید گزارش.");
    } finally {
      setRunning(null);
    }
  }

  return { run, running };
}
