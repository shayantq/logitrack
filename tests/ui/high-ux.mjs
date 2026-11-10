// سناریوهای مرزی اصلاحات High. فقط روی استک آزمایشی اجرا شود.
// node high-ux.mjs http://localhost:8003 <evidence-directory>
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright";

const BASE = process.argv[2];
assert(BASE && /^http:\/\/(localhost|127\.0\.0\.1):\d+$/.test(BASE), "Use a local isolated test stack");
const evidence = process.argv[3] || join(tmpdir(), "pasineh-high-ux");
mkdirSync(evidence, { recursive: true });
const auth = await fetch(`${BASE}/auth/token`, { method: "POST", body: new URLSearchParams({ username: "qazvin_admin", password: "admin123" }) });
assert.equal(auth.status, 200);
const token = (await auth.json()).access_token;
const browser = await chromium.launch();
let passed = 0;
const ok = label => { passed++; console.log(`OK ${label}`); };
const errors = [];
let debugPage;
async function context(options = {}) {
  const ctx = await browser.newContext({ locale: "fa-IR", timezoneId: "Asia/Tehran", viewport: { width: 1440, height: 1000 }, ...options });
  await ctx.addInitScript(t => { localStorage.setItem("access_token", t); localStorage.setItem("tours-off", "1"); }, token);
  const page = await ctx.newPage();
  debugPage = page;
  page.on("pageerror", e => errors.push(e.message));
  return { ctx, page };
}
const waitTable = page => page.waitForFunction(() => document.querySelector("[data-testid=orders-table] tbody tr") && !document.querySelector("[data-testid=orders-count]")?.textContent?.includes("در حال"));
async function choose(page, selector, value) {
  const trigger = page.locator(selector);
  await trigger.click();
  await page.locator(`[role=option][data-value="${value}"]`).click();
}

try {
  // کد lazy عمداً نگه داشته می‌شود: پوسته باید در DOM و روی صفحه بماند.
  const { ctx, page } = await context();
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  await page.route("**/assets/OrdersPage-*.js", async route => { await gate; await route.continue(); });
  await page.goto(`${BASE}/app`);
  await page.waitForSelector("[data-testid=business-home]");
  assert.equal(await page.locator("[data-testid=overview-toggle]").getAttribute("aria-expanded"), "false");
  assert.equal(await page.locator("[data-testid=biz-late]").count(), 0);
  ok("Dashboard removes duplicate summaries and starts with overview collapsed");
  await page.locator("[data-testid=app-nav]").getByText("سفارش‌ها", { exact: true }).click();
  await page.waitForSelector("[data-testid=page-loading]");
  assert(await page.locator("[data-testid=app-nav]").isVisible());
  assert(await page.locator("[data-testid=org-name]").isVisible());
  await page.screenshot({ animations: "disabled", path: join(evidence, "shell-loading.png") });
  release();
  await waitTable(page);
  assert.equal(await page.evaluate(() => document.activeElement?.tagName), "H1");
  assert((await page.title()).includes("سفارش‌ها"));
  ok("Lazy route keeps shell, shows skeleton, and focuses the new heading");

  // Select قابل جست‌وجو: فوکوس، active descendant، نتیجه خالی و Escape.
  const status = page.locator("[data-testid=search-status]");
  await status.focus(); await page.keyboard.press("ArrowDown");
  const combo = page.locator("[data-testid=search-status-list] input[role=combobox]");
  await combo.waitFor();
  const activeId = await combo.getAttribute("aria-activedescendant");
  assert(activeId && await page.locator(`[id="${activeId}"][role=option]`).count() === 1);
  await combo.fill("گزینه ناموجود ۱۲۳");
  await page.waitForFunction(() => !document.querySelector("[data-testid=search-status-list] input")?.getAttribute("aria-activedescendant"));
  await page.keyboard.press("Enter");
  assert.equal(await status.getAttribute("data-value"), "");
  await page.keyboard.press("Escape");
  assert.equal(await status.evaluate(el => document.activeElement === el), true);
  ok("Searchable Select has valid active descendant, safe empty search, and restored focus");

  await page.fill("[data-testid=search-q]", "تهران");
  await choose(page, "[data-testid=search-status]", "pending");
  assert(!page.url().includes("order_status="));
  await page.waitForSelector("[data-testid=filters-pending]");
  await page.click("[data-testid=search-submit]");
  await page.waitForURL(/order_status=pending/);
  assert(page.url().includes("q="));
  await page.goBack();
  assert(!page.url().includes("order_status="));
  await waitTable(page);
  ok("Text and Select stay draft together; Apply and browser Back preserve filter state");
  const firstCode = page.locator("[data-testid=orders-table] tbody tr").first().getByRole("button");
  await firstCode.focus(); await page.keyboard.press("Enter");
  await page.waitForSelector("[data-testid=order-detail]"); await page.keyboard.press("Escape");
  await page.waitForSelector("[data-testid=order-detail]", { state: "detached" });
  assert.equal(await firstCode.evaluate(el => document.activeElement === el), true);
  ok("Order detail opens with Enter and returns focus to the tracking-code button");

  // خطای بومی و خطای 422 باید ماندگار، متصل به فیلد و قابل فوکوس باشند.
  await page.click("[data-testid=new-order]");
  await page.click("button[form=order-form]");
  await page.waitForSelector("[data-testid=form-errors]:not([hidden])");
  assert.equal(await page.locator("[data-testid=customer-name]").getAttribute("aria-invalid"), "true");
  const errorId = await page.locator("[data-testid=customer-name]").getAttribute("aria-describedby");
  assert(errorId && (await page.locator(`[id="${errorId}"]`).textContent()).includes("پر کنید"));
  await page.locator("[data-testid=form-errors]").getByRole("button", { name: /نام مشتری/ }).click();
  assert.equal(await page.locator("[data-testid=customer-name]").evaluate(el => el === document.activeElement), true);
  await page.fill("[data-testid=customer-name]", "پیش‌نویس آزمایشی");
  assert.equal(await page.locator("#order-form").getAttribute("data-dirty"), "true");
  assert.equal(await page.inputValue("[data-testid=customer-name]"), "پیش‌نویس آزمایشی");
  assert.equal(await page.locator("[data-testid=customer-name]").getAttribute("aria-invalid"), null);
  await page.keyboard.press("Escape");
  await page.waitForSelector("[data-testid=confirm-dialog]");
  await page.getByRole("button", { name: "ادامه ویرایش", exact: true }).click();
  assert.equal(await page.inputValue("[data-testid=customer-name]"), "پیش‌نویس آزمایشی");
  ok("Native validation stays visible and linked; dismissing dirty form asks and preserves draft");

  const product = await page.locator("[data-native-for=order-item-product] option").nth(1).getAttribute("value");
  await choose(page, "[data-testid=order-item-product]", product);
  await page.fill("[data-testid=customer-mobile]", "09121112233");
  await choose(page, "[data-testid=order-province]", "قزوین");
  await page.waitForSelector('[data-native-for=order-city] option[value="قزوین"]', { state: "attached" });
  await choose(page, "[data-testid=order-city]", "قزوین");
  await page.fill("[data-testid=order-address]", "نشانی آزمایشی، پلاک ۱۲");
  await page.route("**/orders/", async route => route.request().method() === "POST"
    ? route.fulfill({ status: 422, json: { detail: [{ loc: ["body", "customer", "mobile"], msg: "موبایل مشتری: شماره معتبر نیست." }] } }) : route.continue());
  await page.click("button[form=order-form]");
  await page.waitForSelector('[data-testid=customer-mobile][aria-invalid="true"]');
  assert((await page.locator("[data-testid=form-errors]").textContent()).includes("شماره معتبر نیست"));
  await page.screenshot({ animations: "disabled", path: join(evidence, "form-validation.png") });
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "دور انداختن تغییرات", exact: true }).click();
  await page.waitForSelector("#order-form", { state: "detached" });
  assert.equal(await page.locator("[data-testid=new-order]").evaluate(el => el === document.activeElement), true);
  ok("Server field errors stay inline and summarized; confirmed discard restores trigger focus");
  const ids = await page.locator("[id]").evaluateAll(nodes => nodes.map(node => node.id));
  assert.equal(new Set(ids).size, ids.length, "Duplicate DOM ids");
  await page.goto(`${BASE}/app`);
  await page.locator("main").getByRole("link", { name: "ثبت سفارش", exact: true }).click();
  await page.waitForSelector("#order-form");
  await page.fill("[data-testid=customer-name]", "پیش‌نویس هنگام بازگشت");
  await page.goBack(); await page.waitForURL(/\/app$/);
  await page.goForward(); await page.waitForSelector("[data-testid=order-draft-restored]");
  assert.equal(await page.inputValue("[data-testid=customer-name]"), "پیش‌نویس هنگام بازگشت");
  await page.keyboard.press("Escape"); await page.getByRole("button", { name: "دور انداختن تغییرات", exact: true }).click();
  await page.waitForSelector("#order-form", { state: "detached" });
  ok("SPA Back/Forward recovers unsaved form from memory without browser storage");

  // ۴۵۱ ردیف شبیه‌سازی می‌شوند تا مرزهای ۲۰۰ و ۳۰۰ واقعاً بررسی شوند.
  const sample = (await (await fetch(`${BASE}/orders/?limit=1`, { headers: { Authorization: `Bearer ${token}` } })).json())[0];
  let failRefresh = 0, delayNext = false, unlock;
  const calls = [];
  await page.route("**/orders/page?*", async route => {
    const url = new URL(route.request().url()); calls.push(url.searchParams);
    if (delayNext) { delayNext = false; await new Promise(resolve => { unlock = resolve; }); }
    if (failRefresh) return route.fulfill({ status: failRefresh, json: { detail: failRefresh === 403 ? "مجوز آزمایشی لغو شد" : "قطع آزمایشی سفارش‌ها" } });
    const skip = Number(url.searchParams.get("skip") || 0), limit = Number(url.searchParams.get("limit") || 50);
    const items = Array.from({ length: Math.max(0, Math.min(limit, 451 - skip)) }, (_, i) => ({ ...sample, id: 10000 + skip + i, tracking_code: `LT-UX${String(skip + i).padStart(6, "0")}` }));
    return route.fulfill({ json: { items, total: 451, skip, limit } });
  });
  await page.goto(`${BASE}/app/orders?page_size=200`); await waitTable(page);
  assert.equal(await page.locator("[data-testid=order-select]").count(), 200);
  await page.locator("[data-testid=order-select]").first().check();
  assert.equal(await page.locator("[data-testid=orders-select-all]").evaluate(el => el.indeterminate), true);
  await page.locator("[data-testid=orders-select-all]").check();
  assert.equal(await page.locator("[data-testid=order-select]:checked").count(), 200);
  delayNext = true;
  await page.getByRole("button", { name: "صفحه بعد", exact: true }).click();
  await page.waitForURL(/page=2/);
  await page.waitForFunction(() => document.querySelector("[data-testid=orders-select-all]")?.disabled);
  assert.equal(await page.locator("[data-testid=orders-bulk-bar]").count(), 0);
  unlock(); await waitTable(page);
  assert((await page.locator("[data-testid=orders-table]").textContent()).includes("LT-UX000200"));
  await page.getByRole("button", { name: "صفحه بعد", exact: true }).click(); await waitTable(page);
  assert.equal(await page.locator("[data-testid=order-select]").count(), 51);
  assert((await page.locator("[data-testid=orders-table]").textContent()).includes("LT-UX000450"));
  ok("451 orders paginate beyond 300; 200-row selection is exact, partial, and resets safely in flight");
  failRefresh = 503;
  await page.getByText("قطع آزمایشی سفارش‌ها", { exact: true }).waitFor({ timeout: 30000 });
  assert.equal(await page.locator("[data-testid=order-select]").count(), 51);
  assert((await page.locator("main").textContent()).includes("اطلاعات قبلی نمایش داده می‌شود"));
  assert(await page.locator("[data-testid=orders-select-all]").isDisabled());
  ok("Background outage retains previous rows, marks them stale, and blocks bulk actions");
  failRefresh = 403;
  await page.waitForSelector("[data-testid=permission-denied]", { timeout: 30000 });
  assert.equal(await page.locator("[data-testid=orders-table]").count(), 0);
  ok("Revoked permissions hide cached rows instead of treating forbidden data as stale");
  await ctx.close();

  // خطا در هر بخش داشبورد باید از بارگذاری و صفر نتیجه متمایز باشد.
  const failure = await context();
  await failure.page.route("**/reports/stats", route => route.fulfill({ status: 503, json: { detail: "خطای آزمایشی آمار" } }));
  await failure.page.route("**/orders/?*", route => route.fulfill({ status: 503, json: { detail: "خطای آزمایشی سفارش‌های اخیر" } }));
  await failure.page.goto(`${BASE}/app`); await failure.page.click("[data-testid=overview-toggle]");
  await failure.page.getByText("خطای آزمایشی آمار", { exact: true }).waitFor({ timeout: 20000 });
  await failure.page.getByText("خطای آزمایشی سفارش‌های اخیر", { exact: true }).waitFor({ timeout: 20000 });
  assert.equal(await failure.page.locator("main .animate-\\[shimmer_1\\.4s_infinite\\]").count(), 0);
  assert(await failure.page.locator("[data-testid=business-home]").isVisible());
  assert.equal(await failure.page.getByText("هنوز سفارشی ثبت نشده", { exact: true }).count(), 0);
  await failure.page.screenshot({ animations: "disabled", path: join(evidence, "dashboard-outage.png"), fullPage: true });
  ok("Independent dashboard failures end skeletons without replacing healthy sections or claiming empty data");
  await failure.ctx.close();

  for (const theme of ["light", "dark"]) {
    const mobile = await context({ viewport: { width: 390, height: 844 } });
    await mobile.ctx.addInitScript(t => localStorage.setItem("theme", t), theme);
    await mobile.page.goto(`${BASE}/app`); await mobile.page.waitForSelector("[data-testid=business-home]");
    assert(await mobile.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await mobile.page.screenshot({ animations: "disabled", path: join(evidence, `dashboard-mobile-${theme}.png`), fullPage: true });
    await mobile.page.goto(`${BASE}/app/orders?new=1`); await mobile.page.waitForSelector("#order-form");
    assert(!mobile.page.url().includes("new=1"));
    assert(await mobile.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await mobile.page.screenshot({ animations: "disabled", path: join(evidence, `form-mobile-${theme}.png`) });
    await mobile.ctx.close();
  }
  ok("Quick-create link works; dashboard and form fit mobile in light and dark themes");
  assert.deepEqual(errors, [], "Browser runtime errors");
  console.log(`PASS ${passed} High UX scenarios; evidence: ${evidence}`);
} catch (error) {
  if (debugPage && !debugPage.isClosed()) {
    await debugPage.screenshot({ animations: "disabled", path: join(evidence, "failure.png"), fullPage: true });
    console.error("Dialogs:", await debugPage.locator("[role=dialog]").allTextContents());
  }
  throw error;
} finally { await browser.close(); }
