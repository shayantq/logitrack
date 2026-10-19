import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

// یک اپ برای همه‌چیز: صفحه اصلی (/)، فرم درخواست (/request) و پنل‌ها (/app/...).
// مسیرهای API (مثل /orders/) جدا هستند و FastAPI فقط مسیرهای بالا را به index.html می‌دهد.
const API_PREFIXES = ["/auth", "/users", "/inventory", "/orders", "/vehicles", "/reports", "/warehouses",
  "/notifications", "/platform", "/organization", "/organization-requests", "/health", "/replenishment", "/stocktakes",
  "/catalog", "/drivers", "/dispatch", "/public", "/tickets", "/map", "/driver-onboarding", "/performance"];

export default defineConfig({
  base: "/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: {
    outDir: "dist",
    assetsDir: "assets",
    sourcemap: false,
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        // سه‌بعدی و انیمیشن فقط در صفحه اصلی لازم‌اند؛ جدا باندل می‌شوند تا پنل‌ها سبک بمانند
        manualChunks: { three: ["three"], gsap: ["gsap"], vendor: ["react", "react-dom", "react-router-dom", "@tanstack/react-query"] },
      },
    },
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(API_PREFIXES.map(p => [p, { target: "http://localhost:8001", changeOrigin: true }])),
  },
});
