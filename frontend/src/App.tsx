import { lazy, Suspense, useLayoutEffect, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, homePathFor, isApprovedDriver, useAuth } from "./auth/AuthContext";
import { AppShell } from "./components/AppShell";
import type { Role } from "./lib/labels";
import { Spinner } from "./ui/primitives";

// هر صفحه جدا بارگذاری می‌شود — بازدیدکننده صفحه اصلی کد پنل‌ها را دانلود نمی‌کند و برعکس
const LandingPage = lazy(() => import("./pages/public/LandingPage"));
const RequestPage = lazy(() => import("./pages/public/RequestPage"));
const JoinPage = lazy(() => import("./pages/public/JoinPage"));
const RatePage = lazy(() => import("./pages/public/RatePage"));
const TrackPage = lazy(() => import("./pages/public/TrackPage"));
const AboutPage = lazy(() => import("./pages/public/AboutPage"));
const SupportPage = lazy(() => import("./pages/public/SupportPage"));
const OrgTicketsPage = lazy(() => import("./pages/tickets/TicketsPage").then(m => ({ default: m.OrgTicketsPage })));
const DriverSupportPage = lazy(() => import("./pages/tickets/TicketsPage").then(m => ({ default: m.DriverSupportPage })));
const PlatformTicketsPage = lazy(() => import("./pages/tickets/TicketsPage").then(m => ({ default: m.PlatformTicketsPage })));
const FaqPage = lazy(() => import("./pages/public/FaqPage"));
const TermsPage = lazy(() => import("./pages/public/TermsPage"));
const PrivacyPage = lazy(() => import("./pages/public/PrivacyPage"));
const PricingPage = lazy(() => import("./pages/public/PricingPage"));
const ForgotPasswordPage = lazy(() => import("./pages/ForgotPasswordPage"));
const LoginPage = lazy(() => import("./pages/LoginPage"));
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const OrdersPage = lazy(() => import("./pages/orders/OrdersPage"));
const InventoryPage = lazy(() => import("./pages/inventory/InventoryPage"));
const LedgerPage = lazy(() => import("./pages/inventory/LedgerPage"));
const DocumentsPage = lazy(() => import("./pages/inventory/DocumentsPage"));
const StockCardPage = lazy(() => import("./pages/inventory/StockCardPage"));
const LocationsPage = lazy(() => import("./pages/warehouse/LocationsPage"));
const ReceiptsPage = lazy(() => import("./pages/warehouse/ReceiptsPage"));
const QualityPage = lazy(() => import("./pages/warehouse/QualityPage"));
const PutawayPage = lazy(() => import("./pages/warehouse/PutawayPage"));
const PartnersPage = lazy(() => import("./pages/PartnersPage"));
const ChangePasswordPage = lazy(() => import("./pages/ChangePasswordPage"));
const UserDetailPage = lazy(() => import("./pages/users/UserDetailPage"));
const ActivityPage = lazy(() => import("./pages/users/ActivityPage"));
const ReportsPage = lazy(() => import("./pages/reports/ReportsPage"));
const FinancePage = lazy(() => import("./pages/reports/FinancePage"));
const CapitalPlanPage = lazy(() => import("./pages/reports/CapitalPlanPage"));
const ReorderPage = lazy(() => import("./pages/inventory/ReorderPage"));
const MapPage = lazy(() => import("./pages/MapPage"));
const StocktakesPage = lazy(() => import("./pages/stocktakes/StocktakesPage"));
const StocktakeDetailPage = lazy(() => import("./pages/stocktakes/StocktakeDetailPage"));
const WarehousesPage = lazy(() => import("./pages/WarehousesPage"));
const VehiclesPage = lazy(() => import("./pages/VehiclesPage"));
const UsersPage = lazy(() => import("./pages/users/UsersPage"));
const OrganizationPage = lazy(() => import("./pages/OrganizationPage"));
const DriverPage = lazy(() => import("./pages/DriverPage"));
const SchedulesPage = lazy(() => import("./pages/SchedulesPage"));
const OnboardingPage = lazy(() => import("./pages/driver/OnboardingPage"));
const AgendaPage = lazy(() => import("./pages/driver/AgendaPage"));
const DriverRequestsPage = lazy(() => import("./pages/driver/DriverRequestsPage"));
const DriverProfilePage = lazy(() => import("./pages/driver/DriverProfilePage"));
const DriverRequestsReviewPage = lazy(() => import("./pages/drivers/DriverRequestsReviewPage"));
const TopDriversPage = lazy(() => import("./pages/drivers/TopDriversPage"));
const DriverOverviewPage = lazy(() => import("./pages/drivers/DriverOverviewPage"));
const CommissionPlanPage = lazy(() => import("./pages/CommissionPlanPage"));
const DriverReviewPage = lazy(() => import("./pages/drivers/DriverReviewPage"));
const OrganizationsPage = lazy(() => import("./pages/platform/OrganizationsPage"));
const RequestsPage = lazy(() => import("./pages/platform/RequestsPage"));

const ORG_STAFF: Role[] = ["org_admin", "warehouse_manager"];
const PLATFORM: Role[] = ["platform_admin", "platform_support"];

function PageLoader() {
  return <div className="grid min-h-[50vh] place-items-center" data-testid="loading"><Spinner className="size-7" /></div>;
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  const location = useLocation();
  if (loading) return <PageLoader />;
  if (!me) return <Navigate to="/app/login" replace state={{ from: location.pathname }} />;
  if (me.must_change_password) return <Navigate to="/app/change-password" replace />;
  return <>{children}</>;
}

/** فقط ورود لازم است (صفحه تغییر اجباری رمز) */
function RequireLogin({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  if (loading) return <PageLoader />;
  if (!me) return <Navigate to="/app/login" replace />;
  return <>{children}</>;
}

/** هر نقش فقط صفحات خودش؛ در غیر این صورت به صفحه اول نقش خودش می‌رود. */
function RequireRole({ roles, children, onboarding = false }: { roles: Role[]; children: ReactNode; onboarding?: boolean }) {
  const { me } = useAuth();
  if (!me) return null;
  if (!roles.includes(me.role)) return <Navigate to={homePathFor(me)} replace />;
  // راننده تأییدنشده فقط فرم احراز هویت را می‌بیند؛ راننده تأییدشده دیگر به آن نیازی ندارد
  if (me.role === "driver" && isApprovedDriver(me) === onboarding) return <Navigate to={homePathFor(me)} replace />;
  return <>{children}</>;
}

/**
 * با هر رفتن به صفحه دیگر، صفحه جدید از بالا شروع شود (نه از جایی که در صفحه قبل بودیم).
 * لینک لنگردار (مثل /#faq) به همان بخش می‌رود. تغییر فقط query (مثل فیلترهای جستجو) اسکرول را عوض نمی‌کند.
 */
function ScrollManager() {
  const { pathname, hash } = useLocation();
  useLayoutEffect(() => {
    if (hash) {
      const target = document.querySelector(hash);
      if (target) { target.scrollIntoView(); return; }
    }
    const toTop = () => window.scrollTo({ top: 0, left: 0, behavior: "instant" as ScrollBehavior });
    toTop();
    // یک فریم بعد دوباره: صفحه تنبل‌بارگذاری‌شده تازه رسم شده یا اسکرول نرم صفحه قبل هنوز در جریان است
    const frame = requestAnimationFrame(toTop);
    return () => cancelAnimationFrame(frame);
  }, [pathname, hash]);
  return null;
}

/** صفحات خارج از پنل (صفحه اصلی، ورود، پیگیری، ...) نرم ظاهر می‌شوند */
const fade = (page: ReactNode) => <div className="page-fade">{page}</div>;

function HomeRedirect() {
  const { me } = useAuth();
  return <Navigate to={me ? homePathFor(me) : "/app/login"} replace />;
}

const guard = (roles: Role[], page: ReactNode) => <RequireRole roles={roles}>{page}</RequireRole>;

export function App() {
  return (
    <AuthProvider>
      <ScrollManager />
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/" element={fade(<LandingPage />)} />
          <Route path="/request" element={fade(<RequestPage />)} />
          <Route path="/join/:code" element={fade(<JoinPage />)} />
          <Route path="/rate/:code" element={fade(<RatePage />)} />
          <Route path="/track" element={fade(<TrackPage />)} />
          <Route path="/track/:code" element={fade(<TrackPage />)} />
          <Route path="/about" element={fade(<AboutPage />)} />
          <Route path="/faq" element={fade(<FaqPage />)} />
          <Route path="/terms" element={fade(<TermsPage />)} />
          <Route path="/privacy" element={fade(<PrivacyPage />)} />
          <Route path="/pricing" element={fade(<PricingPage />)} />
          <Route path="/support/:token" element={fade(<SupportPage />)} />
          <Route path="/app/login" element={fade(<LoginPage />)} />
          <Route path="/app/forgot-password" element={fade(<ForgotPasswordPage />)} />
          <Route path="/app/change-password" element={<RequireLogin>{fade(<ChangePasswordPage />)}</RequireLogin>} />
          <Route path="/app" element={<RequireAuth><AppShell /></RequireAuth>}>
            <Route index element={guard(ORG_STAFF, <DashboardPage />)} />
            <Route path="orders" element={guard(ORG_STAFF, <OrdersPage />)} />
            <Route path="schedules" element={guard(ORG_STAFF, <SchedulesPage />)} />
            <Route path="map" element={guard(ORG_STAFF, <MapPage />)} />
            <Route path="warehouses" element={guard(ORG_STAFF, <WarehousesPage />)} />
            <Route path="stocktakes" element={guard(ORG_STAFF, <StocktakesPage />)} />
            <Route path="stocktakes/:id" element={guard(ORG_STAFF, <StocktakeDetailPage />)} />
            <Route path="inventory" element={guard(ORG_STAFF, <InventoryPage />)} />
            <Route path="ledger" element={guard(ORG_STAFF, <LedgerPage />)} />
            <Route path="documents" element={guard(ORG_STAFF, <DocumentsPage />)} />
            <Route path="stock-card" element={guard(ORG_STAFF, <StockCardPage />)} />
            <Route path="locations" element={guard(ORG_STAFF, <LocationsPage />)} />
            <Route path="receipts" element={guard(ORG_STAFF, <ReceiptsPage />)} />
            <Route path="quality" element={guard(ORG_STAFF, <QualityPage />)} />
            <Route path="putaway" element={guard(ORG_STAFF, <PutawayPage />)} />
            <Route path="partners" element={guard(ORG_STAFF, <PartnersPage />)} />
            <Route path="reports" element={guard(ORG_STAFF, <ReportsPage />)} />
            <Route path="finance" element={guard(["org_admin"], <FinancePage />)} />
            <Route path="capital" element={guard(["org_admin"], <CapitalPlanPage />)} />
            <Route path="reorder" element={guard(ORG_STAFF, <ReorderPage />)} />
            <Route path="vehicles" element={guard(["org_admin"], <VehiclesPage />)} />
            <Route path="users" element={guard(["org_admin"], <UsersPage />)} />
            <Route path="users/:id" element={guard(["org_admin"], <UserDetailPage />)} />
            <Route path="activity" element={guard(["org_admin"], <ActivityPage />)} />
            <Route path="organization" element={guard(["org_admin"], <OrganizationPage />)} />
            <Route path="drivers" element={guard(["org_admin"], <DriverReviewPage />)} />
            <Route path="drivers/top" element={guard(ORG_STAFF, <TopDriversPage />)} />
            <Route path="drivers/:id" element={guard(ORG_STAFF, <DriverOverviewPage />)} />
            <Route path="commission" element={guard(ORG_STAFF, <CommissionPlanPage />)} />
            <Route path="driver-requests" element={guard(["org_admin"], <DriverRequestsReviewPage />)} />
            <Route path="driver" element={guard(["driver"], <DriverPage />)} />
            <Route path="driver/agenda" element={guard(["driver"], <AgendaPage />)} />
            <Route path="driver/requests" element={guard(["driver"], <DriverRequestsPage />)} />
            <Route path="driver/profile" element={guard(["driver"], <DriverProfilePage />)} />
            <Route path="driver/support" element={guard(["driver"], <DriverSupportPage />)} />
            <Route path="driver/support/:id" element={guard(["driver"], <DriverSupportPage />)} />
            <Route path="tickets" element={guard(ORG_STAFF, <OrgTicketsPage />)} />
            <Route path="tickets/:id" element={guard(ORG_STAFF, <OrgTicketsPage />)} />
            <Route path="platform/tickets" element={guard(PLATFORM, <PlatformTicketsPage />)} />
            <Route path="platform/tickets/:id" element={guard(PLATFORM, <PlatformTicketsPage />)} />
            <Route path="onboarding" element={<RequireRole roles={["driver"]} onboarding><OnboardingPage /></RequireRole>} />
            <Route path="platform" element={guard(PLATFORM, <OrganizationsPage />)} />
            <Route path="platform/requests" element={guard(PLATFORM, <RequestsPage />)} />
            <Route path="*" element={<HomeRedirect />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AuthProvider>
  );
}
