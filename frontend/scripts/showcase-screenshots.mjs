/* GitHub README showcase generator (Daylight redesign).
 *
 * Captures production at desktop framing using the system Chrome
 * (playwright-core channel:"chrome" — no browser download). Animations are
 * frozen and first-run banners suppressed so captures are deterministic.
 *
 *   node scripts/showcase-screenshots.mjs [baseUrl]
 *
 * Output: ../.github/assets/
 *   matches.png / groups.png / brackets.png   1440-wide hero
 *   match-detail.png                                           full-page column
 */
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const BASE = process.argv[2] ?? "https://fifa-wc26-prediction.vercel.app";
const ONLY = process.argv[3]; // optional scene-slug filter, e.g. "match-detail"
const OUT = resolve(import.meta.dirname, "../../.github/assets");

const SCENES = [
  { slug: "matches", path: "/matches", mode: "hero", settle: 3000 },
  { slug: "groups", path: "/groups", mode: "hero", settle: 3000 },
  { slug: "brackets", path: "/brackets", mode: "hero", settle: 3500 },
  { slug: "match-detail", path: "/match/1", mode: "page", settle: 3000 },
];

// Hero shots: wide desktop frame, clipped to viewport. Detail: narrower full page.
const HERO = { width: 1440, height: 820 };
const PAGE = { width: 1180, height: 900 };
const DPR = 2;

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });

for (const scene of SCENES) {
  if (ONLY && scene.slug !== ONLY) continue;
  const size = scene.mode === "hero" ? HERO : PAGE;
  const ctx = await browser.newContext({
    viewport: { width: size.width, height: size.height },
    deviceScaleFactor: DPR,
  });
  // Suppress first-run UI that would clutter a marketing shot: the install
  // banner and the "confirm your time zone" prompt.
  await ctx.addInitScript(() => {
    try {
      localStorage.setItem("finalwhistle:install-prompt-dismissed:v1", "1");
      localStorage.setItem("pp:tz-confirmed", "1");
    } catch {}
  });
  const page = await ctx.newPage();
  await page.goto(BASE + scene.path, { waitUntil: "networkidle", timeout: 45000 });
  await page.addStyleTag({
    content: "*, *::before, *::after { animation: none !important; transition: none !important; }",
  });
  await page.waitForTimeout(scene.settle); // client fetches paint in
  if (scene.mode === "page") {
    // The feature-importance chart renders with isAnimationActive=false, so its
    // bars paint immediately. Just wait until they actually have width before
    // capturing (belt-and-braces against any ResponsiveContainer measure lag).
    await page
      .waitForFunction(() => {
        const r = document.querySelectorAll(".recharts-bar-rectangle path, .recharts-bar-rectangle rect");
        return r.length > 0 && [...r].some((el) => el.getBoundingClientRect().width > 2);
      }, { timeout: 8000 })
      .catch(() => {});
    await page.waitForTimeout(300);
  }
  const file = `${OUT}/${scene.slug}.png`;
  await page.screenshot({ path: file, fullPage: scene.mode === "page" });
  console.log("wrote", file);
  await ctx.close();
}

await browser.close();
console.log("done");
