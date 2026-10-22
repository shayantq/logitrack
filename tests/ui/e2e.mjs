// تست سرتاسری اپ React با مرورگر واقعی (Chromium + Playwright).
// هر نقش وارد می‌شود، کارهای اصلی‌اش را مثل یک کاربر واقعی انجام می‌دهد و هر خطای
// جاوااسکریپت یا خطای کنسول گزارش می‌شود.
//   استفاده:  node e2e.mjs http://localhost:8002   (داده می‌نویسد — فقط روی استک تست)
import { appendFileSync } from "node:fs";
import { chromium } from "playwright";

const BASE = process.argv[2] || "http://localhost:8001";
const results = [];
// در GitHub Actions هر بررسی ناموفق یک annotation در صفحه اجرا می‌شود و فهرستشان در Job Summary می‌آید
const CI = process.env.GITHUB_ACTIONS === "true";
const annotate = text => text.replace(/%/g, "%25").replace(/\r/g, "%0D").replace(/\n/g, "%0A");
function check(scope, label, ok, detail = "") {
  results.push({ ok, scope, label, detail });
  console.log(`${ok ? "OK  " : "FAIL"} [${scope}] ${label}${detail ? " — " + detail : ""}`);
  if (!ok && CI) console.log(`::error title=E2E [${scope}]::${annotate(label + (detail ? " — " + detail : ""))}`);
}

// WebGL نرم‌افزاری برای شهر سه‌بعدی صفحه اصلی در حالت بدون‌سر
// دوربین/میکروفون ساختگی برای تست ضبط ویدیوی احراز هویت
const browser = await chromium.launch({ args: [
  "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
  "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
] });

async function session(scope, username, password, scenario, contextOptions = {}) {
  const { tours = false, ...options } = contextOptions;
  const context = await browser.newContext({ locale: "fa-IR", ...options });
  // راهنمای تعاملی (فقط بار اول کاربر) جلوی کلیک‌های جریان‌های دیگر را می‌گیرد؛ فقط نشست «tour» آن را می‌بیند
  if (!tours) await context.addInitScript(() => { try { localStorage.setItem("tours-off", "1"); } catch { /* */ } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(`pageerror: ${e.message}`));
  // پاسخ‌های 4xx سناریوهای خطای عمدی (رمز اشتباه و ...) را مرورگر به‌صورت «Failed to load resource» لاگ می‌کند؛
  // درستی آن جریان‌ها با assertion خودشان بررسی می‌شود
  page.on("console", m => { if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) errors.push(`console: ${m.text()}`); });
  try {
    if (username) {
      await page.goto(`${BASE}/app/login`);
      await page.fill("#username", username);
      await page.fill("#password", password);
      await page.click("button[type=submit]");
      await page.waitForSelector("[data-testid=org-name]", { timeout: 15000 });
    }
    await scenario(page);
  } catch (e) {
    // برای عیب‌یابی: انتظار ناموفق + پیام‌های روی صفحه + اسکرین‌شات
    const toasts = await page.locator("[data-testid=toast]").allTextContents().catch(() => []);
    await page.screenshot({ path: `e2e-failure-${scope}.png`, fullPage: true }).catch(() => {});
    errors.push(`scenario: ${e.message.split("\n").slice(0, 3).join(" ")} — toasts: ${toasts.join(" / ")}`);
  }
  check(scope, "no JS/console errors", errors.length === 0, errors.slice(0, 4).join(" | "));
  await context.close();
}

/**
 * انتخاب از فهرست سفارشی (Select در ui/select.tsx): کلیک روی دکمه و سپس گزینه.
 * target: سلکتور یا Locator دکمه؛ value: مقدار گزینه یا { index }.
 */
async function choose(page, target, value) {
  const trigger = typeof target === "string" ? page.locator(target) : target;
  await trigger.click();
  const options = page.locator("[data-popover] [data-select-list] [role=option]");
  const option = typeof value === "object" ? options.nth(value.index) : page.locator(`[data-popover] [data-select-list] [role=option][data-value="${value}"]`);
  await option.click();
  await page.locator("[data-popover] [data-select-list]").waitFor({ state: "detached" });
}
const latinize = text => (text ?? "").replace(/[۰-۹]/g, d => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)));
/** انتخاب ساعت از ساعت‌شمار سفارشی (TimeField) */
async function pickTime(page, testId, hour, minute) {
  await page.click(`[data-testid=${testId}]`);
  await page.click(`[data-testid=${testId}-picker] [data-hour='${hour}']`);
  await page.click(`[data-testid=${testId}-picker] [data-minute='${minute}']`);
}
/** انتخاب شهر از فهرست شهرهای استان (بعد از بارگذاری گزینه‌ها) */
async function pickCity(page, testId, city) {
  await page.waitForSelector(`[data-native-for=${testId}] option[value="${city}"]`, { state: "attached" });
  await choose(page, `[data-testid=${testId}]`, city);
}
const rowCount = (page, testId) => page.locator(`[data-testid=${testId}] tbody tr`).count();
const toast = page => page.locator("[data-testid=toast]").first().textContent({ timeout: 10000 });

// ---------------- ادمین سازمان ----------------
await session("org_admin", "qazvin_admin", "admin123", async page => {
  check("org_admin", "lands on dashboard", /\/app\/?$/.test(page.url()), page.url());
  await page.waitForSelector("text=کالاهای رو‌به‌اتمام");

  await page.click("[data-testid=app-nav] >> text=سفارش‌ها");
  await page.waitForSelector("[data-testid=orders-table] tbody tr");
  check("org_admin", "orders listed", (await rowCount(page, "orders-table")) > 0);

  // ثبت سفارش دوقلمی بدون خودرو
  await page.click("[data-testid=new-order]");
  const productSelects = page.locator("[data-testid=order-item-product]");
  // دو کالا که موجودی کافی دارند (عدد موجودی در متن گزینه با ارقام فارسی است)
  const stocked = await page.locator("[data-native-for=order-item-product]").first().evaluate(sel => [...sel.options]
    .map(o => ({ value: o.value, stock: Number((/موجودی(?: کل)?: ([۰-۹٬,]+)/.exec(o.text)?.[1] ?? "0").replace(/[٬,]/g, "").replace(/[۰-۹]/g, d => "۰۱۲۳۴۵۶۷۸۹".indexOf(d))) }))
    .filter(o => o.value && o.stock >= 5).map(o => o.value));
  await choose(page, productSelects.first(), stocked[0]);
  await page.waitForSelector("[data-testid=warehouse-stock] [data-warehouse]");
  check("org_admin", "product row shows stock per warehouse", (await page.locator("[data-testid=warehouse-stock] [data-warehouse]").count()) >= 1);
  await page.click("text=افزودن کالا");
  await choose(page, productSelects.nth(1), stocked[1]);
  await page.locator("[data-testid=order-item-qty]").nth(1).fill("1"); // تعداد کالای دوم
  await page.fill("[data-testid=customer-name]", "مشتری تست مرورگر");
  await page.fill("[data-testid=customer-mobile]", "۰۹۱۲۷۷۷۸۸۹۹");
  await choose(page, "[data-testid=order-province]", "قزوین");
  await pickCity(page, "order-city", "قزوین");
  await page.fill("[data-testid=order-address]", "خیابان پیروزی، پلاک ۹");
  // تاریخ پیش‌فرض «فردا» است؛ رانندگان نمونه جمعه شیفت ندارند، پس اگر فردا جمعه است روز کاری بعد انتخاب می‌شود
  const defaultDay = await page.getAttribute("[data-testid=order-date]", "data-value");
  if (new Date(`${defaultDay}T12:00:00Z`).getUTCDay() === 5) {
    const workday = new Date(Date.parse(`${defaultDay}T12:00:00Z`) + 86400000).toISOString().slice(0, 10);
    await page.click("[data-testid=order-date]");
    if (!(await page.locator(`[data-testid=order-date-calendar] [data-day="${workday}"]`).count())) await page.click("[data-testid=order-date-calendar] [aria-label='ماه بعد']");
    await page.click(`[data-testid=order-date-calendar] [data-day="${workday}"]`);
  }
  await page.click("[data-testid=assign-mode-later]");
  await page.click("button[form=order-form]");
  const created = await toast(page);
  check("org_admin", "multi-item order created", /LT-/.test(created), created);
  const code = /LT-[A-Z0-9]{8}/.exec(created)?.[0];

  // جزئیات + تخصیص + تغییر وضعیت
  await page.locator(`[data-testid=orders-table] tr:has-text("${code}")`).click();
  await page.waitForSelector("[data-testid=order-detail]");
  await page.click("text=تخصیص خودکار خودرو");
  await page.waitForSelector("[data-testid=order-detail] >> text=تخصیص‌یافته");
  await choose(page, "[data-testid=next-status]", "canceled");
  await page.click("[data-testid=apply-status]");
  await page.waitForSelector("[data-testid=order-history] >> text=لغوشده");
  check("org_admin", "history shows pending→assigned→canceled", (await page.locator("[data-testid=order-history] li").count()) === 3);
  await page.keyboard.press("Escape");

  // انبار: ثبت ورود کالا + دفتر گردش
  await page.click("[data-testid=app-nav] >> text=انبار و کالاها");
  await page.waitForSelector("[data-testid=products-table] tbody tr");
  await page.click("[data-testid=new-movement]");
  await choose(page, "[data-testid=movement-product]", { index: 1 });
  await choose(page, "[data-testid=movement-warehouse]", { index: 1 });
  await page.fill("[data-testid=movement-qty]", "7");
  await page.click("button[form=movement-form]");
  await page.waitForSelector("[data-testid=toast]:has-text('گردش کالا ثبت شد')", { timeout: 10000 });
  check("org_admin", "stock receipt recorded", true);
  await page.click("[data-testid=app-nav] >> text=دفتر گردش کالا");
  await page.waitForSelector("[data-testid=ledger-table] tbody tr");
  check("org_admin", "ledger shows return of canceled order", (await page.locator("[data-testid=ledger-table] >> text=برگشت از سفارش").count()) > 0);

  for (const [link, testId] of [["ناوگان", "vehicles-table"], ["کاربران و رانندگان", "users-table"]]) {
    await page.click(`[data-testid=app-nav] >> text=${link}`);
    await page.waitForSelector(`[data-testid=${testId}] tbody tr`);
    check("org_admin", `${link} page`, (await rowCount(page, testId)) > 0);
  }
  await page.click("[data-testid=app-nav] >> text=پروفایل سازمان");
  await page.waitForSelector("[data-testid=org-profile-form]");
  await page.waitForFunction(() => document.querySelector("[data-testid=org-profile-form] input")?.value.length > 0);
  check("org_admin", "organization profile loaded", true);

  // تغییر تم از منوی بالا ← کل پنل تاریک می‌شود و انتخاب ذخیره می‌ماند
  await page.click("[data-testid=theme-toggle]");   // یک کلیک، بدون منو
  check("org_admin", "theme toggles with one click (no menu)", (await page.locator("[role=menu]").count()) === 0);
  await page.waitForFunction(() => document.documentElement.dataset.theme === "dark");   // پس از انیمیشن دایره‌ای
  check("org_admin", "dark theme applied", (await page.evaluate(() => document.documentElement.dataset.theme)) === "dark");
  await page.reload();
  await page.waitForSelector("[data-testid=org-name]");
  check("org_admin", "dark theme persists after reload", (await page.evaluate(() => document.documentElement.dataset.theme)) === "dark");
  await page.screenshot({ path: "e2e-dark-organization.png" });

  // خروج
  await page.click("[data-testid=user-menu]");
  await page.click("[data-testid=logout]");
  await page.waitForURL(/\/app\/login$/);
  check("org_admin", "logout returns to login", true);
});

// ---------------- مدیر انبار ----------------
await session("manager", "manager_tehran", "manager123", async page => {
  check("manager", "lands on inventory", page.url().endsWith("/app/inventory"), page.url());
  await page.waitForSelector("[data-testid=products-table] tbody tr");
  const menu = await page.locator("[data-testid=app-nav]").first().textContent();
  check("manager", "no fleet/users menu", !menu.includes("ناوگان") && !menu.includes("کاربران"));
  await page.goto(`${BASE}/app/users`);
  await page.waitForURL(/\/app\/inventory$/);
  check("manager", "forbidden page redirects home", true);
  await page.click("[data-testid=app-nav] >> text=سفارش‌ها");
  await page.waitForSelector("[data-testid=orders-table] tbody tr");
  check("manager", "orders page available", (await rowCount(page, "orders-table")) > 0);
});

// ---------------- راننده ----------------
await session("driver", "driver_ali", "driver123", async page => {
  check("driver", "lands on driver page", page.url().endsWith("/app/driver"), page.url());
  await page.waitForSelector("[data-testid=driver-vehicle] >> text=پلاک");
  check("driver", "vehicle card loaded (not stuck loading)", (await page.locator("[data-testid=driver-vehicle] [data-testid=loading]").count()) === 0);
});

// ---------------- پلتفرم ----------------
await session("platform", "superadmin", "superadmin123", async page => {
  check("platform", "lands on organizations", page.url().endsWith("/app/platform"), page.url());
  await page.waitForSelector("[data-testid=orgs-table] tbody tr");
  check("platform", "organizations listed", (await rowCount(page, "orgs-table")) >= 2);
  await page.click("[data-testid=orgs-table] >> text=پروفایل >> nth=0");
  await page.waitForSelector("[role=dialog] [data-testid=data-list]");
  check("platform", "organization profile modal", true);
  await page.keyboard.press("Escape");
  await page.click("[data-testid=app-nav] >> text=درخواست‌های ثبت سازمان");
  await page.waitForSelector("[data-testid=requests-table] tbody tr");
  await page.locator("[data-testid=requests-table] tbody tr").first().click();
  check("platform", "request review form visible", (await page.locator("#approve-form").count()) === 1);
});

// ---------------- مرحله ۶: ثبت‌نام راننده با لینک دعوت ← مدارک ← تأیید ادمین ----------------
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
const MP4 = Buffer.concat([Buffer.from([0, 0, 0, 0x18]), Buffer.from("ftypisom"), Buffer.alloc(64)]);
const runId = String(Date.now()).slice(-6);
/** MP4 حداقلی با مدت مشخص (جعبه mvhd در انتهای فایل، مثل ضبط گوشی) */
function mp4OfSeconds(seconds) {
  const body = Buffer.alloc(100);
  body.writeUInt32BE(1000, 12);
  body.writeUInt32BE(seconds * 1000, 16);
  const box = (type, payload) => { const h = Buffer.alloc(8); h.writeUInt32BE(8 + payload.length); h.write(type, 4); return Buffer.concat([h, payload]); };
  return Buffer.concat([box("ftyp", Buffer.from("isom\0\0\0\0")), box("mdat", Buffer.alloc(32)), box("moov", box("mvhd", body))]);
}
const kycUser = `kyc_${runId}`;
const kycPlate = { a: runId.slice(0, 2), b: runId.slice(2, 5), region: runId.slice(4, 6) };
function nationalCode() {
  const base = String(100000000 + Math.floor(Math.random() * 800000000));
  const r = [...base].reduce((sum, d, i) => sum + Number(d) * (10 - i), 0) % 11;
  return base + String(r < 2 ? r : 11 - r);
}
const upload = (page, kind, isVideo = false) => page.setInputFiles(`[data-testid=doc-input-${kind}]`,
  { name: isVideo ? "v.mp4" : "d.png", mimeType: isVideo ? "video/mp4" : "image/png", buffer: isVideo ? MP4 : PNG })
  .then(() => page.waitForSelector(`[data-testid=doc-${kind}][data-uploaded=true]`, { timeout: 15000 }));

await session("kyc-driver", null, null, async page => {
  await page.goto(`${BASE}/join/QAZVIN26`);
  await page.waitForSelector("[data-testid=invite-org] >> text=فروشگاه نمونه قزوین");
  check("kyc-driver", "invite link shows organization", true);
  await page.fill("[data-testid=join-name]", "راننده آزمون");
  await page.fill("[data-testid=join-mobile]", "۰۹۱۲۵۵۵۶۶۷۷");
  await page.fill("[data-testid=join-username]", kycUser);
  await page.fill("[data-testid=join-password]", "driver123");
  await page.click("[data-testid=join-submit]");
  await page.waitForURL(/\/app\/onboarding$/);
  await page.waitForSelector("[data-testid=onboarding]");
  check("kyc-driver", "signup lands on onboarding wizard", true);
  const nav = await page.locator("[data-testid=app-nav]").first().textContent();
  check("kyc-driver", "unapproved driver menu has only onboarding", nav.includes("تکمیل پرونده") && !nav.includes("خودرو و سفارش‌های امروز") && !nav.includes("پروفایل من"));
  await page.goto(`${BASE}/app/driver`);
  await page.waitForURL(/\/app\/onboarding$/);
  check("kyc-driver", "driver panel locked until approval", true);

  // ۱. وسیله
  await page.click("[data-testid=vehicle-kind] >> text=وانت / نیسان");
  await page.click("[data-testid=onboarding-next]");
  // ۲. هویت و مدارک
  await page.fill("[data-testid=ob-first-name]", "راننده");
  await page.fill("[data-testid=ob-last-name]", "آزمون");
  await page.fill("[data-testid=ob-national-code]", nationalCode());
  await choose(page, "[data-testid=ob-birth-date] [role=combobox][aria-label=روز]", "12");
  await choose(page, "[data-testid=ob-birth-date] [role=combobox][aria-label=ماه]", "5");
  await choose(page, "[data-testid=ob-birth-date] [role=combobox][aria-label=سال]", "1370");
  for (const kind of ["national_card", "selfie", "driving_license"]) await upload(page, kind);

  // ویدیوی طولانی و حجیم با پیام روشن رد می‌شوند
  await page.setInputFiles("[data-testid=doc-input-video]", { name: "long.mp4", mimeType: "video/mp4", buffer: mp4OfSeconds(90) });
  await page.waitForSelector("[data-testid=toast]:has-text('ثانیه')");
  check("kyc-driver", "90-second video rejected", (await page.locator("[data-testid=doc-video][data-uploaded=true]").count()) === 0);
  await page.setInputFiles("[data-testid=doc-input-video]", { name: "big.mp4", mimeType: "video/mp4", buffer: Buffer.concat([mp4OfSeconds(5), Buffer.alloc(31 * 1024 * 1024)]) });
  await page.waitForSelector("[data-testid=toast]:has-text('مگابایت')");
  check("kyc-driver", "31MB video rejected before upload", (await page.locator("[data-testid=doc-progress-video]").count()) === 0);

  // ضبط با دوربین ← پیش‌نمایش باید همان ویدیوی ضبط‌شده باشد، نه تصویر زنده دوربین
  await page.click("[data-testid=record-video]");
  // دوربین ساختگی مرورگر بدون‌سر زیر بار سیستم گاهی فایل خالی ضبط می‌کند؛ مثل کاربر واقعی «ضبط دوباره» (تا ۳ بار)
  let playback;
  for (let attempt = 1; attempt <= 3; attempt++) {
    if (attempt > 1) await page.click("[data-testid=recorder-retake]");
    // صبر تا دوربین ساختگی واقعاً تصویر بدهد
    await page.waitForFunction(() => { const v = document.querySelector("[data-testid=recorder-live]"); return v?.srcObject && v.readyState >= 2 && v.videoWidth > 0; }, null, { timeout: 20000 });
    await page.click("[data-testid=recorder-start]");
    // دکمه «توقف» با شروع ضبط جای «شروع» را می‌گیرد؛ کلیک مستقیم (بدون انتظار برای پایدار شدن انیمیشن پنجره)
    // تا زیر بار سیستم، ضبط تا سقف زمان ادامه پیدا نکند
    const stop = page.locator("[data-testid=recorder-stop]");
    await stop.waitFor({ state: "attached", timeout: 15000 });
    await page.waitForTimeout(3500);
    await stop.dispatchEvent("click").catch(() => {});
    await page.waitForSelector("[data-testid=recorder-playback]", { timeout: 60000 });
    playback = await page.evaluate(async () => {
      const v = document.querySelector("[data-testid=recorder-playback]");
      // سقف ۱۵ ثانیه: بدون آن، اگر loadeddata نرسد evaluate تا ابد منتظر می‌ماند و کل تست بی‌صدا گیر می‌کند
      await new Promise(r => { if (v.readyState >= 2) return r(); v.addEventListener("loadeddata", r, { once: true }); setTimeout(r, 15000); });
      return { live: !!document.querySelector("[data-testid=recorder-live]"), srcObject: !!v.srcObject, blob: v.src.startsWith("blob:"), ready: v.readyState };
    });
    if (playback.ready >= 2) break;
    console.log(`     (kyc-driver) empty recording on attempt ${attempt}, recording again`);
  }
  check("kyc-driver", "recorded video plays back (not live camera)", !playback.live && !playback.srcObject && playback.blob && playback.ready >= 2, JSON.stringify(playback));
  await page.click("[data-testid=recorder-use]");
  await page.waitForSelector("[data-testid=doc-video][data-uploaded=true]", { timeout: 20000 });
  check("kyc-driver", "recorded video uploaded", true);

  // ویدیوی آپلودشده قابل پخش است
  await page.click("[data-testid=doc-view-video]");
  const viewer = await page.evaluate(async () => {
    const v = document.querySelector("[data-testid=doc-viewer-video]");
    await new Promise(r => (v.readyState >= 2 ? r() : v.addEventListener("loadeddata", r, { once: true })));
    return v.readyState;
  });
  check("kyc-driver", "uploaded video can be played", viewer >= 2);
  await page.keyboard.press("Escape");
  check("kyc-driver", "identity documents uploaded", true);
  await page.click("[data-testid=onboarding-next]");
  // ۳. مشخصات وسیله
  await page.fill("[data-testid=ob-model]", "نیسان زامیاد");
  await page.fill("[data-testid=plate-a]", kycPlate.a);
  await page.fill("[data-testid=plate-b]", kycPlate.b);
  await page.fill("[data-testid=plate-region]", kycPlate.region);
  await page.fill("[data-testid=ob-max-weight]", "1200");
  const year = await page.locator("[data-testid=ob-inspection] [data-select-root]:has([aria-label=سال]) select option").nth(2).getAttribute("value");
  await choose(page, "[data-testid=ob-inspection] [role=combobox][aria-label=روز]", "1");
  await choose(page, "[data-testid=ob-inspection] [role=combobox][aria-label=ماه]", "1");
  await choose(page, "[data-testid=ob-inspection] [role=combobox][aria-label=سال]", year);
  await page.check("[data-testid=ob-intercity]");
  for (const kind of ["vehicle_photo", "vehicle_card", "technical_inspection"]) await upload(page, kind);
  await page.click("[data-testid=onboarding-next]");
  // ۴. سکونت
  await choose(page, "[data-testid=ob-province]", "قزوین");
  await pickCity(page, "ob-city", "قزوین");
  await page.fill("[data-testid=ob-address]", "قزوین، خیابان فردوسی، کوچه ۸، پلاک ۳");
  await page.click("[data-testid=onboarding-next]");
  // ۵. ارسال
  await page.waitForSelector("text=همه اطلاعات و مدارک کامل است");
  await page.screenshot({ path: "e2e-onboarding-review.png", fullPage: true });
  await page.click("[data-testid=onboarding-submit]");
  await page.waitForSelector("[data-testid=onboarding-waiting]");
  check("kyc-driver", "application submitted, waiting screen", true);
}, { viewport: { width: 420, height: 900 }, permissions: ["camera", "microphone"] });

await session("kyc-admin", "qazvin_admin", "admin123", async page => {
  await page.waitForSelector("[data-testid=pending-drivers-badge]");
  check("kyc-admin", "pending applications badge in menu", true);
  await page.click("[data-testid=app-nav] >> text=احراز هویت رانندگان");
  await page.locator("[data-testid=drivers-table] tbody tr", { hasText: "راننده آزمون" }).first().click();
  // مدارک یکی‌یکی بارگذاری می‌شوند؛ صبر تا همه ۶ تصویر و ویدیو حاضر و بارگذاری‌شده باشند
  await page.waitForFunction(() => {
    const imgs = [...document.querySelectorAll("[data-testid=review-documents] img")];
    return imgs.length === 6 && imgs.every(i => i.complete && i.naturalWidth > 0) && document.querySelector("[data-testid=review-video]");
  }, null, { timeout: 20000 });
  check("kyc-admin", "documents load for own org admin", (await page.locator("[data-testid=review-documents] img").count()) === 6);
  check("kyc-admin", "identity video shown", (await page.locator("[data-testid=review-video]").count()) === 1);
  const adminVideo = await page.evaluate(async () => {
    const v = document.querySelector("[data-testid=review-video]");
    await new Promise(r => (v.readyState >= 1 ? r() : v.addEventListener("loadedmetadata", r, { once: true })));
    return v.readyState;
  });
  check("kyc-admin", "admin can play the recorded video", adminVideo >= 1);
  await page.screenshot({ path: "e2e-driver-review.png" });
  await page.click("[data-testid=approve-driver]");
  await page.waitForSelector("[data-testid=toast]:has-text('راننده تأیید شد')");
  check("kyc-admin", "driver approved", true);
  await page.click("[data-testid=app-nav] >> text=ناوگان");
  await page.waitForSelector(`[data-testid=vehicles-table] >> text=نیسان زامیاد`);
  check("kyc-admin", "approved driver's vehicle added to fleet", true);
});

await session("kyc-driver-approved", kycUser, "driver123", async page => {
  check("kyc-driver-approved", "approved driver lands on driver panel", page.url().endsWith("/app/driver"), page.url());
  await page.waitForSelector("[data-testid=driver-vehicle] >> text=نیسان زامیاد");
  check("kyc-driver-approved", "own vehicle visible", true);
});

async function apiToken(username, password) {
  const r = await fetch(`${BASE}/auth/token`, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username, password }) });
  return (await r.json()).access_token;
}
async function apiCall(token, method, path, body, expectOk = true) {
  const r = await fetch(`${BASE}${path}`, { method, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (expectOk && !r.ok) throw new Error(`${method} ${path} → ${r.status} ${JSON.stringify(data)}`);
  return expectOk ? data : { status: r.status, data };
}
// تاریخ امروز و چند روز بعد به وقت ایران
const iranDate = (days = 0) => new Date(Date.now() + 3.5 * 3600_000 + days * 86400_000).toISOString().slice(0, 10);
const adminToken = await apiToken("qazvin_admin", "admin123");
const driverToken = await apiToken(kycUser, "driver123");
const myVehicle = (await apiCall(driverToken, "GET", "/vehicles/"))[0];
const stockProduct = (await apiCall(adminToken, "GET", "/inventory/products")).find(p => p.stock >= 3);
const orderFor = (day, extra = {}) => apiCall(adminToken, "POST", "/orders/", {
  items: [{ product_id: stockProduct.id, quantity: 1 }], customer: { name: "مشتری امتیاز", mobile: "09121234321" },
  destination_province: "قزوین", destination_city: "قزوین", destination_address: "خیابان نظرسنجی، پلاک ۸", size: "m", priority: false,
  delivery_window_start: `${day}T00:00:00+03:30`, delivery_window_end: `${day}T23:59:00+03:30`, vehicle_id: myVehicle.id, ...extra,
});
// سفارش امروز با کرایه ۱٬۰۰۰٬۰۰۰ ریال (سطح D، اولین سفر امروز ← ۱۵٪) — تحویل فقط پس از بارگیری
const perfOrder = await orderFor(iranDate(0), { delivery_fee: 1000000 });
const skipPickup = await apiCall(driverToken, "PUT", `/orders/${perfOrder.id}/status`, { order_status: "delivered" }, false);
check("day-lock", "delivery without pickup is rejected", skipPickup.status === 400);
await apiCall(driverToken, "PUT", `/orders/${perfOrder.id}/status`, { order_status: "picked_up" });
const skipDeparture = await apiCall(driverToken, "PUT", `/orders/${perfOrder.id}/status`, { order_status: "delivered" }, false);
check("day-lock", "delivery without departing (in transit) is rejected", skipDeparture.status === 400);
await apiCall(driverToken, "PUT", `/orders/${perfOrder.id}/status`, { order_status: "in_transit" });
await apiCall(driverToken, "PUT", `/orders/${perfOrder.id}/status`, { order_status: "delivered" });
// سفارش سه روز بعد: تا آن روز قفل است
const futureOrder = await orderFor(iranDate(3));
const junkCity = await apiCall(adminToken, "POST", "/orders/", {
  items: [{ product_id: stockProduct.id, quantity: 1 }], customer: { name: "مشتری", mobile: "09121234321" },
  destination_province: "قزوین", destination_city: "سسس", destination_address: "خیابان آزمایش، پلاک ۱", size: "m",
  delivery_window_start: `${iranDate(1)}T09:00:00+03:30`, delivery_window_end: `${iranDate(1)}T12:00:00+03:30` }, false);
check("cities", "order with a made-up city is rejected", junkCity.status === 422 && JSON.stringify(junkCity.data).includes("فهرست"), JSON.stringify(junkCity.data).slice(0, 120));
const early = await apiCall(driverToken, "PUT", `/orders/${futureOrder.id}/status`, { order_status: "picked_up" }, false);
check("day-lock", "future order cannot be picked up today", early.status === 400 && early.data.detail.includes("تا آن روز"), early.data.detail);
await session("day-lock-driver", kycUser, "driver123", async page => {
  await page.waitForSelector(`[data-testid=upcoming-orders] >> text=${futureOrder.tracking_code}`);
  const card = page.locator("[data-testid=driver-order]", { hasText: futureOrder.tracking_code });
  check("day-lock", "future order shown locked without action buttons",
    (await card.locator("[data-testid=order-locked]").count()) === 1 && (await card.locator("button").count()) === 0);
}, { viewport: { width: 420, height: 900 } });

// ---------------- پنل راننده: برنامه و کارنامه، پروفایل، مرخصی، تغییر خودرو ----------------
const newPlate = { a: String(10 + Number(runId.slice(-2)) % 89), b: runId.slice(0, 3), region: runId.slice(-2) };
await session("portal-driver", kycUser, "driver123", async page => {
  const nav = await page.locator("[data-testid=app-nav]").first().textContent();
  check("portal-driver", "driver menu has agenda, requests, profile", ["برنامه و کارنامه", "درخواست مرخصی / خودرو", "پروفایل من"].every(t => nav.includes(t)));

  await page.goto(`${BASE}/app/driver/agenda`);   // موبایل: منو در کشوی کناری است
  await page.waitForSelector("[data-testid=agenda-day]");
  check("portal-driver", "agenda shows a full week", (await page.locator("[data-testid=agenda-day]").count()) === 7);
  const firstDay = await page.locator("[data-testid=agenda-day]").first().getAttribute("data-day");
  await page.click("[data-testid=week-prev]");
  await page.waitForFunction(d => document.querySelector("[data-testid=agenda-day]")?.getAttribute("data-day") !== d, firstDay);
  await page.locator("[data-testid=agenda-day]").nth(2).click();
  await page.waitForSelector("[data-testid=agenda-selected] >> text=کارنامه");
  check("portal-driver", "past days open as history (کارنامه)", true);

  await page.goto(`${BASE}/app/driver/profile`);
  await page.waitForSelector("[data-testid=profile-vehicle] >> text=نیسان زامیاد");
  await page.fill("[data-testid=profile-address]", "قزوین، بلوار جدید، پلاک ۲۰");
  await page.click("[data-testid=profile-save]");
  await page.waitForSelector("[data-testid=toast]:has-text('اطلاعات ذخیره شد')");
  check("portal-driver", "profile contact info saved", true);

  // مرخصی فوری امروز
  await page.goto(`${BASE}/app/driver/requests`);
  await page.click("[data-testid=new-leave]");
  await page.click("[data-testid=leave-modal] button:has-text('مرخصی فوری')");
  await page.click("[data-testid=leave-category] >> text=بیماری");
  await pickTime(page, "leave-to-time", 23, 55);
  await page.fill("[data-testid=leave-reason]", "سرماخوردگی شدید");
  await page.click("[data-testid=leave-submit]");
  await page.waitForSelector("[data-testid=toast]:has-text('درخواست مرخصی')");
  await page.waitForSelector("[data-testid=my-request][data-status=pending] >> text=مرخصی فوری");
  check("portal-driver", "urgent leave request sent", true);

  // تغییر خودرو با مدارک
  await apiCall(adminToken, "PUT", `/orders/${futureOrder.id}/status`, { order_status: "canceled" });
  await page.click("[data-testid=new-vehicle-request]");
  await page.click("[data-testid=vr-kind] >> text=ون");
  await page.fill("[data-testid=vr-model]", "ون هیوندای H350");
  await page.fill("[data-testid=vehicle-request-modal] [data-testid=plate-a]", newPlate.a);
  await page.fill("[data-testid=vehicle-request-modal] [data-testid=plate-b]", newPlate.b);
  await page.fill("[data-testid=vehicle-request-modal] [data-testid=plate-region]", newPlate.region);
  await page.fill("[data-testid=vr-weight]", "1500");
  const y = await page.locator("[data-testid=vr-inspection] [data-select-root]:has([aria-label=سال]) select option").nth(2).getAttribute("value");
  await choose(page, "[data-testid=vr-inspection] [role=combobox][aria-label=روز]", "1");
  await choose(page, "[data-testid=vr-inspection] [role=combobox][aria-label=ماه]", "1");
  await choose(page, "[data-testid=vr-inspection] [role=combobox][aria-label=سال]", y);
  await page.click("[data-testid=vehicle-request-next]");
  for (const kind of ["vehicle_photo", "vehicle_card", "technical_inspection"]) await upload(page, kind);
  await page.click("[data-testid=vehicle-request-submit]");
  await page.waitForSelector("[data-testid=toast]:has-text('تغییر خودرو')");
  await page.waitForSelector("[data-testid=my-request][data-status=pending] >> text=تغییر خودرو");
  check("portal-driver", "vehicle change request sent with documents", (await page.locator("[data-testid=my-request][data-status=pending]").count()) === 2);
}, { viewport: { width: 420, height: 900 } });

await session("portal-admin", "qazvin_admin", "admin123", async page => {
  await page.waitForSelector("[data-testid=pending-requests-badge]");
  check("portal-admin", "urgent request badge in menu", (await page.locator("[data-testid=pending-requests-badge].bg-danger").count()) === 1);
  await page.click("[data-testid=app-nav] >> text=درخواست‌های رانندگان");
  const leave = page.locator("[data-testid=driver-request][data-kind=leave]", { hasText: "راننده آزمون" }).first();
  await leave.waitFor();
  check("portal-admin", "urgent leave shown with reason", (await leave.textContent()).includes("سرماخوردگی شدید"));
  await leave.locator("[data-testid=request-approve]").click();
  await page.waitForSelector("[data-testid=toast]:has-text('مرخصی تأیید')");
  const change = page.locator("[data-testid=driver-request][data-kind=vehicle_change]", { hasText: "راننده آزمون" }).first();
  await change.locator("img").first().waitFor();
  check("portal-admin", "vehicle change shows new vehicle and documents", (await change.locator("img").count()) === 3);
  await change.locator("[data-testid=request-approve]").click();
  await page.waitForSelector("[data-testid=toast]:has-text('تغییر خودرو تأیید شد')");
  await page.click("[data-testid=app-nav] >> text=ناوگان");
  await page.waitForSelector("[data-testid=vehicles-table] >> text=ون هیوندای H350");
  check("portal-admin", "new vehicle in fleet", true);
});

await session("portal-driver-after", kycUser, "driver123", async page => {
  await page.waitForSelector("[data-testid=driver-vehicle] >> text=ون هیوندای H350");
  check("portal-driver-after", "driver panel shows new vehicle", true);
  await page.goto(`${BASE}/app/driver/requests`);
  await page.waitForSelector("[data-testid=my-request]");
  check("portal-driver-after", "both requests approved", (await page.locator("[data-testid=my-request][data-status=approved]").count()) >= 2);
  await page.goto(`${BASE}/app/driver/agenda`);
  await page.waitForSelector("[data-testid=agenda-selected] >> text=مرخصی");
  check("portal-driver-after", "today marked as leave in agenda", true);
}, { viewport: { width: 420, height: 900 } });

// ---------------- مرحله ۸: سطح، پورسانت پلکانی، امتیاز سازمان/مشتری/پلتفرم، برترین رانندگان ----------------

let customerLink = null;
await session("perf-admin", "qazvin_admin", "admin123", async page => {
  // قوانین و شبیه‌ساز: ۶۰ تحویل، ۴۵ روز، امتیاز ۴٫۳، سفر ششم ← C ۱۲٪ × ۵۰٪ = ۶٪ از ۱٬۰۰۰٬۰۰۰
  await page.click("[data-testid=app-nav] >> text=سطح‌ها و پورسانت");
  await page.waitForSelector("[data-testid=plan-levels]");
  check("perf-admin", "simulator applies level × daily tier", (await page.locator("[data-testid=sim-commission]").textContent()).includes("۶۰٬۰۰۰"));
  await page.fill("[data-testid=sim-trip]", "11");
  check("perf-admin", "11th trip of the day is commission-free", (await page.locator("[data-testid=sim-commission]").textContent()).includes("۰"));
  await page.click("[data-testid=plan-save]");
  await page.waitForSelector("[data-testid=toast]:has-text('قوانین ذخیره شد')");
  check("perf-admin", "commission plan saved", true);

  // جزئیات سفارش تحویل‌شده: تسویه منجمد + امتیاز سازمان + لینک مشتری
  await page.click("[data-testid=app-nav] >> text=سفارش‌ها");
  await page.locator(`[data-testid=orders-table] tr:has-text("${perfOrder.tracking_code}")`).click();
  await page.waitForSelector("[data-testid=order-settlement]");
  check("perf-admin", "frozen commission shown (15% of fare)", (await page.locator("[data-testid=settlement-commission]").textContent()).includes("۱۵۰٬۰۰۰"));
  await page.click("[data-testid=org-rating-stars] [data-star='5']");
  await page.click("[data-testid=org-rating-save]");
  await page.waitForSelector("[data-testid=toast]:has-text('امتیاز راننده ثبت شد')");
  customerLink = await page.inputValue("[data-testid=customer-link]");
  check("perf-admin", "organization rated driver; customer link ready", /\/rate\//.test(customerLink), customerLink);
  await page.keyboard.press("Escape");

  await page.click("[data-testid=app-nav] >> text=برترین رانندگان");
  await page.waitForSelector("[data-testid=leaderboard-table] tbody tr");
  check("perf-admin", "leaderboard lists drivers", (await rowCount(page, "leaderboard-table")) > 0);
  await page.locator("[data-testid=leaderboard-table] tbody tr", { hasText: "راننده آزمون" }).first().click();
  await page.waitForSelector("[data-testid=driver-overview] [data-testid=level-badge]");
  check("perf-admin", "driver overview shows level, ratings and settled order",
    (await page.locator("[data-testid=overview-orders] >> text=" + perfOrder.tracking_code).count()) === 1
    && (await page.locator("[data-testid=overview-ratings] li").count()) >= 1);
});

await session("perf-customer", null, null, async page => {
  await page.goto(customerLink);
  await page.waitForSelector("[data-testid=rate-form]");
  await page.click("[data-testid=rate-stars] [data-star='5']");
  check("perf-customer", "5 stars show only positive tags",
    (await page.locator("[data-testid=rate-tags] [data-tag=bad]").count()) === 0 && (await page.locator("[data-testid=rate-tags] [data-tag=good]").count()) > 0);
  await page.click("[data-testid=rate-stars] [data-star='1']");
  check("perf-customer", "1 star shows only negative tags", (await page.locator("[data-testid=rate-tags] [data-tag=good]").count()) === 0);
  await page.click("[data-testid=rate-stars] [data-star='3']");
  check("perf-customer", "3 stars show both kinds",
    (await page.locator("[data-testid=rate-tags] [data-tag=good]").count()) > 0 && (await page.locator("[data-testid=rate-tags] [data-tag=bad]").count()) > 0);
  await page.click("[data-testid=rate-stars] [data-star='4']");
  await page.click("[data-testid=rate-tags] >> text=به‌موقع رسید");
  check("perf-customer", "tags do not fill the comment box", (await page.inputValue("[data-testid=rate-comment]")) === "");
  await page.fill("[data-testid=rate-comment]", "راننده خوش‌برخورد بود");
  await page.click("[data-testid=rate-submit]");
  await page.waitForSelector("[data-testid=rate-thanks]");
  check("perf-customer", "customer rated via public link", true);
  await page.reload();
  await page.waitForSelector("[data-testid=rate-expired]");
  check("perf-customer", "reopening the link says expired", (await page.locator("[data-testid=rate-expired]").textContent()).includes("منقضی"));
}, { viewport: { width: 390, height: 844 } });

await session("perf-driver", kycUser, "driver123", async page => {
  await page.goto(`${BASE}/app/driver/profile`);
  await page.waitForSelector("[data-testid=my-performance] [data-testid=level-badge][data-level=D]");
  const text = await page.locator("[data-testid=my-performance]").textContent();
  check("perf-driver", "driver sees level, earnings (850,000) and ratings", text.includes("۸۵۰٬۰۰۰") && text.includes("مشتری"));
}, { viewport: { width: 390, height: 844 } });

await session("perf-platform", "superadmin", "superadmin123", async page => {
  await page.locator("[data-testid=orgs-table] tr", { hasText: "فروشگاه نمونه قزوین" }).locator("text=کاربران").click();
  await page.waitForSelector("[data-testid=platform-driver-ratings]");
  await page.locator("[data-testid=platform-driver-ratings] li", { hasText: "راننده آزمون" }).first().locator("[data-testid=platform-rate-open]").click();
  await page.click("[data-testid=platform-driver-ratings] [data-star='5']");
  await page.click("[data-testid=platform-rate-save]");
  await page.waitForSelector("[data-testid=toast]:has-text('ارزیابی پلتفرم ثبت شد')");
  check("perf-platform", "platform rated a driver", true);
});

// ---------------- مرحله ۹: پیگیری عمومی با کد + جستجوی پیشرفته + به‌روزرسانی خودکار ----------------
const pendingOrder = await apiCall(adminToken, "POST", "/orders/", {
  items: [{ product_id: stockProduct.id, quantity: 1 }], customer: { name: "مشتری پیگیری", mobile: "09129998877" },
  destination_province: "قزوین", destination_city: "قزوین", destination_address: "کوچه محرمانه، پلاک ۴۲", size: "m", priority: false,
  delivery_window_start: `${iranDate(1)}T09:00:00+03:30`, delivery_window_end: `${iranDate(1)}T13:00:00+03:30`, auto_assign: false,
});
await session("track-public", null, null, async page => {
  await page.goto(`${BASE}/`);
  await page.click("[data-testid=nav-track]");
  await page.waitForURL(/\/track$/);
  await page.fill("[data-testid=track-input]", perfOrder.tracking_code.toLowerCase());
  await page.click("[data-testid=track-submit]");
  await page.waitForSelector("[data-testid=track-result][data-status=delivered]");
  check("track-public", "tracking by code from landing page", (await page.locator("[data-testid=track-steps] li").count()) === 5);
  check("track-public", "address hidden without phone digits", !(await page.content()).includes("خیابان نظرسنجی"));
  await page.fill("[data-testid=track-phone]", "0000");
  await page.click("[data-testid=track-verify-submit]");
  await page.waitForSelector("[data-testid=track-phone-error]");
  check("track-public", "wrong phone digits rejected", true);
  await page.fill("[data-testid=track-phone]", "۴۳۲۱");
  await page.click("[data-testid=track-verify-submit]");
  await page.waitForSelector("[data-testid=track-details] >> text=خیابان نظرسنجی");
  check("track-public", "correct phone digits reveal details", true);

  await page.goto(`${BASE}/track/LT-NOPE0000`);
  await page.waitForSelector("[data-testid=track-error]");
  check("track-public", "unknown code shows error", true);

  // به‌روزرسانی خودکار: لغو سفارش در پس‌زمینه بدون رفرش صفحه دیده می‌شود
  await page.goto(`${BASE}/track/${pendingOrder.tracking_code}`);
  await page.waitForSelector("[data-testid=track-result][data-status=pending]");
  check("track-public", "live badge on active order", (await page.locator("[data-testid=track-live]").count()) === 1);
  await apiCall(adminToken, "PUT", `/orders/${pendingOrder.id}/status`, { order_status: "canceled" });
  await page.waitForSelector("[data-testid=track-result][data-status=canceled]", { timeout: 25000 });
  check("track-public", "page updated itself within 15s", (await page.locator("[data-testid=track-status-text]").textContent()).includes("لغو"));
}, { viewport: { width: 420, height: 900 } });

await session("search", "qazvin_admin", "admin123", async page => {
  await page.click("[data-testid=app-nav] >> text=سفارش‌ها");
  await page.waitForSelector("[data-testid=orders-table] tbody tr");
  const codes = async () => (await page.locator("[data-testid=orders-table] tbody tr td:first-child").allTextContents()).join(" ");
  const waitList = () => page.waitForFunction(() => !document.querySelector("[data-testid=orders-count]")?.textContent?.includes("در حال"));

  await page.click("[data-testid=date-presets] [data-preset=today]");
  await page.waitForURL(/delivery_from=/);
  await waitList();
  check("search", "«today» preset includes today's order", (await codes()).includes(perfOrder.tracking_code));
  await page.click("[data-testid=date-presets] [data-preset=tomorrow]");
  await page.waitForFunction(c => !document.querySelector("[data-testid=orders-table]")?.textContent?.includes(c), perfOrder.tracking_code);
  check("search", "«tomorrow» preset excludes today's order", (await codes()).includes(pendingOrder.tracking_code));

  // جستجوی پیشرفته
  await page.goto(`${BASE}/app/orders`);
  await page.click("[data-testid=search-advanced-toggle]");
  await page.fill("[data-testid=search-driver]", "راننده آزمون");
  await page.fill("[data-testid=search-code]", perfOrder.tracking_code.slice(-5));
  await page.click("[data-testid=search-apply]");
  await page.waitForURL(/driver=/);
  await page.waitForFunction(c => {
    const rows = document.querySelectorAll("[data-testid=orders-table] tbody tr");
    return rows.length === 1 && rows[0].textContent.includes(c);
  }, perfOrder.tracking_code, { timeout: 15000 });
  check("search", "driver + partial code filters", true);
  check("search", "active filter chips shown", (await page.locator("[data-testid=active-filters] span").count()) === 2);

  await page.goto(`${BASE}/app/orders?plate=${encodeURIComponent(kycPlate.b)}`);
  await page.waitForSelector(`[data-testid=orders-table] >> text=${perfOrder.tracking_code}`);
  check("search", "plate filter (old vehicle) finds the order", true);
  await page.goto(`${BASE}/app/orders?product=${encodeURIComponent(stockProduct.name.slice(0, 4))}&tracking_code=${perfOrder.tracking_code}`);
  await page.waitForSelector(`[data-testid=orders-table] >> text=${perfOrder.tracking_code}`);
  check("search", "product filter", true);
  await page.goto(`${BASE}/app/orders?product=کالای-ناموجود-xyz`);
  await page.waitForSelector("text=سفارشی یافت نشد");
  check("search", "no results state", true);

  // لینک پیگیری در جزئیات سفارش
  await page.goto(`${BASE}/app/orders?tracking_code=${perfOrder.tracking_code}`);
  await page.locator(`[data-testid=orders-table] tr:has-text("${perfOrder.tracking_code}")`).click();
  check("search", "order detail shows customer tracking link",
    (await page.locator("[data-testid=track-link]").textContent()).endsWith(`/track/${perfOrder.tracking_code}`));
});

// ---------------- مرحله ۷: برنامه رانندگان و پیشنهاد هوشمند راننده ----------------
await session("dispatch", "qazvin_admin", "admin123", async page => {
  await page.click("[data-testid=app-nav] >> text=برنامه رانندگان");
  await page.waitForSelector("[data-testid=schedules-table] tbody tr");
  check("dispatch", "schedules page lists drivers", (await rowCount(page, "schedules-table")) >= 2);
  await page.locator("[data-testid=schedule-day]").nth(1).click();
  await page.locator("[data-testid=schedules-table] tbody tr", { hasText: "لیلا مرادی" }).click();
  await page.waitForSelector("[data-testid=schedule-modal]");
  await page.click("[data-testid=preset-full_time]");
  check("dispatch", "preset fills six working days", (await page.locator("[data-testid=shift-editor] [data-time-field]").count()) === 12);
  await page.fill("[data-testid=max-daily]", "5");
  await page.click("[data-testid=schedule-save]");
  await page.waitForSelector("[data-testid=toast]:has-text('برنامه راننده ذخیره شد')");
  check("dispatch", "driver schedule saved", true);

  // ثبت سفارش: پیشنهادها با پر شدن کالا/مقصد/زمان ظاهر می‌شوند و یکی انتخاب می‌شود
  await page.click("[data-testid=app-nav] >> text=سفارش‌ها");
  await page.click("[data-testid=new-order]");
  const select = page.locator("[data-testid=order-item-product]").first();
  await page.waitForSelector("[data-native-for=order-item-product] option:nth-child(3)", { state: "attached" });
  const stocked = await page.locator("[data-native-for=order-item-product]").first().evaluate(sel => [...sel.options]
    .map(o => ({ value: o.value, stock: Number((/موجودی(?: کل)?: ([۰-۹٬,]+)/.exec(o.text)?.[1] ?? "0").replace(/[٬,]/g, "").replace(/[۰-۹]/g, d => "۰۱۲۳۴۵۶۷۸۹".indexOf(d))) }))
    .filter(o => o.value && o.stock >= 5).map(o => o.value));
  await choose(page, select, stocked[0]);
  await page.fill("[data-testid=customer-name]", "مشتری زمان‌بندی");
  await page.fill("[data-testid=customer-mobile]", "09127778899");
  await choose(page, "[data-testid=order-province]", "قزوین");
  await pickCity(page, "order-city", "قزوین");
  await page.fill("[data-testid=order-address]", "خیابان پیروزی، پلاک ۹");
  await page.waitForSelector("[data-testid=suggestion]", { timeout: 10000 });
  const suggestionCount = await page.locator("[data-testid=suggestion]").count();
  check("dispatch", "order form shows suggested drivers", suggestionCount > 0, `${suggestionCount}`);
  const best = page.locator("[data-testid=suggestion]").first();
  const bestText = await best.textContent();
  check("dispatch", "best suggestion is marked with reasons", bestText.includes("بهترین گزینه") && bestText.includes("ظرفیت آزاد"));
  if (await page.locator("[data-testid=excluded-toggle]").count()) {
    await page.click("[data-testid=excluded-toggle]");
    check("dispatch", "excluded drivers explain why", (await page.locator("[data-testid=excluded] li").count()) > 0);
  }
  const driverName = (await best.locator("span.font-bold").first().textContent()).trim();
  await best.click();
  check("dispatch", "suggestion selectable", (await best.getAttribute("class")).includes("border-brand"));
  await page.click("button[form=order-form]");
  const created = await page.locator("[data-testid=toast]", { hasText: "LT-" }).first().textContent({ timeout: 10000 });
  const code = /LT-[A-Z0-9]{8}/.exec(created)?.[0];
  check("dispatch", "order created with chosen driver", !!code, created);
  await page.locator(`[data-testid=orders-table] tr:has-text("${code}")`).click();
  await page.waitForSelector(`[data-testid=order-detail] >> text=${driverName}`);
  check("dispatch", "order assigned to the selected driver", (await page.locator("[data-testid=order-detail] >> text=تخصیص‌یافته").count()) > 0);
  // لغو تا ظرفیت/سهمیه رانندگان برای اجراهای بعدی آزاد بماند
  await choose(page, "[data-testid=next-status]", "canceled");
  await page.click("[data-testid=apply-status]");
  await page.waitForSelector("[data-testid=order-history] >> text=لغوشده");
});

await session("dispatch-driver", "qazvin_driver1", "driver123", async page => {
  await page.waitForSelector("[data-testid=my-schedule]");
  check("dispatch-driver", "driver sees own weekly schedule", (await page.locator("[data-testid=my-schedule] li").count()) === 7);
});

// ---------------- صفحه اصلی (شهر سه‌بعدی + اسکرول) ----------------
for (const theme of ["light", "dark"]) {
  await session(`landing-${theme}`, null, null, async page => {
    await page.goto(`${BASE}/`);
    await page.waitForSelector("[data-testid=landing]");
    check(`landing-${theme}`, "theme from storage", (await page.evaluate(() => document.documentElement.dataset.theme)) === theme);
    await page.waitForSelector("[data-testid=city-canvas].opacity-100", { timeout: 20000 });
    check(`landing-${theme}`, "3D city rendered", true);
    // شب: چراغ خیابان‌ها و خودروها روشن؛ روز: خاموش
    await page.waitForSelector(`[data-testid=city-canvas][data-night="${theme === "dark" ? 1 : 0}"]`, { timeout: 8000 });
    check(`landing-${theme}`, theme === "dark" ? "street & head lights on at night" : "lights off by day", true);
    // اسکرول ← مرحله‌های سفر به‌جای اسکرول شدن، جای هم ظاهر می‌شوند
    const heroScroll = await page.evaluate(() => document.getElementById("hero").offsetHeight - innerHeight);
    await page.evaluate(y => window.scrollTo({ top: y, behavior: "instant" }), heroScroll * 0.65);
    await page.waitForSelector("[data-testid=hero-stage][data-active=true] >> text=در مسیر مقصد", { timeout: 20000 });
    check(`landing-${theme}`, "scroll drives the trip (in transit)", true);
    await page.evaluate(y => window.scrollTo({ top: y, behavior: "instant" }), heroScroll * 0.97);
    await page.waitForSelector("[data-testid=hero-stage][data-active=true] >> text=تحویل داده شد", { timeout: 20000 });
    check(`landing-${theme}`, "trip reaches delivered", true);
    // گفتگوی بخش «مشکل»: همه پیام‌ها داخل کارت (قبلاً پیام آخر از پایین کارت بیرون می‌زد)
    const problem = await page.evaluate(() => { const s = document.getElementById("problem"); return s.offsetTop + s.offsetHeight * 0.25; });
    await page.evaluate(y => window.scrollTo({ top: y, behavior: "instant" }), problem);
    await page.waitForTimeout(1500);
    const chat = await page.evaluate(() => {
      const box = document.querySelector("[data-testid=problem-chat]").getBoundingClientRect();
      const bubbles = [...document.querySelectorAll("[data-testid=problem-chat] .rounded-2xl")].map(b => b.getBoundingClientRect()).filter(r => r.height > 4);
      return { inside: bubbles.every(r => r.bottom <= box.bottom + 1 && r.left >= box.left - 1 && r.right <= box.right + 1), count: bubbles.length };
    });
    check(`landing-${theme}`, "problem chat bubbles stay inside the card", chat.inside && chat.count >= 4, JSON.stringify(chat));
    check(`landing-${theme}`, "clear 'why' section label", await page.locator("#problem >> text=چرا پسینه؟").count() >= 1);
    check(`landing-${theme}`, "team chat tells a success story", ((await page.textContent("[data-testid=problem-chat]")) ?? "").includes("همه پیام‌ها پاسخ داده شد"));
    await page.evaluate(() => document.getElementById("faq").scrollIntoView({ behavior: "instant" }));
    await page.waitForSelector("[data-testid=section-indicator] >> text=پرسش‌ها", { timeout: 10000 });
    check(`landing-${theme}`, "header shows current section", true);
    await page.click("#faq button:has-text('چطور شروع کنم')");
    await page.waitForSelector("#faq >> text=کد پیگیری می‌گیرید");
    check(`landing-${theme}`, "FAQ accordion opens", true);
  }, { viewport: { width: 1440, height: 900 }, storageState: { cookies: [], origins: [{ origin: BASE, localStorage: [{ name: "theme", value: theme }] }] } });
}

// ---------------- مرحله ۱۰: نقشه ارسال‌ها، مسیر شهربه‌شهر و گزارش «رسیدم به ...» ----------------
// راننده نمونه قزوین (راننده احراز هویت‌شده آزمون، امروز مرخصی تأییدشده دارد)
const routeDriverToken = await apiToken("qazvin_driver1", "driver123");
const routeVehicle = (await apiCall(routeDriverToken, "GET", "/vehicles/")).find(v => v.status !== "inactive");
const routeOrder = await orderFor(iranDate(0), { destination_city: "تاکستان", destination_province: "قزوین",
  customer: { name: "مشتری نقشه", mobile: "09121239876" }, vehicle_id: routeVehicle.id });
const planned = await apiCall(adminToken, "GET", `/orders/${routeOrder.id}/route`);
check("map", "route planned from the warehouse city", planned.available && planned.points[0].city === "قزوین"
  && planned.points[planned.points.length - 1].city === "تاکستان" && planned.progress.fraction === 0, JSON.stringify(planned.points?.map(p => p.city)));
const earlyReport = await apiCall(routeDriverToken, "POST", `/orders/${routeOrder.id}/checkpoints`, { seq: 1 }, false);
check("map", "position report rejected before departure", earlyReport.status === 400);
await apiCall(routeDriverToken, "PUT", `/orders/${routeOrder.id}/status`, { order_status: "picked_up" });

await session("map-driver", "qazvin_driver1", "driver123", async page => {
  const loaded = page.locator("[data-testid=driver-order]", { hasText: routeOrder.tracking_code });
  await loaded.waitFor();
  check("map", "picked-up order offers departure, not delivery",
    (await loaded.locator("button >> text=حرکت به سمت مقصد").count()) === 1 && (await loaded.locator("button >> text=تحویل داده شد").count()) === 0);
  await loaded.locator("button >> text=حرکت به سمت مقصد").click();
  const card = page.locator("[data-testid=driver-order]", { hasText: routeOrder.tracking_code });
  await card.locator("[data-testid=driver-route] [data-testid=route-view]").waitFor();
  check("map", "driver sees route map on in-transit order", (await card.locator("[data-testid=iran-map] svg [data-route]").count()) === 1);
  await card.locator("[data-testid=report-next]").click();
  await card.locator("[data-testid=route-city][data-seq='1'][data-passed=true]").waitFor();
  check("map", "driver reported arriving at the next city", (await card.locator("[data-testid=report-undo]").count()) === 1);
}, { viewport: { width: 420, height: 900 } });

await session("map-admin", "qazvin_admin", "admin123", async page => {
  await page.click("[data-testid=app-nav] >> text=نقشه ارسال‌ها");
  await page.waitForSelector("[data-testid=map-row]");
  check("map", "map page lists shipments with routes", (await page.locator("[data-testid=map-page-map] svg [data-route]").count()) >= 1);
  await page.click(`[data-testid=map-row][data-order=${routeOrder.tracking_code}]`);
  await page.waitForSelector("[data-testid=map-selected]");
  check("map", "selecting a shipment shows its progress", (await page.locator("[data-testid=map-selected]").textContent()).includes(routeOrder.tracking_code));
  await page.click("[data-testid=map-open-order]");
  await page.waitForSelector("[data-testid=order-route] [data-testid=route-city][data-seq='1'][data-passed=true]");
  check("map", "order details show the driver's report", true);
  await page.keyboard.press("Escape");

  // انبار جدید با استان و شهر ← روی نقشه
  await page.click('[data-testid=app-nav] >> text="انبارها"');
  await page.waitForSelector("[data-testid=warehouse-card]");
  await page.click("[data-testid=warehouse-new]");
  const whName = `انبار آزمون ${runId}`;
  await page.fill("[data-testid=wh-name]", whName);
  await choose(page, "[data-testid=wh-province]", "زنجان");
  await pickCity(page, "wh-city", "زنجان");
  await page.click("[data-testid=warehouse-form] button[type=submit]");
  const whCard = page.locator("[data-testid=warehouse-card]", { hasText: whName });
  await whCard.waitFor();
  check("map", "new warehouse is placed on the map", (await whCard.textContent()).includes("روی نقشه: زنجان"));
  await whCard.locator("button >> text=حذف").click();
  await page.click("[data-testid=confirm-dialog] [data-testid=dialog-ok]");
  await whCard.waitFor({ state: "detached" });
  check("map", "empty warehouse can be deleted", true);
});

await session("map-public", null, null, async page => {
  await page.goto(`${BASE}/track/${routeOrder.tracking_code}`);
  await page.waitForSelector("[data-testid=track-route] [data-testid=route-view]");
  check("map", "customer sees route on tracking page", (await page.locator("[data-testid=track-route] [data-testid=route-city]").count()) === 2);
  check("map", "customer sees reported progress", (await page.locator("[data-testid=track-route] [data-testid=route-city][data-passed=true]").count()) === 2);
}, { viewport: { width: 420, height: 900 } });

// ---------------- مرحله ۱۱: تیکت پشتیبانی — مشتری ← سازمان ← پشتیبانی پسینه ----------------
let supportUrl = "", ticketCode = "";
await session("tickets-customer", null, null, async page => {
  await page.goto(`${BASE}/track/${perfOrder.tracking_code}`);
  await page.fill("[data-testid=track-phone]", "4321");
  await page.click("[data-testid=track-verify-submit]");
  await page.click("[data-testid=track-support-open]");
  await page.click("[data-testid=support-category] [data-value=damaged]");
  await page.fill("[data-testid=support-body]", "یکی از کارتن‌ها پاره رسیده است (آزمون مرورگر).");
  await page.setInputFiles("[data-testid=support-file]", { name: "photo.png", mimeType: "image/png", buffer: PNG });
  await page.click("[data-testid=support-submit]");
  await page.waitForSelector("[data-testid=support-created]");
  supportUrl = page.url();
  ticketCode = /TK-[A-Z0-9]{7}/.exec(await page.locator("[data-testid=support-created]").textContent())?.[0] ?? "";
  check("tickets", "customer opened a ticket from tracking page", /\/support\//.test(supportUrl) && !!ticketCode, ticketCode);
  check("tickets", "customer photo attached", (await page.locator("[data-testid=ticket-attachment] img").count()) === 1);
}, { viewport: { width: 420, height: 900 } });

await session("tickets-org", "qazvin_admin", "admin123", async page => {
  await page.waitForSelector("[data-testid=tickets-badge]");
  check("tickets", "org sees a waiting-ticket badge", Number(latinize(await page.locator("[data-testid=tickets-badge]").first().textContent())) >= 1);
  await page.click("[data-testid=app-nav] >> text=پشتیبانی و تیکت‌ها");
  await page.click(`[data-testid=ticket-row][data-code=${ticketCode}]`);
  await page.waitForSelector("[data-testid=ticket-detail]");
  await page.click("[data-testid=ticket-composer] [data-visibility=side]");
  await page.fill("[data-testid=ticket-body]", "یادداشت داخلی آزمون");
  await page.click("[data-testid=ticket-send]");
  await page.waitForSelector("[data-testid=ticket-message][data-visibility=side]");
  await page.click("[data-testid=ticket-composer] [data-visibility=all]");
  await page.fill("[data-testid=ticket-body]", "پاسخ سازمان به مشتری (آزمون)");
  await page.click("[data-testid=ticket-send]");
  await page.waitForSelector("[data-testid=ticket-message] >> text=پاسخ سازمان به مشتری (آزمون)");
  check("tickets", "org replied and wrote an internal note", true);
  await page.click("[data-testid=ticket-escalate]");
  await page.fill("[data-testid=prompt-input]", "برای بررسی ادعای راننده کمک لازم داریم");
  await page.click("[data-testid=prompt-dialog] [data-testid=dialog-ok]");
  await page.waitForSelector("[data-testid=ticket-composer] [data-visibility=staff]");
  check("tickets", "escalated to platform support", (await page.locator("[data-testid=ticket-detail]").textContent()).includes("ارجاع به پشتیبانی پسینه"));
});

await session("tickets-platform", "superadmin", "superadmin123", async page => {
  await page.click("[data-testid=app-nav] >> text=تیکت‌های پشتیبانی");
  await page.click(`[data-testid=ticket-row][data-code=${ticketCode}]`);
  await page.waitForSelector("[data-testid=ticket-detail]");
  check("tickets", "platform does not see the org's internal note",
    !(await page.locator("[data-testid=ticket-thread]").textContent()).includes("یادداشت داخلی آزمون"));
  await page.fill("[data-testid=ticket-body]", "پیام پشتیبانی به سازمان (آزمون)");
  await page.click("[data-testid=ticket-send]");
  await page.waitForSelector("[data-testid=ticket-message][data-side=platform]");
  await page.click("[data-testid=ticket-resolve]");
  await page.waitForSelector("[data-testid=ticket-message] >> text=تیکت به سازمان برگشت");
  check("tickets", "platform replied to org and returned the ticket", true);
});

await session("tickets-customer-follow", null, null, async page => {
  await page.goto(supportUrl);
  await page.waitForSelector("[data-testid=support-page]");
  const thread = await page.locator("[data-testid=ticket-thread]").textContent();
  check("tickets", "customer sees org reply but not internal/platform messages",
    thread.includes("پاسخ سازمان به مشتری (آزمون)") && !thread.includes("یادداشت داخلی آزمون") && !thread.includes("پیام پشتیبانی به سازمان"));
  await page.fill("[data-testid=ticket-body]", "ممنون، منتظر جایگزین هستم.");
  await page.click("[data-testid=ticket-send]");
  await page.waitForSelector("[data-testid=ticket-message] >> text=ممنون، منتظر جایگزین هستم.");
  await page.click("[data-testid=support-resolve]");
  await page.waitForSelector("[data-testid=support-page][data-status=resolved]");
  check("tickets", "customer marked the ticket solved", true);
}, { viewport: { width: 420, height: 900 } });

await session("tickets-driver", "qazvin_driver1", "driver123", async page => {
  await page.goto(`${BASE}/app/driver/support`);   // روی موبایل منو پشت دکمه همبرگری است
  await page.click("[data-testid=ticket-new]");
  await choose(page, "[data-testid=ticket-category]", "payment");
  await page.fill("[data-testid=ticket-new-body]", "پورسانت سفر امروز ثبت نشده (آزمون)");
  await page.click("[data-testid=ticket-submit]");
  await page.waitForSelector("[data-testid=ticket-detail] >> text=پورسانت سفر امروز ثبت نشده (آزمون)");
  check("tickets", "driver opened a ticket to the organization", true);
}, { viewport: { width: 420, height: 900 } });

// ---------------- مرحله ۱۲: انبارگردانی — شمارش کور مدیر انبار ← بررسی و تأیید ادمین ----------------
let stocktakeUrl = "";
await session("stocktake-manager", "qazvin_manager", "manager123", async page => {
  await page.goto(`${BASE}/app/stocktakes`);
  await page.waitForSelector("[data-testid=stocktake-warehouse]");
  await page.click("[data-testid=stocktake-new]");
  await page.click("[data-testid=stocktake-start] button >> text=کالاهای انتخابی");
  await page.locator("[data-testid=stocktake-products] input[type=checkbox]").nth(0).check();
  await page.locator("[data-testid=stocktake-products] input[type=checkbox]").nth(1).check();
  await page.click("[data-testid=stocktake-create]");
  await page.waitForSelector("[data-testid=stocktake-count]");
  stocktakeUrl = page.url();
  check("stocktake", "blind count hides system quantity", !(await page.locator("[data-testid=stocktake-lines]").textContent()).includes("سیستم"));
  // در زبانه «شمرده‌نشده» هر قلم پس از ثبت از فهرست خارج می‌شود
  await page.locator("[data-testid=stocktake-qty]").first().fill("100");
  await page.locator("[data-testid=stocktake-qty]").first().press("Enter");
  await page.waitForFunction(() => document.querySelectorAll("[data-testid=stocktake-line]").length === 1);
  await page.locator("[data-testid=stocktake-qty]").first().fill("100");
  await page.locator("[data-testid=stocktake-qty]").first().press("Enter");
  await page.waitForFunction(() => !document.querySelector("[data-testid=stocktake-submit]")?.hasAttribute("disabled"));
  await page.click("[data-testid=stocktake-submit]");
  await page.click("[data-testid=confirm-dialog] [data-testid=dialog-ok]");
  await page.waitForSelector("[data-testid=stocktake-waiting]");
  check("stocktake", "manager submitted count for review", true);
});
await session("stocktake-admin", "qazvin_admin", "admin123", async page => {
  await page.waitForSelector("[data-testid=stocktakes-badge]");
  check("stocktake", "admin sees a stocktake badge", true);
  await page.goto(stocktakeUrl);
  await page.waitForSelector("[data-testid=stocktake-variance-row]");
  check("stocktake", "admin sees variances after submit", (await page.locator("[data-testid=stocktake-variance]").count()) >= 1);
  await page.locator("[data-testid=stocktake-variance-row] input[type=checkbox]").first().check();
  await page.click("[data-testid=stocktake-recount]");
  await page.click("[data-testid=prompt-dialog] [data-testid=dialog-ok]");
  await page.waitForSelector("[data-testid=stocktake-review]", { state: "detached" });
  check("stocktake", "recount sends the item back to counting", (await page.locator("[data-testid=stocktake-review]").count()) === 0);
});
await session("stocktake-recount", "qazvin_manager", "manager123", async page => {
  await page.goto(stocktakeUrl);
  await page.waitForSelector("[data-testid=stocktake-count]");
  check("stocktake", "manager sees the recount request", (await page.locator("[data-testid=stocktake-count]").textContent()).includes("شمارش مجدد"));
  await page.locator("[data-testid=stocktake-qty]").first().fill("101");
  await page.locator("[data-testid=stocktake-qty]").first().press("Enter");
  await page.waitForFunction(() => !document.querySelector("[data-testid=stocktake-submit]")?.hasAttribute("disabled"));
  await page.click("[data-testid=stocktake-submit]");
  await page.click("[data-testid=confirm-dialog] [data-testid=dialog-ok]");
  await page.waitForSelector("[data-testid=stocktake-waiting]");
});
await session("stocktake-approve", "qazvin_admin", "admin123", async page => {
  await page.goto(stocktakeUrl);
  await page.waitForSelector("[data-testid=stocktake-approve]");
  await page.click("[data-testid=stocktake-approve]");
  await page.click("[data-testid=confirm-dialog] [data-testid=dialog-ok]");
  await page.waitForSelector("[data-testid=stocktake-steps] li:last-child >> svg");
  await page.waitForFunction(() => document.body.textContent.includes("تأیید و اعمال‌شده"));
  check("stocktake", "approval adjusted stock via the ledger", (await page.locator("[data-testid=stocktake-variance-table]").textContent()).includes("اصلاح"));
});

// ---------------- مرحله ۱۵: بخش کاربران — رمز موقت، تغییر اجباری، غیرفعال‌سازی، قفل ورود، گزارش فعالیت ----------------
const opsUser = `ops_${runId}`;
let opsPassword = "";
async function loginRaw(page, username, password) {
  await page.goto(`${BASE}/app/login`);
  await page.fill("#username", username);
  await page.fill("#password", password);
  await page.click("button[type=submit]");
}
await session("users-admin", "qazvin_admin", "admin123", async page => {
  await page.click("[data-testid=app-nav] >> text=کاربران و رانندگان");
  await page.waitForSelector("[data-testid=users-table]");
  const myRow = page.locator("[data-testid=user-row][data-username=qazvin_admin]");
  check("users", "own last login shown", (await myRow.locator("[data-testid=user-last-login]").textContent()).includes("همین الان"));
  await page.click("[data-testid=user-new]");
  await page.waitForSelector("[data-testid=user-form-modal]");
  await choose(page, "[data-testid=user-role]", "warehouse_manager");
  await page.fill("[data-testid=user-fullname]", "کارشناس عملیات آزمون");
  await page.fill("[data-testid=user-username]", opsUser);
  await page.fill("[data-testid=user-mobile]", "۰۹۱۲۳۴۵۶۷۸۹");
  await page.fill("[data-testid=user-email]", `${opsUser}@example.com`);
  await page.click("[data-testid=user-generate-password]");
  opsPassword = await page.inputValue("[data-testid=user-password]");
  check("users", "generated password is visible text", opsPassword.length === 10 && (await page.getAttribute("[data-testid=user-password]", "type")) === "text");
  check("users", "must-change checkbox on by default", await page.isChecked("[data-testid=user-must-change]"));
  await choose(page, "[data-testid=user-warehouse]", { index: 1 });
  await page.click("[data-testid=user-form-submit]");
  await page.waitForSelector(`[data-testid=user-row][data-username=${opsUser}]`);
  check("users", "new user listed", true);
});
await session("users-first-login", null, null, async page => {
  await loginRaw(page, opsUser, opsPassword);
  await page.waitForURL(/\/app\/change-password$/);
  check("users", "temp password forces change page", true);
  await page.goto(`${BASE}/app/orders`);
  await page.waitForURL(/\/app\/change-password$/);
  check("users", "panel blocked until password changed", true);
  await page.fill("[data-testid=password-old]", opsPassword);
  await page.fill("[data-testid=password-new]", "OpsNew2026");
  await page.fill("[data-testid=password-repeat]", "OpsNew2026");
  await page.click("[data-testid=password-submit]");
  await page.waitForURL(/\/app\/inventory$/);
  check("users", "after change lands on manager home", true);
  // تغییر رمز از منوی کاربر
  await page.click("[data-testid=user-menu]");
  await page.click("[data-testid=menu-change-password]");
  await page.fill("[data-testid=password-modal] [data-testid=password-old]", "OpsNew2026");
  await page.fill("[data-testid=password-modal] [data-testid=password-new]", "OpsNew2027");
  await page.fill("[data-testid=password-modal] [data-testid=password-repeat]", "OpsNew2027");
  await page.click("[data-testid=password-modal] [data-testid=password-submit]");
  await page.waitForSelector("[data-testid=password-modal]", { state: "detached" });
  await page.reload();
  await page.waitForSelector("[data-testid=org-name]");
  check("users", "session survives own password change (fresh token)", page.url().endsWith("/app/inventory"), page.url());
});
await session("users-manage", "qazvin_admin", "admin123", async page => {
  await page.goto(`${BASE}/app/users`);
  const row = page.locator(`[data-testid=user-row][data-username=${opsUser}]`);
  await row.waitFor();
  await row.locator("[data-testid=user-actions]").click();
  await page.click("[data-testid=action-reset]");
  await page.click("[data-testid=confirm-dialog] [data-testid=dialog-ok]");
  await page.waitForSelector("[data-testid=temp-password-modal]");
  const temp = (await page.textContent("[data-testid=temp-password]")).trim();
  check("users", "temporary password shown once", /^[a-z0-9]{10}$/.test(temp), temp);
  await page.keyboard.press("Escape");
  const oldLogin = await fetch(`${BASE}/auth/token`, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: opsUser, password: "OpsNew2027" }) });
  check("users", "old password stops working after reset", oldLogin.status === 401, String(oldLogin.status));

  await row.locator("[data-testid=user-actions]").click();
  await page.click("[data-testid=action-deactivate]");
  await page.click("[data-testid=confirm-dialog] [data-testid=dialog-ok]");
  await row.waitFor({ state: "detached" });                      // فیلتر پیش‌فرض «فعال» است
  await choose(page, "[data-testid=users-status]", "inactive");
  await page.waitForSelector(`[data-testid=user-row][data-username=${opsUser}] [data-testid=account-status][data-active=false]`);
  check("users", "deactivated user under «inactive»", true);

  // جزئیات و خط زمانی
  await page.click(`[data-testid=user-row][data-username=${opsUser}] [data-testid=user-open]`);
  await page.waitForSelector("[data-testid=user-timeline]");
  const timeline = await page.textContent("[data-testid=user-timeline]");
  check("users", "timeline has login, reset and deactivation", timeline.includes("ورود به سامانه") && timeline.includes("بازنشانی") && timeline.includes("غیرفعال"));

  await page.click("[data-testid=app-nav] >> text=گزارش فعالیت");
  await page.waitForSelector("[data-testid=activity-table]");
  await choose(page, "[data-testid=activity-category]", "users");
  await page.waitForFunction(() => [...document.querySelectorAll("[data-testid=activity-row]")].every(r => r.dataset.action.startsWith("user.")));
  const actions = await page.locator("[data-testid=activity-row]").evaluateAll(rows => rows.map(r => r.dataset.action));
  check("users", "activity log: create, reset, deactivate", ["user.create", "user.reset_password", "user.deactivate"].every(a => actions.includes(a)), actions.join(","));
});
await session("users-blocked", null, null, async page => {
  await loginRaw(page, opsUser, "anything1");
  await page.waitForSelector("[data-testid=login-error]");
  check("users", "inactive account cannot log in", (await page.textContent("[data-testid=login-error]")).length > 0);
});
// قفل موقت پس از ۵ تلاش ناموفق؛ ادمین قفل را برمی‌دارد
{
  const admin = await apiToken("qazvin_admin", "admin123");
  const list = await (await fetch(`${BASE}/users/`, { headers: { Authorization: `Bearer ${admin}` } })).json();
  const ops = list.find(u => u.username === opsUser);
  await fetch(`${BASE}/users/${ops.id}/activate`, { method: "POST", headers: { Authorization: `Bearer ${admin}` } });
  const attempt = pw => fetch(`${BASE}/auth/token`, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: opsUser, password: pw }) });
  for (let i = 0; i < 5; i++) await attempt("wrong-pass");
  const locked = await attempt("wrong-pass");
  check("users", "sixth try is locked (429)", locked.status === 429, String(locked.status));
}
await session("users-unlock", "qazvin_admin", "admin123", async page => {
  await page.goto(`${BASE}/app/users`);
  await page.waitForSelector("[data-testid=users-table]");
  await choose(page, "[data-testid=users-status]", "locked");
  const row = page.locator(`[data-testid=user-row][data-username=${opsUser}]`);
  await row.waitFor();
  await row.locator("[data-testid=user-actions]").click();
  await page.click("[data-testid=action-unlock]");
  await row.waitFor({ state: "detached" });
  check("users", "unlock removes the lock", true);
});

// ---------------- مرحله ۱۴: گزارش با برند سازمان و مالی حمل‌ونقل ----------------
async function grabDownload(page, selector) {
  const [download] = await Promise.all([page.waitForEvent("download", { timeout: 60000 }), page.click(selector)]);
  const path = await download.path();
  const head = (await import("node:fs")).readFileSync(path).subarray(0, 4).toString("latin1");
  return { name: download.suggestedFilename(), head };
}
await session("reports", "qazvin_admin", "admin123", async page => {
  // رنگ سربرگ سازمان
  await page.click("[data-testid=app-nav] >> text=پروفایل سازمان");
  await page.waitForSelector("[data-testid=brand-color-card]");
  const fileBox = await page.locator("[data-testid=logo-file]").boundingBox();
  check("reports", "logo picker hides Chrome's native file button", !fileBox || fileBox.width <= 2, JSON.stringify(fileBox));
  await page.setInputFiles("[data-testid=logo-file]", { name: "logo.png", mimeType: "image/png",
    buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64") });
  check("reports", "chosen file name shown in Persian picker", (await page.textContent("[data-testid=logo-file-name]")) === "logo.png");
  await page.click("[data-testid=brand-swatch][data-color='#B91C1C']");
  check("reports", "swatch updates the live header preview", (await page.getAttribute("[data-testid=brand-preview]", "data-color")) === "#B91C1C");
  await page.fill("[data-testid=brand-hex]", "#1d4ed8");
  check("reports", "custom hex updates the preview", (await page.getAttribute("[data-testid=brand-preview]", "data-color")) === "#1D4ED8");
  await page.click("[data-testid=brand-save]");
  await page.waitForSelector("[data-testid=brand-save]:disabled");
  check("reports", "brand colour saved", true);

  await page.click("[data-testid=app-nav] >> text=گزارش‌های اکسل و PDF");
  await page.waitForSelector("[data-testid=report-card-finance]");
  // موجودی، سفارش‌ها، دفتر گردش، مالی، نقطه سفارش، برآورد سرمایه
  check("reports", "admin sees all six report cards", (await page.locator("[data-testid^=report-card-]").count()) === 6);
  await page.click("[data-testid=period-picker] button >> text=امسال");
  const pdf = await grabDownload(page, "[data-testid=report-pdf-finance]");
  check("reports", "finance PDF downloads with Jalali-stamped name", pdf.head === "%PDF" && /^Pasineh_Transport_Finance_14\d\d-\d\d-\d\d\.pdf$/.test(pdf.name), pdf.name);
  const xlsx = await grabDownload(page, "[data-testid=report-excel-inventory]");
  check("reports", "inventory Excel downloads", xlsx.head.startsWith("PK") && xlsx.name.endsWith(".xlsx"), xlsx.name);
  const ledger = await grabDownload(page, "[data-testid=report-pdf-ledger]");
  check("reports", "ledger PDF downloads", ledger.head === "%PDF", ledger.name);

  await page.click("[data-testid=app-nav] >> text=مالی حمل‌ونقل");
  await page.waitForSelector("[data-testid=period-picker]");
  await page.click("[data-testid=period-picker] button >> text=امسال");
  await page.waitForSelector("[data-testid=finance-dashboard]");
  await page.waitForSelector("[data-testid=finance-drivers]");
  const trips = Number(await page.getAttribute("[data-testid=finance-dashboard]", "data-trips"));
  check("reports", "finance dashboard shows delivered trips this year", trips > 0, String(trips));
  check("reports", "driver breakdown rows", (await page.locator("[data-testid=finance-drivers] tbody tr").count()) > 0);
  check("reports", "monthly chart rendered", (await page.locator("[data-testid=finance-months] > div").count()) > 0);
  const fin = await grabDownload(page, "[data-testid=finance-excel]");
  check("reports", "finance Excel from dashboard", fin.head.startsWith("PK"), fin.name);
});
await session("reports-manager", "qazvin_manager", "manager123", async page => {
  check("reports-manager", "no finance entry for warehouse manager", (await page.locator("[data-testid=app-nav] >> text=مالی حمل‌ونقل").count()) === 0);
  await page.click("[data-testid=app-nav] >> text=گزارش‌های اکسل و PDF");
  await page.waitForSelector("[data-testid=report-card-inventory]");
  // بدون مالی و برآورد سرمایه
  check("reports-manager", "manager sees four report cards", (await page.locator("[data-testid^=report-card-]").count()) === 4);
  const inv = await grabDownload(page, "[data-testid=report-pdf-inventory]");
  check("reports-manager", "manager inventory PDF", inv.head === "%PDF", inv.name);
});
const forbidden = await fetch(`${BASE}/reports/finance`, { headers: { Authorization: `Bearer ${await apiToken("qazvin_manager", "manager123")}` } });
check("reports-manager", "finance API forbidden for manager", forbidden.status === 403, String(forbidden.status));

// ---------------- مرحله ۱۳: کاتالوگ — قیمت تاریخ‌دار با یارانه، تنوع، ورود اکسل ----------------
const catalogXlsx = Buffer.from(await (await fetch(`${BASE}/catalog/export`, { headers: { Authorization: `Bearer ${adminToken}` } })).arrayBuffer());
check("catalog", "catalog export is a real xlsx", catalogXlsx.subarray(0, 2).toString() === "PK" && catalogXlsx.length > 2000, String(catalogXlsx.length));
await session("catalog", "qazvin_admin", "admin123", async page => {
  await page.click("[data-testid=app-nav] >> text=انبار و کالاها");
  await page.waitForSelector("[data-testid=product-row]");
  await page.locator("[data-testid=product-open]").first().click();
  await page.waitForSelector("[data-testid=catalog-info]");
  await page.click("[data-testid=catalog-product] button >> text=قیمت‌ها");
  await page.waitForSelector("[data-testid=catalog-price-form]");
  const before = await page.locator("[data-testid=price-row]").count();
  await page.fill("[data-testid=price-base]", "2000000");
  await page.check("[data-testid=price-subsidized]");
  await page.fill("[data-testid=price-subsidy]", "10");
  check("catalog", "subsidy preview computes the selling price", latinize(await page.locator("[data-testid=price-preview]").textContent()).replace(/[,٬]/g, "").includes("1800000"));
  await page.click("[data-testid=price-submit]");
  await page.waitForFunction(n => document.querySelectorAll("[data-testid=price-row]").length > n, before);
  check("catalog", "new dated price becomes current", latinize(await page.locator("[data-testid=catalog-current-price]").textContent()).replace(/[,٬]/g, "").includes("1800000"));
  await page.click("[data-testid=catalog-product] button >> text=تنوع‌ها");
  await page.fill("[data-testid=variant-sku]", `VAR-${runId}`);
  await page.fill("[data-testid=variant-label]", "سری آزمون مرورگر");
  await page.click("[data-testid=variant-submit]");
  await page.waitForSelector("[data-testid=catalog-product] >> text=سری آزمون مرورگر");
  check("catalog", "variant created and opened", (await page.locator("[data-testid=catalog-product]").textContent()).includes(`VAR-${runId}`));
  await page.keyboard.press("Escape");

  await page.click("[data-testid=catalog-import-open]");
  await page.setInputFiles("[data-testid=import-file]", { name: "catalog.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: catalogXlsx });
  await page.click("[data-testid=import-check]");
  await page.waitForSelector("[data-testid=import-report]");
  check("catalog", "re-importing the export has no errors", (await page.getAttribute("[data-testid=import-report]", "data-errors")) === "0");
  await page.click("[data-testid=import-apply]");
  await page.waitForSelector("[data-testid=import-report][data-applied=true]");
  check("catalog", "import applied", true);
});

// ---------------- کنترل‌های سفارشی به‌جای ظاهر پیش‌فرض کروم ----------------
await session("native-ui-public", null, null, async page => {
  await page.goto(`${BASE}/request`);
  await page.waitForSelector("[data-testid=request-step]");
  await page.hover("[data-testid=theme-toggle]");
  await page.waitForSelector("[data-testid=app-tooltip]");
  check("native-ui", "theme toggle shows a themed tooltip (not the browser one)",
    (await page.locator("[data-testid=app-tooltip]").textContent()).includes("تم") && (await page.getAttribute("[data-testid=theme-toggle]", "title")) === null);
  await page.mouse.move(0, 0);
  await page.click("[data-testid=request-next]");
  await page.waitForSelector("[data-testid=validation-bubble]");
  check("native-ui", "empty required field shows a Persian validation bubble", /فیلد را پر کنید|انتخاب کنید/.test(await page.locator("[data-testid=validation-bubble]").textContent()));
  await choose(page, "[data-testid=req-province]", "قزوین");
  check("native-ui", "custom select shows the chosen value", (await page.getAttribute("[data-testid=req-province]", "data-value")) === "قزوین");
});
await session("native-ui-panel", "qazvin_admin", "admin123", async page => {
  await page.click("[data-testid=app-nav] >> text=سفارش‌ها");
  await page.click("[data-testid=new-order]");
  await page.click("[data-testid=order-date]");
  await page.waitForSelector("[data-testid=order-date-calendar]");
  check("native-ui", "Jalali calendar opens", /فروردین|اردیبهشت|خرداد|تیر|مرداد|شهریور|مهر|آبان|آذر|دی|بهمن|اسفند/.test(await page.locator("[data-testid=order-date-calendar]").textContent()));
  const day = await page.locator("[data-testid=order-date-calendar] [data-day]").nth(20).getAttribute("data-day");
  await page.locator("[data-testid=order-date-calendar] [data-day]").nth(20).click();
  check("native-ui", "picked day stored as ISO date", (await page.getAttribute("[data-testid=order-date]", "data-value")) === day, day);
  await page.click("[data-testid=order-from]");
  await page.click("[data-testid=order-from-picker] [data-hour='10']");
  await page.click("[data-testid=order-from-picker] [data-minute='30']");
  check("native-ui", "time picker sets HH:MM", (await page.getAttribute("[data-testid=order-from]", "data-value")) === "10:30");
  await page.keyboard.press("Escape");
});

// ---------------- تم پیش‌فرض سیستم، تغییر یک‌کلیکی، و شروع صفحه جدید از بالا ----------------
await session("ux-system-dark", null, null, async page => {
  await page.goto(`${BASE}/track`);
  check("ux", "first visit follows system dark theme", (await page.evaluate(() => document.documentElement.dataset.theme)) === "dark");
  await page.click("[data-testid=theme-toggle]");
  await page.waitForFunction(() => document.documentElement.dataset.theme === "light");
  check("ux", "one click switches to light and is remembered", (await page.evaluate(() => localStorage.getItem("theme"))) === "light");
}, { colorScheme: "dark" });
await session("ux-scroll", null, null, async page => {
  await page.goto(`${BASE}/`);
  await page.waitForSelector("[data-testid=landing]");
  await page.evaluate(() => window.scrollTo({ top: document.body.scrollHeight, behavior: "instant" }));
  await page.waitForTimeout(400);
  check("ux", "landing scrolled to bottom", (await page.evaluate(() => window.scrollY)) > 2000);
  await page.click("[data-testid=nav-track]");
  await page.waitForURL(/\/track$/);
  await page.waitForSelector("[data-testid=track-input]");
  check("ux", "new page starts from the top", (await page.evaluate(() => window.scrollY)) === 0);
  check("ux", "page fades in", (await page.locator(".page-fade").count()) === 1);
}, { viewport: { width: 1280, height: 800 } });

// ---------------- فرم درخواست سازمان + پیگیری ----------------
let referralRun = "";
await session("request", null, null, async page => {
  await page.goto(`${BASE}/`);
  await page.click("[data-testid=cta-request]");
  await page.waitForURL(/\/request\?plan=trial$/);
  await page.waitForSelector("[data-testid=request-plan] >> text=آزمایشی");
  check("request", "header CTA starts the free trial request", true);
  // داده یکتا در هر اجرا: درخواست تکراری با همان شناسه ملی عمداً رد می‌شود
  const run = String(Date.now()).slice(-10);
  await page.fill("[data-testid=req-name]", `فروشگاه آزمون مرورگر ${run}`);
  await page.fill("[data-testid=req-legal-name]", "شرکت آزمون مرورگر");
  await page.click("[data-testid=req-business] >> text=فروشگاه اینترنتی");
  await page.fill("[data-testid=req-national-id]", `1${run}`);
  await choose(page, "[data-testid=req-province]", "قزوین");
  await pickCity(page, "req-city", "قزوین");
  await page.fill("[data-testid=req-address]", "خیابان پیروزی، کوچه ۱۲، پلاک ۴");
  await page.click("[data-testid=request-next]");
  await page.waitForSelector("[data-testid=request-step][data-step='1']");
  await page.click("[data-testid=request-next]");
  check("request", "step 2 validates choices", (await page.locator("[data-testid=request-error]").count()) === 1);
  await page.click("[data-testid=req-employees] >> text=۱۱ تا ۵۰");
  await page.click("[data-testid=req-volume] >> text=۱۰۰ تا ۱۰۰۰");
  await page.click("[data-testid=request-next]");
  await page.waitForSelector("[data-testid=request-step][data-step='2']");
  await page.fill("[data-testid=req-contact-name]", "مسئول آزمون");
  await page.fill("[data-testid=req-mobile]", "۰۹۱۲۳۴۵۶۷۸۹");
  await page.fill("[data-testid=req-email]", "e2e-request@example.com");
  // «چطور با ما آشنا شدید؟» — اختیاری؛ «سایر» توضیح می‌خواهد و کلیک دوباره انتخاب را برمی‌دارد
  check("request", "referral question is optional (nothing preselected)", (await page.locator("[data-testid=req-referral] [aria-checked=true]").count()) === 0);
  check("request", "terms link shown before submit", (await page.locator("[data-testid=req-terms] a[href='/terms']").count()) === 1);
  await page.click("[data-testid=req-referral] [data-value=other]");
  await page.waitForSelector("[data-testid=req-referral-detail]");
  check("request", "'other' asks where they heard about us", (await page.getAttribute("[data-testid=req-referral-detail]", "required")) !== null);
  await page.click("[data-testid=req-referral] [data-value=other]");
  await page.waitForSelector("[data-testid=req-referral-detail]", { state: "detached" });
  check("request", "clicking again clears the optional answer", (await page.locator("[data-testid=req-referral] [aria-checked=true]").count()) === 0);
  await page.click("[data-testid=req-referral] [data-value=other]");
  await page.fill("[data-testid=req-referral-detail]", `پادکست آزمون ${run}`);
  check("request", "request page has no horizontal overflow", await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.click("[data-testid=request-submit]");
  const code = (await page.locator("[data-testid=request-tracking-code]").textContent({ timeout: 10000 })).trim();
  check("request", "request submitted with tracking code", /^REQ-/.test(code), code);
  await page.fill("[data-testid=status-code]", code);
  await page.click("#status button[type=submit]");
  await page.waitForSelector("[data-testid=status-result] >> text=در انتظار");
  check("request", "status lookup shows pending", true);
  referralRun = run;
});

// ادمین پلتفرم منبع آشنایی را در فهرست، جزئیات و خلاصه می‌بیند
await session("request-platform", "superadmin", "superadmin123", async page => {
  await page.goto(`${BASE}/app/platform/requests`);
  await page.waitForSelector("[data-testid=requests-table] tbody tr");
  const cell = page.locator("[data-testid=request-referral]", { hasText: `پادکست آزمون ${referralRun}` });
  check("request", "platform admin sees the referral answer", (await cell.count()) === 1);
  check("request", "referral summary card shown", (await page.locator("[data-testid=referral-summary] [data-source=other]").count()) === 1);
  await cell.click();
  await page.waitForSelector("[role=dialog] >> text=آشنایی با ما");
  check("request", "referral shown in request details", (await page.locator(`[role=dialog] >> text=پادکست آزمون ${referralRun}`).count()) >= 1);
});

// ---------------- صفحه‌های درباره ما، سوالات متداول، قوانین + پانویس ----------------
await session("info-pages", null, null, async page => {
  await page.goto(`${BASE}/`);
  await page.waitForSelector("[data-testid=landing]");
  await page.click("[data-testid=landing-faq-all]");
  await page.waitForSelector("[data-testid=faq-page]");
  check("info", "landing links to the full FAQ", page.url().endsWith("/faq"));
  const totalFaq = await page.locator("[data-testid=faq-item]").count();
  check("info", "FAQ has many organization questions", totalFaq >= 30, String(totalFaq));
  await page.fill("[data-testid=faq-search]", "کمیسیون");
  await page.waitForFunction(n => document.querySelectorAll("[data-testid=faq-item]").length < n, totalFaq);
  check("info", "FAQ search filters questions", (await page.locator("[data-testid=faq-item]").count()) >= 1);
  await page.fill("[data-testid=faq-search]", "zzzz-nothing");
  await page.waitForSelector("[data-testid=faq-empty]");
  check("info", "FAQ search empty state", true);
  // پرسشی از انتهای صفحه، بعد از جست‌وجو باید واقعاً دیده شود (نه فقط در DOM باشد)
  await page.fill("[data-testid=faq-search]", "شمسی");
  await page.waitForSelector("#q-persian");
  await page.evaluate(() => document.getElementById("q-persian").scrollIntoView({ block: "center" }));
  const opacityOf = () => { let n = document.getElementById("q-persian"), op = 1; while (n) { op *= Number(getComputedStyle(n).opacity); n = n.parentElement; } return op; };
  const shown = await page.waitForFunction(`(${opacityOf})() > 0.95`, null, { timeout: 8000 }).then(() => true, () => false);
  check("info", "searched question from page bottom is visible", shown, `opacity=${await page.evaluate(`(${opacityOf})()`)}`);
  await page.fill("[data-testid=faq-search]", "");
  await page.click("[data-testid=faq-categories] [data-category=drivers]");
  check("info", "FAQ category filter", (await page.locator("[data-testid=faq-item]").count()) < totalFaq);
  await page.goto(`${BASE}/faq#q-day-lock`);
  await page.waitForSelector("#q-day-lock[data-state=open]");
  check("info", "FAQ deep link opens that question", true);

  await page.click("[data-testid=footer-site-pages] >> text=درباره ما");
  await page.waitForSelector("[data-testid=about-page]");
  check("info", "about page from footer", page.url().endsWith("/about"));
  const atTop = await page.waitForFunction(() => window.scrollY === 0, null, { timeout: 3000 }).then(() => true, () => false);
  check("info", "about page starts at top", atTop, String(await page.evaluate(() => window.scrollY)));
  await page.click("[data-testid=footer-site-pages] >> text=قوانین و مقررات");
  await page.waitForSelector("[data-testid=terms-page]");
  check("info", "terms has numbered clauses", (await page.locator("[data-testid=terms-clause]").count()) >= 10);
  check("info", "terms table of contents", (await page.locator("[data-testid=terms-toc] a").count()) >= 10);

  // نام بزرگ پانویس: قبل از انتها نیمه‌پر و در انتها کامل
  await page.goto(`${BASE}/`);
  await page.waitForSelector("[data-testid=landing]");
  const max = await page.evaluate(() => document.documentElement.scrollHeight - innerHeight);
  const progress = () => page.getAttribute("[data-testid=footer-wordmark]", "data-progress").then(Number);
  await page.evaluate(y => window.scrollTo({ top: y, behavior: "instant" }), max - 120);
  await page.waitForFunction(() => Number(document.querySelector("[data-testid=footer-wordmark]").dataset.progress) > 0, null, { timeout: 8000 }).catch(() => {});
  const mid = await progress();
  await page.evaluate(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "instant" }));
  await page.waitForFunction(() => document.querySelector("[data-testid=footer-wordmark]").dataset.progress === "1.00", null, { timeout: 8000 }).catch(() => {});
  const end = await progress();
  check("info", "footer wordmark fills gradually", mid > 0.2 && mid < 0.95 && end === 1, `${mid} → ${end}`);
}, { viewport: { width: 1280, height: 800 } });

// هیچ صفحه عمومی روی موبایل اسکرول افقی نداشته باشد
// ---------------- حریم خصوصی، تعرفه‌ها، بازیابی رمز و پیش‌نمایش لینک ----------------
await session("brand-pages", null, null, async page => {
  await page.goto(`${BASE}/about`);
  await page.click("[data-testid=footer-site-pages] >> text=حریم خصوصی");
  await page.waitForSelector("[data-testid=privacy-page]");
  check("brand", "privacy policy opens from footer", (await page.locator("[data-testid=privacy-clause]").count()) >= 8);
  check("brand", "privacy has table of contents", (await page.locator("[data-testid=privacy-toc] a").count()) >= 8);
  check("brand", "footer shows support phone", ((await page.textContent("[data-testid=footer-phone]")) ?? "").includes("۰۹۹۲"));

  await page.goto(`${BASE}/pricing`);
  await page.waitForSelector("[data-testid=pricing-page]");
  check("brand", "four pricing plans", (await page.locator("[data-testid=plan-card]").count()) === 4);
  const monthly = await page.textContent("[data-plan=pro] [data-testid=plan-price]");
  await page.click("[data-testid=billing-annual]");
  await page.waitForFunction(m => document.querySelector("[data-plan=pro] [data-testid=plan-price]")?.textContent !== m, monthly);
  check("brand", "annual billing changes the price", ((await page.textContent("[data-plan=pro] [data-testid=plan-price]")) ?? "").includes("در سال"));
  check("brand", "feature comparison table", (await page.locator("[data-testid=pricing-compare] tbody tr").count()) >= 8);
  await page.click("[data-plan=pro] [data-testid=plan-cta]");
  await page.waitForSelector("[data-testid=request-plan] >> text=حرفه‌ای");
  check("brand", "chosen plan carried into the request form", page.url().includes("plan=pro"));

  // بدون پیامک/ایمیل تنظیم‌شده: لینک «فراموشی رمز» نیست و صفحه آن راه دیگر را توضیح می‌دهد
  await page.goto(`${BASE}/app/login`);
  await page.waitForSelector("#username");
  await page.waitForTimeout(800);
  check("brand", "no forgot-password link without SMS/email", (await page.locator("[data-testid=forgot-password-link]").count()) === 0);
  await page.goto(`${BASE}/app/forgot-password`);
  await page.waitForSelector("[data-testid=reset-unavailable]");
  check("brand", "forgot-password explains admin reset when disabled", true);

  const og = await fetch(`${BASE}/og.png`);
  check("brand", "link preview image served", og.ok && og.headers.get("content-type") === "image/png", String(og.status));
  const html = await (await fetch(`${BASE}/pricing`)).text();
  check("brand", "pricing route served directly and has og:image", html.includes('property="og:image"'));
});

await session("mobile-overflow", null, null, async page => {
  for (const path of ["/", "/request", "/track", "/about", "/faq", "/terms", "/privacy", "/pricing", "/app/forgot-password"]) {
    await page.goto(`${BASE}${path}`);
    await page.waitForTimeout(600);
    const { sw, w } = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, w: innerWidth }));
    check("mobile", `${path} has no horizontal overflow`, sw <= w, `${sw} > ${w}`);
  }
}, { viewport: { width: 390, height: 844 } });

// ---------------- نقطه سفارش هوشمند و برآورد سرمایه خرید ----------------
await session("reorder", "admin", "admin123", async page => {
  await page.goto(`${BASE}/app/reorder`);
  await page.waitForSelector("[data-testid=rop-table] tbody tr");
  const rows = await rowCount(page, "rop-table");
  check("reorder", "items listed with formula status", rows >= 10, String(rows));
  check("reorder", "urgent items sorted first", (await page.getAttribute("[data-testid=rop-row] >> nth=0", "data-status")) !== "ok");
  await page.click("text=نقطه سفارش چطور محاسبه می‌شود؟");
  await page.waitForSelector("[data-testid=rop-formula] >> text=SS = z");
  check("reorder", "formula explainer opens", true);
  // جزئیات یک کالای دارای سابقه: محاسبه با عددهای واقعی
  const ok = page.locator("[data-testid=rop-row][data-status=ok]").first();
  const sku = await ok.getAttribute("data-sku");
  await ok.click();
  await page.waitForSelector("[data-testid=rop-breakdown] >> text=موجودی اطمینان (SS)");
  check("reorder", "item breakdown shows SS and ROP", (await page.locator("[data-testid=rop-breakdown] dd").count()) >= 8);
  await page.click("[data-testid=rop-modal] >> text=عدد دستی");
  await page.fill("[data-testid=rop-manual]", "123");
  await page.fill("[data-testid=rop-lead]", "12");
  await page.click("[data-testid=rop-save]");
  await page.waitForSelector("[data-testid=rop-modal]", { state: "detached" });
  await page.waitForFunction(s => document.querySelector(`[data-testid=rop-row][data-sku="${s}"]`)?.textContent.includes("۱۲۳"), sku);
  check("reorder", "manual reorder point saved", true);
  await page.click(`[data-testid=rop-row][data-sku="${sku}"]`);
  await page.waitForSelector("[data-testid=rop-breakdown] >> text=اختصاصی این کالا");
  check("reorder", "item lead time override used in formula", true);
  await page.click("[data-testid=rop-modal] >> text=خودکار با فرمول");
  await page.click("[data-testid=rop-save]");
  await page.waitForSelector("[data-testid=rop-modal]", { state: "detached" });
  await page.waitForFunction(s => document.querySelector(`[data-testid=rop-row][data-sku="${s}"]`)?.textContent.includes("خودکار"), sku);
  check("reorder", "back to automatic mode", true);
});

await session("capital", "admin", "admin123", async page => {
  await page.goto(`${BASE}/app/capital`);
  await page.waitForSelector("[data-testid=capital-plan]");
  const total = Number(await page.getAttribute("[data-testid=capital-plan]", "data-total"));
  check("capital", "plan has required capital", total > 0, String(total));
  check("capital", "six months by default", (await rowCount(page, "capital-months")) === 6);
  check("capital", "items breakdown", (await rowCount(page, "capital-items")) >= 5);
  check("capital", "missing purchase cost is flagged", (await page.locator("[data-testid=capital-estimated]").count()) === 1);
  await page.fill("[data-testid=capital-price-growth]", "10");
  await page.waitForFunction(t => Number(document.querySelector("[data-testid=capital-plan]")?.dataset.total) > t, total, { timeout: 10000 });
  check("capital", "higher inflation → more capital", true);
  await page.click("text=۱۲ ماه");
  await page.waitForFunction(() => document.querySelectorAll("[data-testid=capital-months] tbody tr").length === 12, null, { timeout: 10000 });
  check("capital", "12-month horizon", true);
});

// ---------------- اعلان‌ها: جزئیات، بستن، رفتن به همان مورد ----------------
{
  const warehouse = (await apiCall(adminToken, "GET", "/warehouses/"))[0];
  const sku = `NTF-${Date.now() % 1e8}`;
  const { product } = await apiCall(adminToken, "POST", "/inventory/products", {
    name: "کالای آزمون اعلان", sku, price: 1000, weight_kg: 1, initial_quantity: 30, warehouse_id: warehouse.id });
  await apiCall(adminToken, "PUT", `/inventory/stock/${product.id}`, { quantity: 30, reorder_point: 10, warehouse_id: warehouse.id });
  // خروج ضایعات ← موجودی ۵ (زیر نقطه سفارش ۱۰) ← هشدار همان لحظه
  await apiCall(adminToken, "POST", "/inventory/movements", {
    product_id: product.id, warehouse_id: warehouse.id, movement_type: "damage", quantity: 25, reason: "آزمون اعلان" });
  const someOrder = (await apiCall(adminToken, "GET", "/orders/?limit=1"))[0];

  await session("notifications", "qazvin_admin", "admin123", async page => {
    await page.waitForSelector("[data-testid=notifications-count]");
    check("notifications", "unread badge on bell", true);
    await page.click("[data-testid=notifications-bell]");
    const item = page.locator("[data-testid=notification-item][data-kind=low_stock]", { hasText: "کالای آزمون اعلان" }).first();
    await item.waitFor();
    const text = await item.textContent();
    check("notifications", "rich details (stock, reorder point, warehouse)", text.includes("موجودی فعلی") && text.includes("نقطه سفارش") && text.includes(warehouse.name), text);
    check("notifications", "unread item marked", (await item.getAttribute("data-read")) === "0");
    // کلیک ← صفحه انبار و همان کالا برجسته
    await item.locator("[data-testid=notification-open]").click();
    await page.waitForURL(/\/app\/inventory$/);
    await page.waitForSelector(`[data-focus="product-${product.id}"].focus-flash`, { timeout: 10000 });
    check("notifications", "click opens the item in the inventory tab", true);
    const inView = await page.evaluate(id => {
      const r = document.querySelector(`[data-focus="product-${id}"]`).getBoundingClientRect();
      return r.top >= 0 && r.bottom <= innerHeight;
    }, product.id);
    await page.waitForTimeout(600);
    check("notifications", "item scrolled into view", inView || await page.evaluate(id => {
      const r = document.querySelector(`[data-focus="product-${id}"]`).getBoundingClientRect();
      return r.top >= 0 && r.bottom <= innerHeight;
    }, product.id));
    await page.click("[data-testid=notifications-bell]");
    await item.waitFor();
    check("notifications", "opened item is now read", (await item.getAttribute("data-read")) === "1");
    // فیلتر دسته
    await page.click("[data-testid=notifications-filter-inventory]");
    const kinds = await page.locator("[data-testid=notification-item]").evaluateAll(els => els.map(e => e.dataset.kind));
    check("notifications", "category filter", kinds.length > 0 && kinds.every(k => k === "low_stock" || k === "out_of_stock"), kinds.join(","));
    // بستن با ✕
    const before = await page.locator("[data-testid=notification-item]").count();
    // حذف در رابط کاربری فوری (optimistic) است؛ بررسی سرور بعد از پاسخ خود درخواست DELETE
    const deleted = page.waitForResponse(r => r.request().method() === "DELETE" && /\/notifications\/\d+$/.test(r.url()), { timeout: 10000 });
    await item.locator("[data-testid=notification-dismiss]").click();
    await page.waitForFunction(n => document.querySelectorAll("[data-testid=notification-item]").length === n - 1, before);
    await deleted;
    const server = await page.evaluate(async () => (await (await fetch("/notifications/", { headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` } })).json()).items);
    check("notifications", "dismissed item removed on server", !server.some(n => n.message.includes("کالای آزمون اعلان") && n.kind === "low_stock"));
    // خواندن همه
    if (await page.locator("[data-testid=notifications-read-all]").isEnabled()) await page.click("[data-testid=notifications-read-all]");
    await page.waitForSelector("[data-testid=notifications-count]", { state: "detached" });
    check("notifications", "read all clears the badge", true);
    await page.keyboard.press("Escape");
    await page.waitForSelector("[data-testid=notifications-panel]", { state: "detached" });
    check("notifications", "Esc closes the panel", true);
    // لینک مستقیم سفارش ← جزئیات همان سفارش
    if (someOrder) {
      await page.goto(`${BASE}/app/orders?order=${someOrder.id}`);
      await page.waitForSelector(`[data-testid=order-detail] >> text=${someOrder.tracking_code}`);
      check("notifications", "order link opens that order", true);
    }
  });
  await session("notifications-mobile", "qazvin_admin", "admin123", async page => {
    await page.click("[data-testid=notifications-bell]");
    await page.waitForSelector("[data-testid=notifications-panel]");
    const { left, right, w } = await page.evaluate(() => {
      const r = document.querySelector("[data-testid=notifications-panel]").getBoundingClientRect();
      return { left: r.left, right: r.right, w: innerWidth };
    });
    check("notifications-mobile", "panel fits the screen", left >= 0 && right <= w, `${left}..${right} / ${w}`);
  }, { viewport: { width: 390, height: 844 } });
}

// ---------------- راهنمای تعاملی (فقط بار اول) ----------------
await session("tour", "qazvin_manager", "manager123", async page => {
  await page.waitForSelector("[data-testid=tour][data-tour-id=main-manager]", { timeout: 10000 });
  check("tour", "main tour opens for a first-time user", true);
  await page.click("[data-testid=tour-next]");
  await page.waitForSelector("[data-testid=tour][data-step='1'] [data-testid=tour-spotlight]");
  check("tour", "next step highlights its target", true);
  await page.click("[data-testid=tour-back]");
  await page.waitForSelector("[data-testid=tour][data-step='0']");
  check("tour", "back works", true);
  await page.click("[data-testid=tour-skip]");
  await page.waitForSelector("[data-testid=tour]", { state: "detached" });
  await page.reload();
  await page.waitForSelector("[data-testid=org-name]");
  await page.waitForTimeout(2000);
  // راهنمای اصلی دوباره باز نمی‌شود؛ صفحه خانه مدیر انبار (انبار و کالاها) راهنمای خودش را دارد که حالا نوبت آن است
  check("tour", "skipped tour does not reopen", (await page.locator("[data-testid=tour][data-tour-id=main-manager]").count()) === 0);
  const homeTour = await page.getAttribute("[data-testid=tour]", "data-tour-id", { timeout: 3000 }).catch(() => null);
  check("tour", "home page tour follows the main tour", homeTour === "page-inventory", String(homeTour));
  if (homeTour) await page.click("[data-testid=tour-skip]");
  await page.goto(`${BASE}/app/reorder`);
  await page.waitForSelector("[data-testid=tour][data-tour-id=page-reorder]", { timeout: 10000 });
  check("tour", "page tour on first visit", true);
  for (let i = 0; i < 10; i++) {
    const label = (await page.textContent("[data-testid=tour-next]")).trim();
    await page.click("[data-testid=tour-next]");
    if (label === "متوجه شدم") break;
  }
  await page.waitForSelector("[data-testid=tour]", { state: "detached" });
  const state = await page.evaluate(async () => (await (await fetch("/users/me", { headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` } })).json()).tour_state);
  check("tour", "state saved on server", state["main-manager"] === "skipped" && state["page-reorder"] === "done", JSON.stringify(state));
  // دوباره دیدن از منوی کاربر
  await page.click("[data-testid=user-menu]");
  await page.click("[data-testid=menu-tour]");
  await page.waitForSelector("[data-testid=tour][data-tour-id=main-manager]");
  check("tour", "replay from user menu", true);
  await page.keyboard.press("Escape");
  await page.waitForSelector("[data-testid=tour]", { state: "detached" });
}, { tours: true, viewport: { width: 1440, height: 900 } });

// ---------------- مسیرهای قدیمی و ورود ناموفق ----------------
await session("public", null, null, async page => {
  await page.goto(`${BASE}/dashboard`);
  await page.waitForURL(/\/app\/login$/);
  check("public", "old /dashboard → new login", true);
  await page.goto(`${BASE}/legacy/driver`);
  await page.waitForURL(/\/app\/(login|driver)$/);
  check("public", "old /legacy/* → new app", true);
  await page.goto(`${BASE}/app/login`);
  await page.fill("#username", "admin");
  await page.fill("#password", "wrong-password");
  await page.click("button[type=submit]");
  await page.waitForSelector("[data-testid=login-error]");
  check("public", "wrong password shows error", true);
});

await browser.close();
const failures = results.filter(r => !r.ok);
const failed = failures.length;
console.log(`\n${results.length - failed}/${results.length} checks passed`);
if (CI && process.env.GITHUB_STEP_SUMMARY) {
  const cell = text => String(text || "").replace(/\|/g, "\\|").replace(/\s+/g, " ").slice(0, 300);
  appendFileSync(process.env.GITHUB_STEP_SUMMARY, [
    `### ${failed ? "❌" : "✅"} E2E: ${results.length - failed}/${results.length} checks passed`, "",
    ...(failed ? ["| Session | Check | Detail |", "|---|---|---|", ...failures.map(f => `| ${f.scope} | ${cell(f.label)} | ${cell(f.detail)} |`), ""] : []),
  ].join("\n") + "\n");
}
process.exit(failed ? 1 : 0);
