# FinalWhistle Logo Rebrand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the real FinalWhistle hexagon-whistle logo across the app (header, footer, favicon, OG share images, and all PWA/native icons), recolored to the app green, and clear the safe-to-remove legacy "PitchProphet" references.

**Architecture:** A single `Logo.tsx` component owns the in-app mark + two-tone wordmark (currentColor-driven, theme-safe). Static brand SVGs and a `sharp`-based generation script produce the favicon and all raster icon/splash assets from one source path; `@capacitor/assets` fans the masters out to iOS/Android. OG images embed the mark as an inline data-URI image (Satori-compatible).

**Tech Stack:** Next.js 14 (App Router), React 18, Tailwind (CSS-variable color tokens), `next/og` (Satori), Jest + React Testing Library, `sharp`, `@capacitor/assets` v3.

**Branch:** `rebrand/finalwhistle-logo` (already created; spec committed).

**Source of truth (mark path data, reused verbatim throughout):**
- Hexagon: `M46 0h80l46 78-46 78H46L0 78 46 0Z` (viewBox `0 0 172 156`, stroke-width 9, round joins)
- Whistle body: `M40 70c-20.4 0-37-15.4-37-34.4C3 16.6 19.6 1.2 40 1.2c13.5 0 25.3 6.8 31.7 17h37.7c8.1 0 14.6 6.3 14.6 14.1v23.9H91.5V40.1H76.4C74 57 58.6 70 40 70Z`
- Whistle top loop: `M111.5 19h27.8c8 0 14.5 6.3 14.5 14.1v13.2h-29.9v-14c0-7.3-5.4-13.3-12.4-13.3Z`
- Mouthpiece cut-out: `M87.8 29h24.6c2.3 0 4.2 1.8 4.2 4v12.6H87.8V29Z`
- Pea hole: circle `cx=39.6 cy=35.6 r=10.2`
- Whistle group offset: `translate(36 44)`
- Colors: lime `#9ee633`, brand dark `#08120d`

---

## Phase A — Core brand (web-facing)

### Task 1: Logo component (`BrandMark` + `Wordmark`)

The in-app mark is a single-color silhouette (no dark cut-outs) so it inherits `currentColor` and works on any surface. Cut-outs are only used in the on-dark static/raster assets (later tasks).

**Files:**
- Create: `frontend/components/Logo.tsx`
- Test: `frontend/components/__tests__/logo.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/components/__tests__/logo.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { BrandMark, Wordmark } from "@/components/Logo";

describe("Logo", () => {
  it("Wordmark renders the FinalWhistle two-tone split", () => {
    render(<Wordmark />);
    expect(screen.getByText("Final")).toBeInTheDocument();
    expect(screen.getByText("Whistle")).toBeInTheDocument();
  });

  it("BrandMark renders a decorative, sizable svg", () => {
    const { container } = render(<BrandMark className="h-7 text-win" />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveClass("h-7");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- logo`
Expected: FAIL — cannot resolve `@/components/Logo`.

- [ ] **Step 3: Write the component**

Create `frontend/components/Logo.tsx`:

```tsx
import { cn } from "@/lib/utils";

/** The FinalWhistle hexagon-whistle mark. Single-color: inherits `currentColor`
 *  (set color with a `text-*` utility). Decorative by default — give the parent
 *  (e.g. the nav link) the accessible name. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 172 156" fill="none" className={className} aria-hidden="true">
      <path
        d="M46 0h80l46 78-46 78H46L0 78 46 0Z"
        fill="none"
        stroke="currentColor"
        strokeWidth={9}
        strokeLinejoin="round"
      />
      <g transform="translate(36 44)" fill="currentColor">
        <path d="M40 70c-20.4 0-37-15.4-37-34.4C3 16.6 19.6 1.2 40 1.2c13.5 0 25.3 6.8 31.7 17h37.7c8.1 0 14.6 6.3 14.6 14.1v23.9H91.5V40.1H76.4C74 57 58.6 70 40 70Z" />
        <path d="M111.5 19h27.8c8 0 14.5 6.3 14.5 14.1v13.2h-29.9v-14c0-7.3-5.4-13.3-12.4-13.3Z" />
      </g>
    </svg>
  );
}

/** FinalWhistle wordmark with the brand two-tone split: "Final" in the
 *  foreground color, "Whistle" in lime. Mirrors APP_NAME ("FinalWhistle"). */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("font-display tracking-tight", className)}>
      <span className="text-foreground">Final</span>
      <span className="text-win">Whistle</span>
    </span>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- logo`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/components/Logo.tsx frontend/components/__tests__/logo.test.tsx
git commit -m "feat(brand): add FinalWhistle Logo component (mark + two-tone wordmark)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Wire the logo into the site header

Replace the placeholder star + single-color name with the mark and two-tone wordmark. Drop the tinted chip (the hexagon is its own container) and add an accessible name to the home link.

**Files:**
- Modify: `frontend/components/SiteNav.tsx`

- [ ] **Step 1: Add the import and remove the now-unused APP_NAME import**

In `frontend/components/SiteNav.tsx`, delete this line:

```tsx
import { APP_NAME } from "@/lib/constants";
```

and add:

```tsx
import { BrandMark, Wordmark } from "@/components/Logo";
```

- [ ] **Step 2: Replace the logo link contents**

Replace this block (the `<Link href="/">` opening tag through its closing `</Link>`, currently lines ~29–42):

```tsx
        <Link
          href="/"
          onClick={() => setOpen(false)}
          className="group flex shrink-0 items-center gap-2.5"
        >
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-win/15 text-win ring-1 ring-win/30 transition group-hover:bg-win/25">
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
              <path d="M12 2l3 6 6 .8-4.5 4.2 1.2 6L12 17l-5.9 2 1.2-6L3 8.8 9 8z" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="font-display text-lg font-extrabold tracking-tight">
            {APP_NAME}
          </span>
        </Link>
```

with:

```tsx
        <Link
          href="/"
          onClick={() => setOpen(false)}
          aria-label="FinalWhistle home"
          className="group flex shrink-0 items-center gap-2.5"
        >
          <BrandMark className="h-7 w-auto shrink-0 text-win transition group-hover:opacity-90" />
          <Wordmark className="text-lg font-extrabold" />
        </Link>
```

- [ ] **Step 3: Verify types and lint pass**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors (in particular, no "APP_NAME is defined but never used").

- [ ] **Step 4: Commit**

```bash
git add frontend/components/SiteNav.tsx
git commit -m "feat(brand): use FinalWhistle mark + two-tone wordmark in site header

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Two-tone wordmark in the footer

**Files:**
- Modify: `frontend/app/layout.tsx`

- [ ] **Step 1: Add the import**

In `frontend/app/layout.tsx`, add:

```tsx
import { Wordmark } from "@/components/Logo";
```

(Keep the existing `import { APP_NAME, SITE_URL } from "@/lib/constants";` — `APP_NAME` is still used in `metadata`.)

- [ ] **Step 2: Replace the footer brand span**

Replace this line (currently ~line 82):

```tsx
            <span className="font-display font-bold text-muted">{APP_NAME}</span>{" "}
```

with:

```tsx
            <Wordmark className="font-bold" />{" "}
```

- [ ] **Step 3: Verify types pass**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/layout.tsx
git commit -m "feat(brand): two-tone FinalWhistle wordmark in footer

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Vector favicon

Add a self-contained mark-on-dark-tile SVG and make it the primary favicon, keeping the PNGs as fallbacks.

**Files:**
- Create: `frontend/public/icon.svg`
- Modify: `frontend/app/layout.tsx` (`metadata.icons.icon`)

- [ ] **Step 1: Create the favicon SVG**

Create `frontend/public/icon.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="FinalWhistle">
  <rect width="512" height="512" rx="112" fill="#08120d"/>
  <g transform="translate(256 256) scale(2) translate(-86 -78)">
    <path d="M46 0h80l46 78-46 78H46L0 78 46 0Z" fill="none" stroke="#9ee633" stroke-width="9" stroke-linejoin="round"/>
    <g transform="translate(36 44)">
      <path fill="#9ee633" d="M40 70c-20.4 0-37-15.4-37-34.4C3 16.6 19.6 1.2 40 1.2c13.5 0 25.3 6.8 31.7 17h37.7c8.1 0 14.6 6.3 14.6 14.1v23.9H91.5V40.1H76.4C74 57 58.6 70 40 70Z"/>
      <path fill="#08120d" d="M87.8 29h24.6c2.3 0 4.2 1.8 4.2 4v12.6H87.8V29Z"/>
      <circle cx="39.6" cy="35.6" r="10.2" fill="#08120d"/>
      <path fill="#9ee633" d="M111.5 19h27.8c8 0 14.5 6.3 14.5 14.1v13.2h-29.9v-14c0-7.3-5.4-13.3-12.4-13.3Z"/>
    </g>
  </g>
</svg>
```

- [ ] **Step 2: Reference it first in metadata**

In `frontend/app/layout.tsx`, change the `icons.icon` array (currently lines ~41–44) from:

```tsx
    icon: [
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
```

to:

```tsx
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
```

- [ ] **Step 3: Verify types pass**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/public/icon.svg frontend/app/layout.tsx
git commit -m "feat(brand): add vector favicon (icon.svg) as primary icon

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Replace the "F" mark in OG share images

The OG `Shell` is Satori (flexbox CSS subset only). Embed the mark as an inline `data:image/svg+xml` `<img>` (URL-encoded — works in the default Node runtime). Color matches the existing OG palette, so no other OG change is needed; this propagates to root/match/team/group OG routes via `Shell`.

**Files:**
- Modify: `frontend/lib/og.tsx`

- [ ] **Step 1: Add the mark data-URI constant**

In `frontend/lib/og.tsx`, after the `C` color object (after line ~19), add:

```tsx
/** The FinalWhistle mark as an inline SVG data-URI. next/og (Satori) renders
 *  <img> data-URIs reliably; raw inline <svg> support is partial, so we embed. */
const MARK_DATA_URI =
  "data:image/svg+xml," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 172 156"><path d="M46 0h80l46 78-46 78H46L0 78 46 0Z" fill="none" stroke="${C.win}" stroke-width="9" stroke-linejoin="round"/><g transform="translate(36 44)"><path fill="${C.win}" d="M40 70c-20.4 0-37-15.4-37-34.4C3 16.6 19.6 1.2 40 1.2c13.5 0 25.3 6.8 31.7 17h37.7c8.1 0 14.6 6.3 14.6 14.1v23.9H91.5V40.1H76.4C74 57 58.6 70 40 70Z"/><path fill="${C.bg}" d="M87.8 29h24.6c2.3 0 4.2 1.8 4.2 4v12.6H87.8V29Z"/><circle cx="39.6" cy="35.6" r="10.2" fill="${C.bg}"/><path fill="${C.win}" d="M111.5 19h27.8c8 0 14.5 6.3 14.5 14.1v13.2h-29.9v-14c0-7.3-5.4-13.3-12.4-13.3Z"/></g></svg>`,
  );
```

- [ ] **Step 2: Replace the "F" box**

In the `Shell` component, replace the `<div>` that renders the letter `F` (currently lines ~38–47):

```tsx
          <div
            style={{
              width: 46, height: 46, borderRadius: 12,
              background: "rgba(158,230,51,0.15)", border: "1px solid rgba(158,230,51,0.35)",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: C.win, fontSize: 28, fontWeight: 800,
            }}
          >
            F
          </div>
```

with:

```tsx
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={MARK_DATA_URI} width={48} height={44} alt="" style={{ display: "flex" }} />
```

- [ ] **Step 3: Verify types and build the OG route**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

Then verify the route renders (Step 4 of Task 6 covers the live image check).

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/og.tsx
git commit -m "feat(brand): render FinalWhistle mark (not letter F) in OG images

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Browser verification checkpoint (Phase A)

No code changes — confirm the web-facing rebrand renders correctly before moving to raster assets.

- [ ] **Step 1: Start the dev server**

Use `preview_start` (or `cd frontend && npm run dev`). The app expects the API at `NEXT_PUBLIC_API_URL`; for visual checks the header/footer/favicon do not need the backend.

- [ ] **Step 2: Check the header (desktop)**

Load `/`, `preview_snapshot` + `preview_screenshot`. Confirm: hexagon-whistle mark in lime, "Final" white + "Whistle" lime, no leftover star, no console errors (`preview_console_logs`).

- [ ] **Step 3: Check the header (mobile + menu)**

`preview_resize` to ~390px wide, screenshot, then `preview_click` the hamburger and screenshot the open menu.

- [ ] **Step 4: Check favicon + OG**

Navigate to `/icon.svg` (expect the tile mark) and `/opengraph-image` (expect a 1200×630 PNG with the mark in the header, not an "F"). Use `preview_network` to confirm `/opengraph-image` returns `200` with `content-type: image/png`.

- [ ] **Step 5: No commit** (verification only). If issues are found, fix the relevant source file and re-verify.

---

## Phase B — Raster & native icons

### Task 7: Generate raster brand assets from the mark

One script renders every PNG from the mark: the `@capacitor/assets` master sources in `assets/`, plus the web/PWA icons in `public/`.

**Files:**
- Modify: `frontend/package.json` (add `sharp` devDependency — see step)
- Create: `frontend/scripts/generate-brand-assets.mjs`
- Regenerate (overwrite): `frontend/assets/{icon-only,icon-foreground,icon-background,splash,splash-dark}.png`, `frontend/public/{icon-192,icon-512,icon-maskable-192,icon-maskable-512,apple-icon-180}.png`

- [ ] **Step 1: Add `sharp`**

Run: `cd frontend && npm install --save-dev sharp`
Expected: `sharp` added to `devDependencies` (dedupes with the copy `@capacitor/assets` already pulls in).

- [ ] **Step 2: Write the generation script**

Create `frontend/scripts/generate-brand-assets.mjs`:

```js
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
```

- [ ] **Step 3: Run the script**

Run: `cd frontend && node scripts/generate-brand-assets.mjs`
Expected: prints `wrote …` for all 10 files, then `done — regenerated 10 assets`.

- [ ] **Step 4: Visually verify the output**

Open `frontend/public/icon-512.png` and `frontend/public/icon-maskable-512.png` (Read tool renders images). Confirm: lime mark centered on the brand-dark tile; maskable variant has noticeably more padding (mark within the safe zone). Confirm `frontend/assets/icon-background.png` is a solid dark square.

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/scripts/generate-brand-assets.mjs frontend/assets frontend/public/icon-192.png frontend/public/icon-512.png frontend/public/icon-maskable-192.png frontend/public/icon-maskable-512.png frontend/public/apple-icon-180.png
git commit -m "feat(brand): regenerate PWA/web icons + splash from the new mark

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Regenerate native iOS/Android assets

Fan the new masters out to the native projects with `@capacitor/assets`.

**Files:**
- Regenerate: `frontend/ios/App/App/Assets.xcassets/**`, `frontend/android/app/src/main/res/**`

- [ ] **Step 1: Run the generator**

Run:

```bash
cd frontend && npx capacitor-assets generate \
  --assetPath assets \
  --iconBackgroundColor '#08120d' \
  --iconBackgroundColorDark '#08120d' \
  --splashBackgroundColor '#08120d' \
  --splashBackgroundColorDark '#08120d'
```

Expected: it reports generating iOS and Android icon/splash assets from `assets/`.

- [ ] **Step 2: Confirm what changed**

Run: `cd frontend && git status --short ios android | head -40`
Expected: modified PNGs under `ios/App/App/Assets.xcassets/` and `android/app/src/main/res/`.

Spot-check one icon image (e.g. `frontend/ios/App/App/Assets.xcassets/AppIcon.appiconset/AppIcon-512@2x.png`) with the Read tool — it should show the new mark.

- [ ] **Step 3 (fallback, only if Step 1 fails):** If `capacitor-assets` cannot run here (missing native platform, sharp/platform error), record exactly which native sets were not regenerated and proceed. The web/PWA icons from Task 7 already cover browser + installed-PWA usage; native iOS/Android regeneration can be re-run later from the committed masters with the same command. Do **not** hand-edit native PNGs.

- [ ] **Step 4: Commit**

```bash
git add frontend/ios frontend/android
git commit -m "feat(brand): regenerate native iOS/Android icons + splash

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Phase C — Legacy cleanup (safe scope)

### Task 9: Remove safe-to-change PitchProphet references

Only the cosmetic npm package name and one genuinely-stale doc URL change. The `pitchprophet-api.onrender.com` / `pitchprophet-db` strings are the **live backend host/DB** and stay.

**Files:**
- Modify: `frontend/package.json`, `frontend/package-lock.json`, `DEPLOYMENT.md`, `render.yaml`

- [ ] **Step 1: Rename the npm package**

In `frontend/package.json`, change line 2:

```json
  "name": "finalwhistle-frontend",
```

In `frontend/package-lock.json`, change the two `"name": "pitchprophet-frontend"` occurrences (the top-level `name` and the `packages[""].name`, lines ~2 and ~8) to:

```json
  "name": "finalwhistle-frontend",
```

- [ ] **Step 2: Fix the stale frontend URL in docs**

In `DEPLOYMENT.md`, replace both occurrences of `https://pitchprophet.vercel.app` (lines ~21 and ~137) with `https://fifa-wc26-prediction.vercel.app`. Leave every `pitchprophet-api.onrender.com` and `pitchprophet-db` reference unchanged — those describe the real Render infrastructure.

- [ ] **Step 3: Annotate render.yaml**

In `render.yaml`, add a comment on the line above the first service `name:` (line ~6):

```yaml
  # NOTE: pitchprophet-* service/DB names are legacy but load-bearing — they map
  # to live Render resources and the production API host. Do not rename.
```

- [ ] **Step 4: Verify nothing broke**

Run: `cd frontend && npm run typecheck && npm test`
Expected: typecheck clean; full Jest suite green (the package rename does not affect runtime).

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json DEPLOYMENT.md render.yaml
git commit -m "chore(brand): rename frontend package; fix stale Vercel URL; annotate render.yaml

Keeps live Render host/DB names (pitchprophet-api/-db) intact.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Phase D — Final verification

### Task 10: Full suite + visual proof

- [ ] **Step 1: Run the whole frontend gate**

Run: `cd frontend && npm test && npm run typecheck && npm run lint`
Expected: all green.

- [ ] **Step 2: Capture final visual proof**

With the dev server running: screenshot the header (desktop + mobile menu open), `/icon.svg`, and `/opengraph-image`. Confirm the mark + two-tone wordmark everywhere and no console errors.

- [ ] **Step 3: Summarize**

Report: files changed, which native asset sets were regenerated (or deferred per Task 8 Step 3), and the verification evidence. Branch `rebrand/finalwhistle-logo` is ready for a PR (creating the PR is a separate, user-initiated step).

---

## Self-review

**Spec coverage:**
- §1 Canonical logo, vendored & recolored → Task 1 (component) + Task 4 (`public/icon.svg`) + Task 7 (`assets`/`public` masters). Note: the spec mentioned a `public/logo.svg` full lockup; the in-app lockup is delivered as the `Wordmark` + `BrandMark` components (Tasks 1–3) and the OG lockup (Task 5), so a separate static `logo.svg` is not required and is intentionally omitted (YAGNI). ✅
- §2 Header & footer → Tasks 2, 3. ✅
- §3 OG images → Task 5. ✅
- §4 Raster/favicon/native → Tasks 4, 7, 8. ✅
- §5 Cleanup (narrowed) → Task 9. ✅
- §6 Testing & verification → Task 1 (unit), Tasks 6 & 10 (browser + suite). ✅

**Placeholder scan:** No TBD/TODO; every code step has complete code and exact commands. ✅

**Type/name consistency:** `BrandMark`/`Wordmark` signatures (`{ className?: string }`) are identical across Tasks 1–3 and 5; mark path data is identical across Tasks 1, 4, 5, 7; colors (`#9ee633`/`#08120d`) consistent. ✅

> Note on the omitted `public/logo.svg`: if an external/static full-lockup file is later needed (e.g. for a press kit), it can be added trivially, but no task in this plan consumes it, so it's left out to avoid an unused asset.
