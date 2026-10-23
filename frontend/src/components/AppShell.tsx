import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import {
  BarChart3, BookOpen, Building2, ChevronsLeft, ChevronsRight, Inbox, LogOut, Menu as MenuIcon,
  Package, Route, Truck, Users, Warehouse, type LucideIcon, Building, Factory, Map as MapIcon, LifeBuoy, ClipboardCheck, UserRound, ShieldCheck, IdCard, CalendarClock, CalendarDays, Send, Mail, Trophy, Percent, FileBarChart, Wallet, History, KeyRound, ShoppingCart, PiggyBank, Compass, MapPinned, FileStack, Handshake,
} from "lucide-react";
import { api, authFetch, unwrap } from "@/api/client";
import { isApprovedDriver, useAuth, useMe } from "@/auth/AuthContext";
import { TourProvider, useTour } from "@/components/tour/TourProvider";
import { NotificationCenter } from "@/components/NotificationCenter";
import { SECTION_TONE, toneColor } from "@/ui/primitives";
import { ROLE_LABELS, type Role } from "@/lib/labels";
import { Logo, LogoMark, ThemeToggle } from "@/ui/brand";
import { Menu, MenuItem, MenuLabel, MenuSeparator, Modal, Tooltip } from "@/ui/overlays";
import { PasswordChangeForm } from "@/components/PasswordChangeForm";
import { Button, cn } from "@/ui/primitives";

type NavItem = {
  to: string; label: string; icon: LucideIcon; roles: Role[]; end?: boolean; group: string;
  /** برای راننده: فقط وقتی تأییدشده است (true) یا فقط وقتی هنوز تأیید نشده (false) */
  approvedDriver?: boolean; badge?: "pending-drivers" | "pending-requests" | "tickets" | "platform-tickets" | "stocktakes";
};

/** منوی هر نقش — گروه‌بندی‌شده */
const NAV: NavItem[] = [
  { to: "/app", label: "نمای کلی", icon: BarChart3, roles: ["org_admin", "warehouse_manager"], end: true, group: "عملیات" },
  { to: "/app/orders", label: "سفارش‌ها", icon: Package, roles: ["org_admin", "warehouse_manager"], group: "عملیات" },
  { to: "/app/map", label: "نقشه ارسال‌ها", icon: MapIcon, roles: ["org_admin", "warehouse_manager"], group: "عملیات" },
  { to: "/app/schedules", label: "برنامه رانندگان", icon: CalendarClock, roles: ["org_admin", "warehouse_manager"], group: "عملیات" },
  { to: "/app/warehouses", label: "انبارها", icon: Factory, roles: ["org_admin", "warehouse_manager"], group: "انبار" },
  { to: "/app/inventory", label: "انبار و کالاها", icon: Warehouse, roles: ["org_admin", "warehouse_manager"], group: "انبار" },
  { to: "/app/stocktakes", label: "انبارگردانی", icon: ClipboardCheck, roles: ["org_admin", "warehouse_manager"], group: "انبار", badge: "stocktakes" },
  { to: "/app/ledger", label: "دفتر گردش کالا", icon: BookOpen, roles: ["org_admin", "warehouse_manager"], group: "انبار" },
  { to: "/app/documents", label: "اسناد انبار", icon: FileStack, roles: ["org_admin", "warehouse_manager"], group: "انبار" },
  { to: "/app/partners", label: "طرف‌های تجاری", icon: Handshake, roles: ["org_admin", "warehouse_manager"], group: "انبار" },
  { to: "/app/reorder", label: "نقطه سفارش هوشمند", icon: ShoppingCart, roles: ["org_admin", "warehouse_manager"], group: "انبار" },
  { to: "/app/reports", label: "گزارش‌های اکسل و PDF", icon: FileBarChart, roles: ["org_admin", "warehouse_manager"], group: "گزارش‌ها" },
  { to: "/app/finance", label: "مالی حمل‌ونقل", icon: Wallet, roles: ["org_admin"], group: "گزارش‌ها" },
  { to: "/app/capital", label: "برآورد سرمایه خرید", icon: PiggyBank, roles: ["org_admin"], group: "گزارش‌ها" },
  { to: "/app/vehicles", label: "ناوگان", icon: Truck, roles: ["org_admin"], group: "تیم" },
  { to: "/app/users", label: "کاربران و رانندگان", icon: Users, roles: ["org_admin"], group: "تیم" },
  { to: "/app/tickets", label: "پشتیبانی و تیکت‌ها", icon: LifeBuoy, roles: ["org_admin", "warehouse_manager"], group: "عملیات", badge: "tickets" },
  { to: "/app/drivers/top", label: "برترین رانندگان", icon: Trophy, roles: ["org_admin", "warehouse_manager"], group: "تیم" },
  { to: "/app/drivers", label: "احراز هویت رانندگان", icon: ShieldCheck, roles: ["org_admin"], group: "تیم", badge: "pending-drivers", end: true },
  { to: "/app/driver-requests", label: "درخواست‌های رانندگان", icon: Mail, roles: ["org_admin"], group: "تیم", badge: "pending-requests" },
  { to: "/app/organization", label: "پروفایل سازمان", icon: Building2, roles: ["org_admin"], group: "تنظیمات" },
  { to: "/app/activity", label: "گزارش فعالیت", icon: History, roles: ["org_admin"], group: "تنظیمات" },
  { to: "/app/commission", label: "سطح‌ها و پورسانت", icon: Percent, roles: ["org_admin"], group: "تنظیمات" },
  { to: "/app/driver", label: "خودرو و سفارش‌های امروز", icon: Route, roles: ["driver"], group: "راننده", approvedDriver: true, end: true },
  { to: "/app/driver/agenda", label: "برنامه و کارنامه", icon: CalendarDays, roles: ["driver"], group: "راننده", approvedDriver: true },
  { to: "/app/driver/requests", label: "درخواست مرخصی / خودرو", icon: Send, roles: ["driver"], group: "راننده", approvedDriver: true },
  { to: "/app/driver/support", label: "پشتیبانی", icon: LifeBuoy, roles: ["driver"], group: "راننده", approvedDriver: true, badge: "tickets" },
  { to: "/app/driver/profile", label: "پروفایل من", icon: UserRound, roles: ["driver"], group: "راننده", approvedDriver: true },
  { to: "/app/onboarding", label: "تکمیل پرونده", icon: IdCard, roles: ["driver"], group: "راننده", approvedDriver: false },
  { to: "/app/platform", label: "سازمان‌ها", icon: Building, roles: ["platform_admin", "platform_support"], end: true, group: "پلتفرم" },
  { to: "/app/platform/tickets", label: "تیکت‌های پشتیبانی", icon: LifeBuoy, roles: ["platform_admin", "platform_support"], group: "پلتفرم", badge: "platform-tickets" },
  { to: "/app/platform/requests", label: "درخواست‌های ثبت سازمان", icon: Inbox, roles: ["platform_admin", "platform_support"], group: "پلتفرم" },
];

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

/** تعداد پرونده‌های راننده منتظر بررسی (برای نشان کنار منو) */
function usePendingDrivers(enabled: boolean) {
  return useQuery({
    queryKey: ["driver-pending-count"],
    queryFn: () => unwrap(api.GET("/drivers/applications/pending-count")) as Promise<{ count: number }>,
    enabled, refetchInterval: 60_000,
  }).data?.count ?? 0;
}

/** درخواست‌های منتظر رانندگان (مرخصی فوری با نشان قرمز) */
function usePendingRequests(enabled: boolean) {
  return useQuery({
    queryKey: ["driver-requests-count"],
    queryFn: () => unwrap(api.GET("/driver-requests/pending-count")) as Promise<{ count: number; urgent: number }>,
    enabled, refetchInterval: 30_000,
  }).data ?? { count: 0, urgent: 0 };
}

/** تیکت‌هایی که منتظر پاسخ این کاربرند (سازمان، راننده یا پشتیبانی پلتفرم) */
function useTicketCount(kind: "tickets" | "platform-tickets" | null) {
  return useQuery({
    queryKey: ["tickets-summary", kind],
    queryFn: () => kind === "platform-tickets" ? unwrap(api.GET("/platform/tickets/summary")) : unwrap(api.GET("/tickets/summary")),
    enabled: !!kind, refetchInterval: 30_000,
  }).data?.needs_action ?? 0;
}

function NavLinks({ items, collapsed, onNavigate }: { items: NavItem[]; collapsed: boolean; onNavigate?: () => void }) {
  const pendingDrivers = usePendingDrivers(items.some(i => i.badge === "pending-drivers"));
  const pendingRequests = usePendingRequests(items.some(i => i.badge === "pending-requests"));
  const ticketKind = items.find(i => i.badge === "tickets" || i.badge === "platform-tickets")?.badge as "tickets" | "platform-tickets" | undefined;
  const tickets = useTicketCount(ticketKind ?? null);
  const stocktakes = useQuery({
    queryKey: ["stocktakes-summary"], queryFn: () => unwrap(api.GET("/stocktakes/summary")),
    enabled: items.some(i => i.badge === "stocktakes"), refetchInterval: 60_000,
  }).data?.count ?? 0;
  const groups = [...new Set(items.map(i => i.group))];
  return (
    <nav className="flex flex-col gap-5" data-testid="app-nav">
      {groups.map(group => (
        // هر گروه منو رنگ خودش را دارد (همان رنگ برچسب بالای صفحه‌های آن بخش) — آیکن‌ها و حالت فعال با همین رنگ
        <div key={group} data-tour={`nav-${group}`} style={{
          "--g": toneColor(SECTION_TONE[group] ?? "brand"),
          "--g-soft": `var(--${SECTION_TONE[group] ?? "brand"}-soft)`,
        } as React.CSSProperties}>
          {!collapsed && <div className="mb-1.5 flex items-center gap-2 px-3 text-[11px] font-medium text-muted">
            <span className="size-1.5 rounded-full bg-[var(--g)]" />{group}</div>}
          <div className="flex flex-col gap-0.5">
            {items.filter(i => i.group === group).map(({ to, label, icon: Icon, end, badge }) => {
              const count = badge === "pending-drivers" ? pendingDrivers : badge === "pending-requests" ? pendingRequests.count
                : badge === "tickets" || badge === "platform-tickets" ? tickets : badge === "stocktakes" ? stocktakes : 0;
              const urgentBadge = badge === "pending-requests" && pendingRequests.urgent > 0;
              const link = (
                <NavLink key={to} to={to} end={end} onClick={onNavigate}
                  className={({ isActive }) => cn("group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition",
                    collapsed && "justify-center px-0",
                    isActive ? "bg-[var(--g-soft)] font-semibold text-text before:absolute before:inset-y-2 before:right-0 before:w-1 before:rounded-full before:bg-[var(--g)]"
                      : "text-text-2 hover:bg-surface-2 hover:text-text")}>
                  <span className="relative">
                    <Icon className="size-[18px] shrink-0 text-[var(--g)]" />
                    {collapsed && count > 0 && <span className="absolute -left-1.5 -top-1.5 size-2.5 rounded-full bg-warning" />}
                  </span>
                  {!collapsed && <span className="truncate">{label}</span>}
                  {!collapsed && count > 0 && (
                    <span className={cn("ms-auto grid min-w-5 place-items-center rounded-full px-1.5 text-[11px] font-bold text-white",
                      urgentBadge ? "animate-pulse bg-danger" : badge === "tickets" || badge === "platform-tickets" ? "bg-brand" : "bg-warning")}
                      data-testid={badge === "pending-requests" ? "pending-requests-badge" : badge === "pending-drivers" ? "pending-drivers-badge" : badge === "stocktakes" ? "stocktakes-badge" : "tickets-badge"}>
                      {count.toLocaleString("fa-IR")}
                    </span>
                  )}
                </NavLink>
              );
              return collapsed ? <Tooltip key={to} content={label}>{link}</Tooltip> : link;
            })}
          </div>
        </div>
      ))}
    </nav>
  );
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
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("sidebar") === "collapsed");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const items = NAV.filter(item => item.roles.includes(me.role)
    && (item.approvedDriver === undefined || item.approvedDriver === isApprovedDriver(me)));
  const logo = useOrgLogo(!!me.organization_id);
  const showNotifications = me.role === "org_admin" || me.role === "warehouse_manager" || me.role === "driver";

  useEffect(() => { try { localStorage.setItem("sidebar", collapsed ? "collapsed" : "open"); } catch { /* */ } }, [collapsed]);
  useEffect(() => setMobileOpen(false), [location.pathname]);

  return (
    <div className="flex min-h-dvh bg-bg">
      {/* سایدبار دسکتاپ */}
      <aside className={cn("sticky top-0 hidden h-dvh shrink-0 flex-col border-l border-border bg-surface transition-[width] duration-300 lg:flex",
        collapsed ? "w-[76px]" : "w-64")}>
        <div className={cn("flex h-16 items-center border-b border-border", collapsed ? "justify-center" : "px-5")}>
          {collapsed ? <LogoMark /> : <Logo />}
        </div>
        <div className="flex-1 overflow-y-auto p-3"><NavLinks items={items} collapsed={collapsed} /></div>
        <button onClick={() => setCollapsed(c => !c)} className="flex h-12 items-center justify-center gap-2 border-t border-border text-xs text-muted transition hover:text-text">
          {collapsed ? <ChevronsLeft className="size-4" /> : <><ChevronsRight className="size-4" /> جمع کردن منو</>}
        </button>
      </aside>

      {/* منوی کشویی موبایل */}
      <Dialog.Root open={mobileOpen} onOpenChange={setMobileOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50 lg:hidden" />
          <Dialog.Content dir="rtl" className="fixed inset-y-0 right-0 z-50 flex w-72 flex-col bg-surface shadow-float animate-rise lg:hidden">
            <Dialog.Title className="flex h-16 items-center border-b border-border px-5"><Logo /></Dialog.Title>
            <Dialog.Description className="sr-only">منوی اصلی</Dialog.Description>
            <div className="flex-1 overflow-y-auto p-3"><NavLinks items={items} collapsed={false} onNavigate={() => setMobileOpen(false)} /></div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 flex h-16 items-center gap-3 border-b border-border bg-surface/80 px-4 backdrop-blur-xl md:px-6">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setMobileOpen(true)} aria-label="منو"><MenuIcon className="size-5" /></Button>
          <div className="flex min-w-0 items-center gap-3">
            {logo && <img src={logo} alt="" className="size-9 rounded-lg bg-white object-contain p-0.5" />}
            <div className="min-w-0">
              <div className="truncate text-sm font-bold" data-testid="org-name">{me.organization ? me.organization.name : "پنل پلتفرم"}</div>
              <div className="truncate text-xs text-muted">{ROLE_LABELS[me.role]}</div>
            </div>
          </div>
          <div className="ms-auto flex items-center gap-1">
            {showNotifications && <NotificationCenter />}
            <ThemeToggle />
            <Menu trigger={
              <button className="flex items-center gap-2 rounded-xl p-1 ps-2 transition hover:bg-surface-2" data-testid="user-menu">
                <span className="hidden text-sm font-medium sm:inline">{me.full_name || me.username}</span>
                <span className="grid size-8 place-items-center rounded-lg bg-brand-soft text-brand"><UserRound className="size-4" /></span>
              </button>
            }>
              <MenuLabel>{me.full_name || me.username}{me.driver_code ? ` — ${me.driver_code}` : ""}</MenuLabel>
              {me.role === "org_admin" && <MenuItem onSelect={() => navigate("/app/organization")} icon={<Building2 className="size-4" />}>پروفایل سازمان</MenuItem>}
              <MenuItem onSelect={() => setPasswordOpen(true)} icon={<KeyRound className="size-4" />}><span data-testid="menu-change-password">تغییر رمز عبور</span></MenuItem>
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
