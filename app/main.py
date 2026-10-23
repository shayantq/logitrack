import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.database import db_dependency
from app.core.request_context import RequestContextMiddleware
from app.core.tenancy import TenantIsolationError
from app.services.stock_ledger import LedgerViolationError

from app.routers import (
    auth, inventory, orders, users, vehicles, reports, warehouses, notifications, platform,
    organization, organization_requests, drivers, dispatch, driver_portal, performance, tracking, routes, tickets, stocktakes, catalog, replenishment,
    partners, wms,
)

# ------------------------------------------------------------------------------
# رابط کاربری: خروجی build اپ React (داخل داکر: /code/frontend/dist)
# ------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", BASE_DIR.parent / "frontend" / "dist"))
SPA_INDEX = FRONTEND_DIST / "index.html"

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ⚠️ توجه: دیگر از Base.metadata.create_all() استفاده نمی‌شود.
    # ساخت و به‌روزرسانی جدول‌ها اکنون کاملاً به عهده‌ی Alembic است:
    #   docker compose exec web alembic upgrade head
    yield


app = FastAPI(
    title="🏢 Pasineh API",
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# IP و مرورگر هر درخواست برای گزارش فعالیت (app/services/audit_service.py)
app.add_middleware(RequestContextMiddleware)

# فرانت‌اند از همین سرور سرو می‌شود (same-origin) و به CORS نیازی ندارد.
# اگر کلاینت دیگری روی دامنه جدا دارید، آدرس‌هایش را با کاما در CORS_ORIGINS بنویسید.
# توکن در هدر Authorization ارسال می‌شود، نه کوکی؛ پس allow_credentials لازم نیست.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ------------------------------------------------------------------------------
# اپ React کل رابط کاربری است: صفحه اصلی (/)، فرم درخواست (/request) و پنل‌ها (/app/...).
# همه این مسیرها همان index.html را می‌گیرند و مسیریابی سمت مرورگر انجام می‌شود.
# ------------------------------------------------------------------------------

# مرورگر index.html را کش نکند تا بعد از هر به‌روزرسانی، نسخه جدید بدون Ctrl+F5 دیده شود
NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}

if (FRONTEND_DIST / "assets").exists():
    # نام فایل‌ها هش دارند؛ پس کش طولانی برایشان امن است
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")


@app.get("/", include_in_schema=False)
@app.get("/request", include_in_schema=False)
@app.get("/join/{code}", include_in_schema=False)
@app.get("/rate/{code}", include_in_schema=False)
@app.get("/track", include_in_schema=False)
@app.get("/track/{code}", include_in_schema=False)
@app.get("/about", include_in_schema=False)
@app.get("/faq", include_in_schema=False)
@app.get("/terms", include_in_schema=False)
@app.get("/privacy", include_in_schema=False)
@app.get("/pricing", include_in_schema=False)
@app.get("/support/{token}", include_in_schema=False)
@app.get("/app", include_in_schema=False)
@app.get("/app/{path:path}", include_in_schema=False)
def serve_react_app(path: str = "", code: str = ""):
    if SPA_INDEX.exists():
        return FileResponse(str(SPA_INDEX), headers=NO_CACHE)
    return JSONResponse(status_code=404, content={"error": "اپ React ساخته نشده است (cd frontend && npm run build)."})


PUBLIC_FILES = {
    "favicon.svg": "image/svg+xml", "og.png": "image/png", "manifest.webmanifest": "application/manifest+json",
    "apple-touch-icon.png": "image/png", "icon-192.png": "image/png", "icon-512.png": "image/png",
    "icon-maskable-512.png": "image/png",
}


@app.get("/favicon.svg", include_in_schema=False)
@app.get("/og.png", include_in_schema=False)
@app.get("/manifest.webmanifest", include_in_schema=False)
@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/icon-192.png", include_in_schema=False)
@app.get("/icon-512.png", include_in_schema=False)
@app.get("/icon-maskable-512.png", include_in_schema=False)
def serve_public_file(request: Request):
    """فایل‌های ثابت ریشه سایت: آیکن‌ها، manifest نصب روی گوشی (PWA) و تصویر پیش‌نمایش لینک."""
    name = request.url.path.lstrip("/")
    path = FRONTEND_DIST / name
    if path.exists():
        return FileResponse(str(path), media_type=PUBLIC_FILES[name], headers={"Cache-Control": "public, max-age=86400"})
    return JSONResponse(status_code=404, content={"error": "یافت نشد."})


# آدرس‌های قدیمی → اپ جدید (بوکمارک‌ها و لینک‌های قبلی کار می‌کنند)
OLD_PAGE_REDIRECTS = {
    "/login": "/app/login", "/dashboard": "/app/", "/manager": "/app/inventory",
    "/driver": "/app/driver", "/platform": "/app/platform",
}
for _old, _new in OLD_PAGE_REDIRECTS.items():
    app.add_api_route(_old, (lambda target=_new: RedirectResponse(target, status_code=307)),
                      methods=["GET"], include_in_schema=False)


@app.get("/legacy/{page}", include_in_schema=False)
def legacy_redirect(page: str):
    """پنل‌های HTML قدیمی حذف شده‌اند؛ لینک‌های ذخیره‌شده به معادل جدیدشان می‌روند."""
    return RedirectResponse(OLD_PAGE_REDIRECTS.get(f"/{page}", "/app/"), status_code=307)


@app.get("/health", include_in_schema=False)
def health_check(db: db_dependency):
    """برای healthcheck داکر و مانیتورینگ: سرور بالاست و به دیتابیس وصل است."""
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


# اتصال روترهای API
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(inventory.router)
app.include_router(orders.router)
app.include_router(vehicles.router)
app.include_router(reports.router)
app.include_router(warehouses.router)
app.include_router(notifications.router)
app.include_router(platform.router)
app.include_router(organization.router)
app.include_router(organization_requests.router)
app.include_router(drivers.public_router)
app.include_router(drivers.onboarding_router)
app.include_router(drivers.admin_router)
app.include_router(dispatch.router)
app.include_router(driver_portal.driver_router)
app.include_router(driver_portal.admin_router)
app.include_router(performance.router)
app.include_router(tracking.router)
app.include_router(routes.router)
app.include_router(tickets.router)
app.include_router(tickets.platform_router)
app.include_router(tickets.public_router)
app.include_router(stocktakes.router)
app.include_router(catalog.router)
app.include_router(replenishment.router)
app.include_router(partners.router)
app.include_router(wms.router)


# محافظ‌های لایه داده آخرین سدند (سرویس‌ها پیش از آن خطای خوانا می‌دهند)؛ اگر کدی از آن‌ها رد شود،
# درخواست با پیام روشن رد می‌شود و هیچ تغییری ذخیره نمی‌شود.
@app.exception_handler(TenantIsolationError)
async def tenant_isolation_handler(request: Request, exc: TenantIsolationError):
    return JSONResponse(status_code=403, content={"detail": "دسترسی به داده سازمان دیگر مجاز نیست."})


@app.exception_handler(LedgerViolationError)
async def ledger_violation_handler(request: Request, exc: LedgerViolationError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})
