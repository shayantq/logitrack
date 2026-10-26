/**
 * کلاینت API تایپ‌شده — مسیرها و بدنه‌ها از schema.d.ts (تولیدشده از OpenAPI سرور) می‌آیند،
 * پس صدا زدن مسیر/فیلدی که در بک‌اند وجود ندارد، در زمان build خطا می‌دهد.
 * برای به‌روزرسانی بعد از تغییر بک‌اند:  npm run gen:api
 */
import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

const TOKEN_KEY = "access_token";

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

/** وقتی سرور 401 داد (توکن منقضی)، کاربر به صفحه ورود برمی‌گردد. */
let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

const authMiddleware: Middleware = {
  onRequest({ request }) {
    const token = tokenStore.get();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ response }) {
    if (response.status === 401) onUnauthorized();
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(authMiddleware);

/** درخواست خام با توکن (برای فایل، FormData و endpointهایی که پاسخ تایپ‌شده ندارند). */
export async function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(input, { ...init, headers });
  if (response.status === 401) onUnauthorized();
  return response;
}

/** خطای API با پیام قابل نمایش به کاربر. */
export class ApiError extends Error {
  constructor(message: string, public status?: number) {
    super(message);
  }
}

type ValidationItem = { loc?: (string | number)[]; msg?: string };

export function errorMessage(error: unknown, fallback = "خطایی رخ داد؛ دوباره تلاش کنید."): string {
  if (error instanceof ApiError) return error.message;
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return (detail as ValidationItem[])
        .map(d => {
          const msg = (d.msg ?? "").replace(/^Value error, /, "");
          const field = String(d.loc?.slice(-1)[0] ?? "");
          // خطای کل فرم (مثل شهر خارج از استان) نام فیلد ندارد
          return !field || field === "body" ? msg : `${field}: ${msg}`;
        })
        .join(" | ");
    }
  }
  if (error instanceof Error) return error.message;
  return fallback;
}

/**
 * نتیجه openapi-fetch را باز می‌کند: data را برمی‌گرداند یا ApiError با پیام فارسی سرور پرتاب می‌کند.
 * استفاده: const orders = await unwrap(api.GET("/orders/", {...}))
 */
export async function unwrap<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response };
  try {
    result = await promise;
  } catch {
    // قطع شبکه یا سرور در دسترس نیست (پاسخی نرسیده) — status خالی می‌ماند تا کلید یکتایی ثبت عوض نشود
    throw new ApiError(navigator.onLine === false ? "اتصال اینترنت قطع است؛ پس از وصل شدن دوباره تلاش کنید."
      : "سرور در دسترس نیست؛ چند لحظه بعد دوباره تلاش کنید.");
  }
  const { data, error, response } = result;
  if (error !== undefined || !response.ok) {
    let message = errorMessage(error, `خطای سرور (${response.status})`);
    // خطای پیش‌بینی‌نشده سرور: کد پیگیری برای پشتیبانی (اگر در خود پیام نیامده باشد)
    const requestId = (error as { request_id?: string } | undefined)?.request_id ?? response.headers.get("x-request-id");
    if (response.status >= 500 && requestId && !message.includes(requestId)) message += ` (کد پیگیری: ${requestId})`;
    throw new ApiError(message, response.status);
  }
  return data as T;
}

/**
 * کلید یکتایی درخواست (هدر Idempotency-Key): اگر ثبت یک سند یا سفارش به‌خاطر قطع شبکه دوباره فرستاده شود،
 * سرور همان نتیجه قبلی را برمی‌گرداند و سند دوم نمی‌سازد. برای هر «تلاش ثبت» یک کلید تازه بسازید و بعد از
 * پاسخ سرور (موفق یا خطا) عوضش کنید؛ فقط وقتی پاسخی نرسیده همان کلید را دوباره بفرستید.
 */
export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/** خطایی که از خود سرور آمده (نه قطع شبکه) — بعد از آن کلید یکتایی باید عوض شود. */
export const isServerError = (error: unknown) => error instanceof ApiError && error.status !== undefined;
