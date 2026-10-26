/**
 * منوی اصلی پنل: شش گروه کاری (داشبورد، عملیات انبار، اطلاعات پایه، لجستیک، گزارش و تحلیل، سیستم) + منوی راننده و پلتفرم.
 * هر گروه جمع/باز می‌شود (وضعیت روی همین مرورگر می‌ماند) و گروهی که صفحه فعلی در آن است همیشه باز است.
 * مورد منو با نقش کاربر و مجوزهای ریز او (MeResponse.permissions) نشان داده می‌شود؛ بررسی واقعی سمت سرور است.
 */
import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeftRight, BarChart3, BookOpen, Building, Building2, CalendarClock, CalendarDays, ChevronDown, ClipboardCheck, ClipboardList,
  Factory, FileBarChart, FileStack, FlaskConical, Gauge, GitBranch, Handshake, Hourglass, IdCard, Inbox, KeyRound, LayoutDashboard,
  LifeBuoy, ListChecks, Mail, Map as MapIcon, MapPinned, Package, PackageCheck, PackageOpen, Percent, PiggyBank, Recycle, Repeat,
  Rocket, Route, ScanLine, Send, ShieldCheck, ShoppingCart, Tags, Trophy, Truck, UserRound, Users, Wallet, Warehouse, Gem, History,
  type LucideIcon,
} from "lucide-react";
import { api, unwrap } from "@/api/client";
import type { Me } from "@/auth/AuthContext";
import { isApprovedDriver } from "@/auth/AuthContext";
import type { Role } from "@/lib/labels";
import { Tooltip } from "@/ui/overlays";
import { cn, toneColor, type Tone } from "@/ui/primitives";

export type NavItem = {
  to: string; label: string; icon: LucideIcon; roles: Role[]; end?: boolean; group: GroupId;
  /** برای راننده: فقط وقتی تأییدشده است (true) یا فقط وقتی هنوز تأیید نشده (false) */
  approvedDriver?: boolean; badge?: "pending-drivers" | "pending-requests" | "tickets" | "platform-tickets" | "stocktakes";
  /** مجوز ریز لازم (app/core/permissions.py) */
  perm?: string;
};

export type GroupId = "overview" | "operations" | "master" | "logistics" | "reports" | "system" | "driver" | "platform";
export const GROUPS: { id: GroupId; label: string; tone: Tone; icon: LucideIcon }[] = [
  { id: "overview", label: "داشبورد و نمای کلی", tone: "brand", icon: LayoutDashboard },
  { id: "operations", label: "عملیات انبار", tone: "info", icon: Warehouse },
  { id: "master", label: "اطلاعات پایه", tone: "accent", icon: Factory },
  { id: "logistics", label: "لجستیک و ارسال", tone: "orange", icon: Truck },
  { id: "reports", label: "گزارش و تحلیل", tone: "violet", icon: FileBarChart },
  { id: "system", label: "سیستم و مدیریت", tone: "pink", icon: ShieldCheck },
  { id: "driver", label: "راننده", tone: "brand", icon: Route },
  { id: "platform", label: "پلتفرم", tone: "violet", icon: Building },
];

const STAFF: Role[] = ["org_admin", "warehouse_manager"];
const ADMIN: Role[] = ["org_admin"];
const PLATFORM: Role[] = ["platform_admin", "platform_support"];

export const NAV: NavItem[] = [
  // داشبورد و نمای کلی
  { to: "/app", label: "نمای کلی", icon: BarChart3, roles: STAFF, end: true, group: "overview" },
  { to: "/app/analytics", label: "شاخص‌های عملکرد", icon: Gauge, roles: STAFF, group: "overview", perm: "analytics.view" },
  { to: "/app/map", label: "نقشه ارسال‌ها", icon: MapIcon, roles: STAFF, group: "overview" },
  // عملیات انبار
  { to: "/app/receipts", label: "رسید و دریافت", icon: PackageOpen, roles: STAFF, group: "operations" },
  { to: "/app/quality", label: "بازرسی کیفی", icon: FlaskConical, roles: STAFF, group: "operations" },
  { to: "/app/putaway", label: "جانمایی", icon: ScanLine, roles: STAFF, group: "operations" },
  { to: "/app/picking", label: "پیکینگ", icon: ListChecks, roles: STAFF, group: "operations" },
  { to: "/app/shipping", label: "بسته‌بندی و ارسال", icon: PackageCheck, roles: STAFF, group: "operations" },
  { to: "/app/transfers", label: "سفارش انتقال", icon: ArrowLeftRight, roles: STAFF, group: "operations" },
  { to: "/app/replenishment", label: "تأمین مجدد و ABC", icon: Repeat, roles: STAFF, group: "operations" },
  { to: "/app/dispositions", label: "تعیین تکلیف معیوب", icon: Recycle, roles: STAFF, group: "operations" },
  { to: "/app/stocktakes", label: "انبارگردانی", icon: ClipboardCheck, roles: STAFF, group: "operations", badge: "stocktakes" },
  { to: "/app/labels", label: "برچسب و بارکد", icon: Tags, roles: STAFF, group: "operations", perm: "labels.print" },
  // اطلاعات پایه
  { to: "/app/warehouses", label: "انبارها", icon: Factory, roles: STAFF, group: "master" },
  { to: "/app/locations", label: "محل‌های انبار", icon: MapPinned, roles: STAFF, group: "master" },
  { to: "/app/inventory", label: "انبار و کالاها", icon: Warehouse, roles: STAFF, group: "master" },
  { to: "/app/partners", label: "طرف‌های تجاری", icon: Handshake, roles: STAFF, group: "master" },
  { to: "/app/vehicles", label: "ناوگان", icon: Truck, roles: ADMIN, group: "master" },
  // لجستیک و ارسال
  { to: "/app/orders", label: "سفارش‌ها", icon: Package, roles: STAFF, group: "logistics" },
  { to: "/app/backorders", label: "سفارش‌های معوق", icon: Hourglass, roles: STAFF, group: "logistics" },
  { to: "/app/schedules", label: "برنامه رانندگان", icon: CalendarClock, roles: STAFF, group: "logistics" },
  { to: "/app/drivers/top", label: "برترین رانندگان", icon: Trophy, roles: STAFF, group: "logistics" },
  { to: "/app/drivers", label: "احراز هویت رانندگان", icon: ShieldCheck, roles: ADMIN, group: "logistics", badge: "pending-drivers", end: true },
  { to: "/app/driver-requests", label: "درخواست‌های رانندگان", icon: Mail, roles: ADMIN, group: "logistics", badge: "pending-requests" },
  { to: "/app/tickets", label: "پشتیبانی و تیکت‌ها", icon: LifeBuoy, roles: STAFF, group: "logistics", badge: "tickets" },
  // گزارش و تحلیل
  { to: "/app/reports", label: "مرکز گزارش و خروجی", icon: FileBarChart, roles: STAFF, group: "reports" },
  { to: "/app/valuation", label: "ارزش‌گذاری و کالای راکد", icon: Gem, roles: STAFF, group: "reports", perm: "valuation.view" },
  { to: "/app/ledger", label: "دفتر گردش کالا", icon: BookOpen, roles: STAFF, group: "reports" },
  { to: "/app/stock-card", label: "کاردکس کالا", icon: ClipboardList, roles: STAFF, group: "reports" },
  { to: "/app/documents", label: "اسناد انبار", icon: FileStack, roles: STAFF, group: "reports" },
  { to: "/app/reorder", label: "نقطه سفارش هوشمند", icon: ShoppingCart, roles: STAFF, group: "reports" },
  { to: "/app/finance", label: "مالی حمل‌ونقل", icon: Wallet, roles: ADMIN, group: "reports" },
  { to: "/app/capital", label: "برآورد سرمایه خرید", icon: PiggyBank, roles: ADMIN, group: "reports" },
  // سیستم و مدیریت
  { to: "/app/users", label: "کاربران و رانندگان", icon: Users, roles: ADMIN, group: "system" },
  { to: "/app/permissions", label: "مجوزهای نقش‌ها", icon: KeyRound, roles: ADMIN, group: "system", perm: "permissions.manage" },
  { to: "/app/activity", label: "گزارش فعالیت", icon: History, roles: STAFF, group: "system", perm: "audit.view" },
  { to: "/app/workflows", label: "گردش‌کار اسناد", icon: GitBranch, roles: STAFF, group: "system" },
  { to: "/app/readiness", label: "آمادگی راه‌اندازی", icon: Rocket, roles: STAFF, group: "system", perm: "cutover.manage" },
  { to: "/app/organization", label: "پروفایل سازمان", icon: Building2, roles: ADMIN, group: "system" },
  { to: "/app/commission", label: "سطح‌ها و پورسانت", icon: Percent, roles: ADMIN, group: "system" },
  // راننده
  { to: "/app/driver", label: "خودرو و سفارش‌های امروز", icon: Route, roles: ["driver"], group: "driver", approvedDriver: true, end: true },
  { to: "/app/driver/agenda", label: "برنامه و کارنامه", icon: CalendarDays, roles: ["driver"], group: "driver", approvedDriver: true },
  { to: "/app/driver/requests", label: "درخواست مرخصی / خودرو", icon: Send, roles: ["driver"], group: "driver", approvedDriver: true },
  { to: "/app/driver/support", label: "پشتیبانی", icon: LifeBuoy, roles: ["driver"], group: "driver", approvedDriver: true, badge: "tickets" },
  { to: "/app/driver/profile", label: "پروفایل من", icon: UserRound, roles: ["driver"], group: "driver", approvedDriver: true },
  { to: "/app/onboarding", label: "تکمیل پرونده", icon: IdCard, roles: ["driver"], group: "driver", approvedDriver: false },
  // پلتفرم
  { to: "/app/platform", label: "سازمان‌ها", icon: Building, roles: PLATFORM, end: true, group: "platform" },
  { to: "/app/platform/tickets", label: "تیکت‌های پشتیبانی", icon: LifeBuoy, roles: PLATFORM, group: "platform", badge: "platform-tickets" },
  { to: "/app/platform/requests", label: "درخواست‌های ثبت سازمان", icon: Inbox, roles: PLATFORM, group: "platform" },
];

export function navItemsFor(me: Me): NavItem[] {
  const perms = new Set(me.permissions ?? []);
  return NAV.filter(item => item.roles.includes(me.role)
    && (item.approvedDriver === undefined || item.approvedDriver === isApprovedDriver(me))
    && (!item.perm || perms.has(item.perm)));
}

/** مسیر فعلی در کدام مورد منوست (طولانی‌ترین تطبیق) */
function activeItem(items: NavItem[], path: string): NavItem | undefined {
  return items.filter(i => i.end ? path === i.to || path === `${i.to}/` : path === i.to || path.startsWith(`${i.to}/`))
    .sort((a, b) => b.to.length - a.to.length)[0];
}

const STORE_KEY = "nav-closed-groups";
function useClosedGroups() {
  const [closed, setClosed] = useState<GroupId[]>(() => {
    try { return JSON.parse(localStorage.getItem(STORE_KEY) ?? "[]"); } catch { return []; }
  });
  useEffect(() => { try { localStorage.setItem(STORE_KEY, JSON.stringify(closed)); } catch { /* */ } }, [closed]);
  const toggle = (id: GroupId) => setClosed(c => c.includes(id) ? c.filter(x => x !== id) : [...c, id]);
  return { closed, toggle };
}

function useBadges(items: NavItem[]) {
  const has = (b: NavItem["badge"]) => items.some(i => i.badge === b);
  const pendingDrivers = useQuery({
    queryKey: ["driver-pending-count"],
    queryFn: () => unwrap(api.GET("/drivers/applications/pending-count")) as Promise<{ count: number }>,
    enabled: has("pending-drivers"), refetchInterval: 60_000,
  }).data?.count ?? 0;
  const requests = useQuery({
    queryKey: ["driver-requests-count"],
    queryFn: () => unwrap(api.GET("/driver-requests/pending-count")) as Promise<{ count: number; urgent: number }>,
    enabled: has("pending-requests"), refetchInterval: 30_000,
  }).data ?? { count: 0, urgent: 0 };
  const ticketKind = has("platform-tickets") ? "platform-tickets" : has("tickets") ? "tickets" : null;
  const tickets = useQuery({
    queryKey: ["tickets-summary", ticketKind],
    queryFn: () => ticketKind === "platform-tickets" ? unwrap(api.GET("/platform/tickets/summary")) : unwrap(api.GET("/tickets/summary")),
    enabled: !!ticketKind, refetchInterval: 30_000,
  }).data?.needs_action ?? 0;
  const stocktakes = useQuery({
    queryKey: ["stocktakes-summary"], queryFn: () => unwrap(api.GET("/stocktakes/summary")),
    enabled: has("stocktakes"), refetchInterval: 60_000,
  }).data?.count ?? 0;
  return {
    count: (b?: NavItem["badge"]) => b === "pending-drivers" ? pendingDrivers : b === "pending-requests" ? requests.count
      : b === "tickets" || b === "platform-tickets" ? tickets : b === "stocktakes" ? stocktakes : 0,
    urgent: requests.urgent > 0,
  };
}

const BADGE_TESTID: Record<string, string> = {
  "pending-requests": "pending-requests-badge", "pending-drivers": "pending-drivers-badge", stocktakes: "stocktakes-badge",
  tickets: "tickets-badge", "platform-tickets": "tickets-badge",
};

export function NavLinks({ items, collapsed, onNavigate }: { items: NavItem[]; collapsed: boolean; onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const { closed, toggle } = useClosedGroups();
  const badges = useBadges(items);
  const current = activeItem(items, pathname);
  const groups = GROUPS.filter(g => items.some(i => i.group === g.id));
  return (
    <nav className="flex flex-col gap-1.5" data-testid="app-nav">
      {groups.map(group => {
        const groupItems = items.filter(i => i.group === group.id);
        const containsActive = current?.group === group.id;
        const open = collapsed || containsActive || !closed.includes(group.id);
        const total = groupItems.reduce((s, i) => s + badges.count(i.badge), 0);
        const GroupIcon = group.icon;
        return (
          // هر گروه رنگ خودش را دارد — آیکن‌ها، خط کنار گروه و حالت فعال با همین رنگ
          <div key={group.id} data-tour={`nav-${group.id}`} data-group={group.id} data-open={open}
            style={{ "--g": toneColor(group.tone), "--g-soft": `var(--${group.tone}-soft)` } as React.CSSProperties}>
            {collapsed ? <div className="mx-auto my-1.5 h-px w-8 bg-border" /> : (
              <button type="button" onClick={() => !containsActive && toggle(group.id)} aria-expanded={open}
                data-testid={`nav-group-${group.id}`}
                className={cn("flex w-full items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-semibold text-muted transition hover:bg-surface-2 hover:text-text",
                  containsActive && "text-text")}>
                <span className="grid size-6 place-items-center rounded-md bg-[var(--g-soft)] text-[var(--g)]"><GroupIcon className="size-3.5" /></span>
                <span className="truncate">{group.label}</span>
                {!open && total > 0 && <span className="grid min-w-5 place-items-center rounded-full bg-warning px-1.5 text-[10px] font-bold text-white">
                  {total.toLocaleString("fa-IR")}</span>}
                <ChevronDown className={cn("ms-auto size-3.5 shrink-0 transition-transform duration-300", !open && "rotate-90")} />
              </button>
            )}
            <div className={cn("grid transition-[grid-template-rows,opacity] duration-300 ease-out", open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0")}>
              <div className={cn("flex flex-col gap-0.5 overflow-hidden", !collapsed && "ms-3 border-s border-border/70 ps-2")}>
                {groupItems.map(({ to, label, icon: Icon, end, badge }) => {
                  const count = badges.count(badge);
                  const urgent = badge === "pending-requests" && badges.urgent;
                  const link = (
                    <NavLink key={to} to={to} end={end} onClick={onNavigate} tabIndex={open ? undefined : -1}
                      className={({ isActive }) => cn("group relative flex min-h-11 items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors duration-200 lg:min-h-10",
                        collapsed && "justify-center px-0",
                        isActive ? "bg-[var(--g-soft)] font-semibold text-text before:absolute before:inset-y-2 before:right-0 before:w-1 before:rounded-full before:bg-[var(--g)]"
                          : "text-text-2 hover:bg-surface-2 hover:text-text")}>
                      <span className="relative">
                        <Icon className="size-[18px] shrink-0 text-[var(--g)] transition-transform duration-200 group-hover:scale-110" />
                        {collapsed && count > 0 && <span className="absolute -left-1.5 -top-1.5 size-2.5 rounded-full bg-warning" />}
                      </span>
                      {!collapsed && <span className="truncate">{label}</span>}
                      {!collapsed && count > 0 && (
                        <span className={cn("ms-auto grid min-w-5 place-items-center rounded-full px-1.5 text-[11px] font-bold text-white",
                          urgent ? "animate-pulse bg-danger" : badge === "tickets" || badge === "platform-tickets" ? "bg-brand" : "bg-warning")}
                          data-testid={BADGE_TESTID[badge!]}>
                          {count.toLocaleString("fa-IR")}
                        </span>
                      )}
                    </NavLink>
                  );
                  return collapsed ? <Tooltip key={to} content={label}>{link}</Tooltip> : link;
                })}
              </div>
            </div>
          </div>
        );
      })}
    </nav>
  );
}
