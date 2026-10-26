import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// همه منابع داخل باندل — بدون وابستگی به CDN خارجی (Google Fonts و ... در ایران ممکن است در دسترس نباشند)
import "vazirmatn/Vazirmatn-Variable-font-face.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "./styles.css";

import { App } from "./App";
import { ApiError } from "./api/client";
import { ToastProvider } from "./components/Toast";
import { ThemeProvider } from "./theme/ThemeProvider";
import { DialogsProvider } from "./ui/dialogs";
import { TitleTooltips, ValidationBubbles } from "./ui/globalLayers";

const queryClient = new QueryClient({
  // قطع موقت شبکه (فصل ۲۱): خواندن‌ها تا سه بار با فاصله افزایشی دوباره تلاش می‌شوند؛ خطای خود سرور (۴xx) تکرار نمی‌شود
  defaultOptions: { queries: { retry: (count, error) => count < 3 && !(error instanceof ApiError && error.status !== undefined && error.status < 500), retryDelay: n => Math.min(1000 * 2 ** n, 8000), refetchOnWindowFocus: false, refetchOnReconnect: true, staleTime: 10_000 } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ToastProvider>
            <DialogsProvider>
              <App />
              <TitleTooltips />
              <ValidationBubbles />
            </DialogsProvider>
          </ToastProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
