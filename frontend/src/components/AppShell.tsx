import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import { Building2, ChevronsLeft, ChevronsRight, Compass, KeyRound, LogOut, MapPinned, Menu as MenuIcon, UserRound, X } from "lucide-react";
import { api, authFetch, unwrap } from "@/api/client";
import { useAuth, useMe } from "@/auth/AuthContext";
import { TourProvider, useTour } from "@/components/tour/TourProvider";
import { NotificationCenter } from "@/components/NotificationCenter";
import { demoAllows, NavLinks, navItemsFor } from "@/components/navigation";
import { OfflineBanner } from "@/components/OfflineBanner";
import { ScanButton } from "@/components/ScanDialog";
import { ROLE_LABELS } from "@/lib/labels";
import { Logo, LogoMark, ThemeToggle } from "@/ui/brand";
import { Menu, MenuItem, MenuLabel, MenuSeparator, Modal } from "@/ui/overlays";
import { PasswordChangeForm } from "@/components/PasswordChangeForm";
import { Button, cn } from "@/ui/primitives";

// فقط برای نسخه نمایشی خصوصی بارگذاری می‌شود
const DemoChrome = lazy(() => import("@/components/demo/DemoChrome"));

function useOrgLogo(enabled: boolean) {
  const { data: profile } = useQuery({
    queryKey: ["organization-profile"], queryFn: () => unwrap(api.GET("/organization/profile")), enabled, staleTime: 60_000,
  });
  const { data: url } = useQuery({
    queryKey: ["organization-logo", profile?.has_logo, profile?.updated_at],
    queryFn: async () => { const r = await authFetch("/organization/logo"); return r.ok ? URL.createObjectURL(await r.blob()) : null; },
    enabled: !!profile?.has_logo, staleTime: Infinity,
  });
  return url ?? null;
}

/** کشیدن کشوی موبایل به سمت راست (بیرون صفحه در RTL) آن را می‌بندد */
function useSwipeToClose(onClose: () => void) {
  const start = useRef<{ x: number; y: number } | null>(null);
  const [dx, setDx] = useState(0);
  return {
    offset: dx,
    handlers: {
      onTouchStart: (e: React.TouchEvent) => { start.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }; },
      onTouchMove: (e: React.TouchEvent) => {
        if (!start.current) return;
        const moveX = e.touches[0].clientX - start.current.x;
        const moveY = Math.abs(e.touches[0].clientY - start.current.y);
        if (moveY > Math.abs(moveX)) return;              // اسکرول عمودی منو
        setDx(Math.max(0, moveX));
      },
      onTouchEnd: () => {
        if (dx > 80) onClose();
        start.current = null;
        setDx(0);
      },
    },
  };
}

export function AppShell() {
  return <TourProvider><Shell /></TourProvider>;
}

function Shell() {
  const me = useMe();
  const tour = useTour();
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem("sidebar") === "collapsed"; } catch { return false; } });
  const [mobileOpen, setMobileOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const items = navItemsFor(me);
  const logo = useOrgLogo(!!me.organization_id);
  const staff = me.role === "org_admin" || me.role === "warehouse_manager";
  const showNotifications = staff || me.role === "driver";
  const swipe = useSwipeToClose(() => setMobileOpen(false));

  useEffect(() => { try { localStorage.setItem("sidebar", collapsed ? "collapsed" : "open"); } catch { /* */ } }, [collapsed]);
  useEffect(() => setMobileOpen(false), [location.pathname]);
  // نسخه نمایشی: صفحه‌های خارج از بخش‌های اصلی به داشبورد برمی‌گردند
  useEffect(() => { if (me.is_demo && !demoAllows(location.pathname)) navigate("/app", { replace: true }); }, [me.is_demo, location.pathname, navigate]);

  return (
    <div className="flex min-h-dvh bg-bg">
      {/* سایدبار دسکتاپ */}
      <aside data-testid="sidebar" data-collapsed={collapsed}
        className={cn("sticky top-0 hidden h-dvh shrink-0 flex-col border-l border-border bg-surface transition-[width] duration-300 ease-out lg:flex",
          collapsed ? "w-[76px]" : "w-[17rem]")}>
        <div className={cn("flex h-16 items-center border-b border-border", collapsed ? "justify-center" : "px-5")}>
          {collapsed ? <LogoMark /> : <Logo />}
        </div>
        <div className="flex-1 overflow-y-auto overscroll-contain p-3"><NavLinks items={items} collapsed={collapsed} /></div>
        <button onClick={() => setCollapsed(c => !c)} data-testid="sidebar-toggle" aria-label={collapsed ? "باز کردن منو" : "جمع کردن منو"}
          className="flex h-12 items-center justify-center gap-2 border-t border-border text-xs text-muted transition hover:bg-surface-2 hover:text-text">
          {collapsed ? <ChevronsLeft className="size-4" /> : <><ChevronsRight className="size-4" /> جمع کردن منو</>}
        </button>
      </aside>

      {/* منوی کشویی موبایل (iOS Safari / Android Chrome): کشیدن به راست یا لمس بیرون، می‌بندد */}
      <Dialog.Root open={mobileOpen} onOpenChange={setMobileOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50 backdrop-blur-[2px] data-[state=open]:animate-fade lg:hidden" />
          <Dialog.Content dir="rtl" data-testid="mobile-nav" {...swipe.handlers}
            style={{ transform: swipe.offset ? `translateX(${swipe.offset}px)` : undefined, transition: swipe.offset ? "none" : undefined }}
            className="fixed inset-y-0 right-0 z-50 flex w-[86vw] max-w-80 flex-col bg-surface pb-[env(safe-area-inset-bottom)] pt-[env(safe-area-inset-top)] shadow-float transition-transform duration-300 data-[state=open]:animate-[drawer-in_.28s_ease-out] lg:hidden">
            <div className="flex h-16 items-center justify-between border-b border-border px-5">
              <Dialog.Title asChild><div><Logo /></div></Dialog.Title>
              <Dialog.Close asChild><Button variant="ghost" size="icon" aria-label="بستن منو" data-testid="mobile-nav-close"><X className="size-5" /></Button></Dialog.Close>
            </div>
            <Dialog.Description className="sr-only">منوی اصلی — برای بستن به راست بکشید</Dialog.Description>
            <div className="flex-1 overflow-y-auto overscroll-contain p-3"><NavLinks items={items} collapsed={false} onNavigate={() => setMobileOpen(false)} /></div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <div className="flex min-w-0 flex-1 flex-col">
        <OfflineBanner />
        {me.is_demo && <Suspense fallback={null}><DemoChrome /></Suspense>}
        <header className="sticky top-0 z-40 flex h-16 items-center gap-3 border-b border-border bg-surface/80 px-4 backdrop-blur-xl md:px-6">
          <Button variant="ghost" size="icon" className="size-11 lg:hidden" onClick={() => setMobileOpen(true)} aria-label="منو" data-testid="mobile-nav-open"><MenuIcon className="size-5" /></Button>
          <div className="flex min-w-0 items-center gap-3">
            {logo && <img src={logo} alt="" className="size-9 rounded-lg bg-white object-contain p-0.5" />}
            <div className="min-w-0">
              <div className="truncate text-sm font-bold" data-testid="org-name">{me.organization ? me.organization.name : "پنل پلتفرم"}</div>
              <div className="truncate text-xs text-muted">{ROLE_LABELS[me.role]}</div>
            </div>
          </div>
          <div className="ms-auto flex items-center gap-1">
            {staff && <ScanButton />}
            {showNotifications && <NotificationCenter />}
            <ThemeToggle />
            <Menu trigger={
              <button className="flex items-center gap-2 rounded-xl p-1 ps-2 transition hover:bg-surface-2" data-testid="user-menu">
                <span className="hidden text-sm font-medium sm:inline">{me.full_name || me.username}</span>
                <span className="grid size-8 place-items-center rounded-lg bg-brand-soft text-brand"><UserRound className="size-4" /></span>
              </button>
            }>
              <MenuLabel>{me.full_name || me.username}{me.driver_code ? ` — ${me.driver_code}` : ""}</MenuLabel>
              {me.role === "org_admin" && !me.is_demo && <MenuItem onSelect={() => navigate("/app/organization")} icon={<Building2 className="size-4" />}>پروفایل سازمان</MenuItem>}
              {!me.is_demo && <MenuItem onSelect={() => setPasswordOpen(true)} icon={<KeyRound className="size-4" />}><span data-testid="menu-change-password">تغییر رمز عبور</span></MenuItem>}
              <MenuSeparator />
              {tour.mainTour && <MenuItem onSelect={() => tour.start(tour.mainTour!)} icon={<Compass className="size-4" />}><span data-testid="menu-tour">راهنمای استفاده</span></MenuItem>}
              {tour.pageTour && <MenuItem onSelect={() => tour.start(tour.pageTour!)} icon={<MapPinned className="size-4" />}><span data-testid="menu-page-tour">راهنمای این صفحه</span></MenuItem>}
              <MenuSeparator />
              <MenuItem onSelect={logout} danger icon={<LogOut className="size-4" />}><span data-testid="logout">خروج</span></MenuItem>
            </Menu>
          </div>
        </header>
        <Modal open={passwordOpen} onClose={() => setPasswordOpen(false)} title="تغییر رمز عبور" testId="password-modal"
          description="با تغییر رمز، از همه دستگاه‌های دیگر خارج می‌شوید؛ این دستگاه وارد می‌ماند.">
          <PasswordChangeForm onDone={() => setPasswordOpen(false)} />
        </Modal>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-8 md:py-8">
          <div key={location.pathname} className="stagger"><Outlet /></div>
        </main>
      </div>
    </div>
  );
}
