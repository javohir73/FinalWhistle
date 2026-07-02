/* QA route sweep — console/pageerror/network health across every route at
 * desktop + mobile. Auto-discovers real dynamic ids from listing pages.
 *
 *   node scripts/qa-sweep.mjs [baseUrl]
 *
 * Reports, per (route × viewport): console errors, uncaught page errors,
 * failed (>=400) responses, and whether the app error boundary showed.
 */
import { chromium } from "playwright-core";

const BASE = process.argv[2] ?? "https://fifa-wc26-prediction.vercel.app";

// Noise we never want to flag as a real error.
const IGNORE = [
  /Download the React DevTools/i,
  /Vercel Web Analytics/i,
  /\[Fast Refresh\]/i,
  /favicon/i,
];
const isNoise = (t) => IGNORE.some((re) => re.test(t || ""));

const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 800, mobile: false },
  { name: "mobile", width: 390, height: 844, mobile: true },
];

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page0 = await (await browser.newContext()).newPage();

// Discover one real id for each dynamic route from the listing pages.
async function firstHref(path, re) {
  await page0.goto(BASE + path, { waitUntil: "networkidle", timeout: 45000 }).catch(() => {});
  await page0.waitForTimeout(2500);
  const hrefs = await page0.$$eval("a[href]", (as) => as.map((a) => a.getAttribute("href")));
  const m = hrefs.map((h) => (h || "").match(re)).find(Boolean);
  return m ? m[0] : null;
}
const matchPath = (await firstHref("/matches", /^\/match\/[^/]+$/)) ?? "/match/1";
const groupPath = (await firstHref("/groups", /^\/groups\/[^/]+$/)) ?? "/groups/1";
const teamPath = (await firstHref(matchPath, /^\/team\/[^/]+$/)) ?? "/team/1";

const ROUTES = [
  "/", "/matches", matchPath, "/groups", groupPath, "/brackets",
  "/leaderboard", teamPath, "/methodology",
  "/about", "/privacy", "/terms",
];

const results = [];
for (const vp of VIEWPORTS) {
  const ctx = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
    deviceScaleFactor: vp.mobile ? 3 : 1,
    isMobile: vp.mobile,
    hasTouch: vp.mobile,
  });
  for (const route of ROUTES) {
    const page = await ctx.newPage();
    const consoleErrors = [];
    const pageErrors = [];
    const badResponses = [];
    page.on("console", (m) => { if (m.type() === "error" && !isNoise(m.text())) consoleErrors.push(m.text().slice(0, 160)); });
    page.on("pageerror", (e) => { if (!isNoise(String(e))) pageErrors.push(String(e).slice(0, 160)); });
    page.on("response", (r) => { if (r.status() >= 400 && !/favicon|\.map$/.test(r.url())) badResponses.push(`${r.status()} ${r.url().replace(BASE, "").slice(0, 80)}`); });
    let errored = false, title = "";
    try {
      await page.goto(BASE + route, { waitUntil: "networkidle", timeout: 45000 });
      await page.waitForTimeout(2500);
      title = await page.title();
      // App error boundary / Next error page heuristics.
      errored = await page.evaluate(() => {
        const t = document.body.innerText || "";
        return /Application error|Something went wrong|This page could not be found|500|Internal Server Error/i.test(t) && t.length < 600;
      });
    } catch (e) {
      pageErrors.push("NAV_FAIL: " + String(e).slice(0, 100));
    }
    results.push({
      vp: vp.name, route, title: title.slice(0, 40),
      errorBoundary: errored,
      consoleErrors: [...new Set(consoleErrors)],
      pageErrors: [...new Set(pageErrors)],
      badResponses: [...new Set(badResponses)].slice(0, 6),
    });
    await page.close();
  }
  await ctx.close();
}

await browser.close();

// Print a compact report.
let clean = 0;
for (const r of results) {
  const issues = r.consoleErrors.length + r.pageErrors.length + r.badResponses.length + (r.errorBoundary ? 1 : 0);
  if (issues === 0) { clean++; console.log(`OK   [${r.vp}] ${r.route}  "${r.title}"`); continue; }
  console.log(`FAIL [${r.vp}] ${r.route}  "${r.title}"${r.errorBoundary ? "  <ERROR-BOUNDARY>" : ""}`);
  for (const e of r.pageErrors) console.log(`       pageerror: ${e}`);
  for (const e of r.consoleErrors) console.log(`       console:   ${e}`);
  for (const e of r.badResponses) console.log(`       net:       ${e}`);
}
console.log(`\n${clean}/${results.length} route×viewport combos clean`);
