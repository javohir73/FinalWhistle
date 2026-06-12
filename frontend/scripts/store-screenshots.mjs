/* Store screenshot generator (App Store 6.7" + Play Store phone).
 *
 * Captures production at device-accurate viewports using the system Chrome
 * (playwright-core channel:"chrome" — no browser download). Animations are
 * frozen so captures are deterministic.
 *
 *   node scripts/store-screenshots.mjs [baseUrl]
 *
 * Output: ../store-assets/
 *   appstore-67-*.png  1290×2796 (430×932 @3x — iPhone 6.7")
 *   play-phone-*.png   1080×2340 (360×780 @3x)
 */
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const BASE = process.argv[2] ?? "https://fifa-wc26-prediction.vercel.app";
const OUT = resolve(import.meta.dirname, "../../store-assets");

const SCENES = [
  { slug: "01-home", path: "/", settle: 2500 },
  { slug: "02-matches", path: "/matches", settle: 3000 },
  { slug: "03-my-bracket", path: "/my-bracket", settle: 3000 },
  { slug: "04-leaderboard", path: "/leaderboard", settle: 2500 },
];

const SIZES = [
  { prefix: "appstore-67", width: 430, height: 932, dpr: 3 },
  { prefix: "play-phone", width: 360, height: 780, dpr: 3 },
];

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true });

for (const size of SIZES) {
  const ctx = await browser.newContext({
    viewport: { width: size.width, height: size.height },
    deviceScaleFactor: size.dpr,
    isMobile: true,
    hasTouch: true,
    userAgent:
      "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
  });
  for (const scene of SCENES) {
    const page = await ctx.newPage();
    await page.goto(BASE + scene.path, { waitUntil: "networkidle", timeout: 45000 });
    await page.addStyleTag({
      content: "*, *::before, *::after { animation: none !important; transition: none !important; }",
    });
    await page.waitForTimeout(scene.settle); // client fetches paint in
    const file = `${OUT}/${size.prefix}-${scene.slug}.png`;
    await page.screenshot({ path: file });
    console.log("wrote", file);
    await page.close();
  }
  await ctx.close();
}

await browser.close();
console.log("done");
