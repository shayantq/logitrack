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
import { ToastProvider } from "./components/Toast";
import { ThemeProvider } from "./theme/ThemeProvider";
import { DialogsProvider } from "./ui/dialogs";
import { TitleTooltips, ValidationBubbles } from "./ui/globalLayers";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 10_000 } },
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
