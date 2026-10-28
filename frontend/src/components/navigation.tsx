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
  Factory, FileBarChart, FileStack, FlaskConical, Gauge, GitBranch, Handshake, Hourglass, IdCard, Inbox, KeyRound,
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
export const GROUPS: { id: GroupId; label: string; tone: Tone }[] = [
  { id: "overview", label: "داشبورد و نمای کلی", tone: "brand" },
  { id: "operations", label: "عملیات انبار", tone: "info" },
  { id: "master", label: "اطلاعات پایه", tone: "accent" },
  { id: "logistics", label: "لجستیک و ارسال", tone: "orange" },
  { id: "reports", label: "گزارش و تحلیل", tone: "violet" },
  { id: "system", label: "سیستم و مدیریت", tone: "pink" },
  { id: "driver", label: "راننده", tone: "brand" },
  { id: "platform", label: "پلتفرم", tone: "violet" },
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

/** نسخه نمایشی خصوصی فقط بخش‌های اصلی را دارد (سرور هم بقیه را رد می‌کند — app/core/demo.py) */
const DEMO_PATHS = ["/app", "/app/analytics", "/app/map", "/app/receipts", "/app/quality", "/app/putaway", "/app/picking", "/app/shipping",
  "/app/stocktakes", "/app/inventory", "/app/orders", "/app/backorders", "/app/schedules", "/app/drivers", "/app/driver-requests", "/app/tickets"];

export function demoAllows(path: string): boolean {
  const clean = path.replace(/\/+$/, "") || "/app";
  return DEMO_PATHS.some(p => clean === p || (p !== "/app" && clean.startsWith(`${p}/`)));
}

export function navItemsFor(me: Me): NavItem[] {
  const perms = new Set(me.permissions ?? []);
  return NAV.filter(item => item.roles.includes(me.role)
    && (item.approvedDriver === undefined || item.approvedDriver === isApprovedDriver(me))
    && (!item.perm || perms.has(item.perm))
    && (!me.is_demo || demoAllows(item.to)));
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
    <nav className="flex flex-col" data-testid="app-nav">
      {groups.map((group, index) => {
        const groupItems = items.filter(i => i.group === group.id);
        const containsActive = current?.group === group.id;
        const open = collapsed || containsActive || !closed.includes(group.id);
        const total = groupItems.reduce((s, i) => s + badges.count(i.badge), 0);
        return (
          // آیکن‌ها تک‌رنگ‌اند؛ رنگ هر گروه فقط در نقطه کوچک کنار عنوانش می‌ماند
          <div key={group.id} data-tour={`nav-${group.id}`} data-group={group.id} data-open={open}
            className={cn(index > 0 && "mt-2 border-t border-border/70 pt-2")}>
            {!collapsed && (
              <button type="button" onClick={() => !containsActive && toggle(group.id)} aria-expanded={open}
                data-testid={`nav-group-${group.id}`}
                className={cn("group/head flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium text-muted transition-colors duration-200 hover:text-text",
                  containsActive && "text-text-2")}>
                <span className="size-1.5 shrink-0 rounded-full" style={{ background: toneColor(group.tone) }} />
                <span className="truncate">{group.label}</span>
                {!open && total > 0 && <span className="ms-auto tabular-nums">{total.toLocaleString("fa-IR")}</span>}
                <ChevronDown className={cn("size-3.5 shrink-0 transition duration-300", !(!open && total > 0) && "ms-auto",
                  open ? "opacity-0 group-hover/head:opacity-100" : "rotate-90")} />
              </button>
            )}
            <div className={cn("grid transition-[grid-template-rows,opacity] duration-300 ease-out", open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0")}>
              <div className={cn("flex flex-col gap-0.5 overflow-hidden", !collapsed && "pt-0.5")}>
                {groupItems.map(({ to, label, icon: Icon, end, badge }) => {
                  const count = badges.count(badge);
                  const urgent = badge === "pending-requests" && badges.urgent;
                  const link = (
                    <NavLink key={to} to={to} end={end} onClick={onNavigate} tabIndex={open ? undefined : -1}
                      className={({ isActive }) => cn("group relative flex h-11 shrink-0 items-center gap-3 rounded-xl border px-3 text-sm transition-[background-color,border-color,color,box-shadow] duration-200 lg:h-10",
                        // جمع‌شده فقط باریک می‌شود و وسط‌چین نمی‌شود تا آیکن در انیمیشن عرض جابه‌جا نشود
                        collapsed && "w-11",
                        // آیتم فعال کارتی برجسته روی زمینه منوست
                        isActive ? "border-border bg-surface font-semibold text-text shadow-sm dark:bg-surface-2"
                          : "border-transparent font-medium text-text-2 hover:bg-surface/70 hover:text-text dark:hover:bg-surface-2/60")}>
                      {({ isActive }) => <>
                        <span className="relative">
                          <Icon className={cn("size-[18px] shrink-0 transition-colors duration-200", isActive ? "text-brand" : "text-muted group-hover:text-text")} />
                          {collapsed && count > 0 && <span className={cn("absolute -left-1 -top-1 size-2 rounded-full ring-2 ring-surface-2 dark:ring-surface", urgent ? "bg-danger" : "bg-warning")} />}
                        </span>
                        {!collapsed && <span className="truncate">{label}</span>}
                        {!collapsed && count > 0 && (
                          <span className={cn("ms-auto tabular-nums", urgent ? "grid min-w-5 animate-pulse place-items-center rounded-full bg-danger px-1.5 text-[11px] font-bold text-white" : "text-xs text-muted")}
                            data-testid={BADGE_TESTID[badge!]}>
                            {count.toLocaleString("fa-IR")}
                          </span>
                        )}
                      </>}
                    </NavLink>
                  );
                  // Tooltip کلاس‌های خودش را با className لینک ادغام می‌کند؛ ظرف جدا، className تابعی NavLink را دست‌نخورده نگه می‌دارد
                  return collapsed ? <Tooltip key={to} content={label}><div className="flex">{link}</div></Tooltip> : link;
                })}
              </div>
            </div>
          </div>
        );
      })}
    </nav>
  );
}
