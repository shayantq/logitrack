import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, ApiError, errorMessage, setUnauthorizedHandler, tokenStore, unwrap, type Schemas } from "@/api/client";
import { PLATFORM_ROLES, type Role } from "@/lib/labels";

export type Me = Schemas["MeResponse"] & { role: Role };

interface AuthState {
  me: Me | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<Me>;
  logout: () => void;
  isPlatform: boolean;
}

const AuthContext = createContext<AuthState | null>(null);

/** صفحه اول هر کاربر بعد از ورود (راننده تأییدنشده ← فرم احراز هویت) */
export function homePathFor(user: { role: Role | string; driver_status?: string | null; must_change_password?: boolean }): string {
  // ورود با رمز موقت ادمین ← اول تغییر رمز
  if (user.must_change_password) return "/app/change-password";
  const role = user.role as Role;
  if (PLATFORM_ROLES.includes(role)) return "/app/platform";
  if (role === "driver") return isApprovedDriver(user) ? "/app/driver" : "/app/onboarding";
  if (role === "warehouse_manager") return "/app/inventory";
  return "/app";
}

export function isApprovedDriver(user: { driver_status?: string | null }): boolean {
  return (user.driver_status ?? "approved") === "approved";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const hasToken = !!tokenStore.get();

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: async () => (await unwrap(api.GET("/users/me"))) as Me,
    enabled: hasToken,
    staleTime: 5 * 60_000,
    retry: false,
  });

  const logout = useCallback(() => {
    tokenStore.clear();
    queryClient.clear();
    navigate("/app/login", { replace: true });
  }, [navigate, queryClient]);

  useEffect(() => setUnauthorizedHandler(logout), [logout]);

  const login = useCallback(async (username: string, password: string) => {
    const response = await fetch("/auth/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ username, password }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new ApiError(errorMessage(body, "نام کاربری یا رمز عبور نامعتبر است."), response.status);
    tokenStore.set(body.access_token);
    queryClient.clear();
    const me = (await unwrap(api.GET("/users/me"))) as Me;
    queryClient.setQueryData(["me"], me);
    return me;
  }, [queryClient]);

  const value = useMemo<AuthState>(() => {
    const me = hasToken ? meQuery.data ?? null : null;
    return {
      me,
      loading: hasToken && meQuery.isLoading,
      login,
      logout,
      isPlatform: !!me && PLATFORM_ROLES.includes(me.role),
    };
  }, [hasToken, meQuery.data, meQuery.isLoading, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** کاربر جاری که حتماً وارد شده است (داخل صفحات محافظت‌شده). */
export function useMe(): Me {
  const { me } = useAuth();
  if (!me) throw new Error("useMe used outside a protected route");
  return me;
}

/** آیا کاربر جاری مجوز ریز key را دارد؟ (فقط برای نمایش؛ بررسی اصلی سمت سرور است) */
export function useCan(key: string): boolean {
  return useMe().permissions?.includes(key) ?? false;
}
