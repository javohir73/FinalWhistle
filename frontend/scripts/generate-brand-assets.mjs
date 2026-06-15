// Regenerates all raster brand assets from the FinalWhistle mark.
// Run: cd frontend && node scripts/generate-brand-assets.mjs
import sharp from "sharp";
import { mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const LIME = "#9ee633";
const BG = "#08120d";
const MARK_W = 172;
const MARK_H = 156;

const MARK = `
  <path d="M46 0h80l46 78-46 78H46L0 78 46 0Z" fill="none" stroke="${LIME}" stroke-width="9" stroke-linejoin="round"/>
  <g transform="translate(36 44)">
    <path fill="${LIME}" d="M40 70c-20.4 0-37-15.4-37-34.4C3 16.6 19.6 1.2 40 1.2c13.5 0 25.3 6.8 31.7 17h37.7c8.1 0 14.6 6.3 14.6 14.1v23.9H91.5V40.1H76.4C74 57 58.6 70 40 70Z"/>
    <path fill="${BG}" d="M87.8 29h24.6c2.3 0 4.2 1.8 4.2 4v12.6H87.8V29Z"/>
    <circle cx="39.6" cy="35.6" r="10.2" fill="${BG}"/>
    <path fill="${LIME}" d="M111.5 19h27.8c8 0 14.5 6.3 14.5 14.1v13.2h-29.9v-14c0-7.3-5.4-13.3-12.4-13.3Z"/>
  </g>`;

// `coverage` = fraction of the canvas the mark's longest side spans.
// `radius` = corner radius as a fraction of size (0 = square / full-bleed).
// `background` = tile color, or null for transparent.
function iconSvg({ size, coverage, background, radius = 0 }) {
  const scale = (size * coverage) / Math.max(MARK_W, MARK_H);
  const bg = background
    ? `<rect width="${size}" height="${size}" rx="${size * radius}" fill="${background}"/>`
    : "";
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">${bg}<g transform="translate(${size / 2} ${size / 2}) scale(${scale}) translate(${-MARK_W / 2} ${-MARK_H / 2})">${MARK}</g></svg>`;
}

async function png(svg, outPath, size) {
  const abs = join(ROOT, outPath);
  await mkdir(dirname(abs), { recursive: true });
  await sharp(Buffer.from(svg)).resize(size, size).png().toFile(abs);
  console.log("wrote", outPath);
}

const jobs = [
  // @capacitor/assets master sources.
  ["assets/icon-only.png", iconSvg({ size: 1024, coverage: 0.7, background: BG, radius: 0 }), 1024],
  ["assets/icon-foreground.png", iconSvg({ size: 1024, coverage: 0.5, background: null }), 1024],
  ["assets/icon-background.png", iconSvg({ size: 1024, coverage: 0, background: BG, radius: 0 }), 1024],
  ["assets/splash.png", iconSvg({ size: 2732, coverage: 0.28, background: BG, radius: 0 }), 2732],
  ["assets/splash-dark.png", iconSvg({ size: 2732, coverage: 0.28, background: BG, radius: 0 }), 2732],
  // Web / PWA icons.
  ["public/icon-192.png", iconSvg({ size: 192, coverage: 0.72, background: BG, radius: 0.22 }), 192],
  ["public/icon-512.png", iconSvg({ size: 512, coverage: 0.72, background: BG, radius: 0.22 }), 512],
  ["public/icon-maskable-192.png", iconSvg({ size: 192, coverage: 0.52, background: BG, radius: 0 }), 192],
  ["public/icon-maskable-512.png", iconSvg({ size: 512, coverage: 0.52, background: BG, radius: 0 }), 512],
  ["public/apple-icon-180.png", iconSvg({ size: 180, coverage: 0.72, background: BG, radius: 0 }), 180],
];

for (const [out, svg, size] of jobs) {
  await png(svg, out, size);
}
console.log("done — regenerated", jobs.length, "assets");
