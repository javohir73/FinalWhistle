# FinalWhistle logo rebrand — design

**Date:** 2026-06-15
**Status:** Approved (design)
**Author:** pete@degail.com (with Claude)

## Summary

The app is already named **FinalWhistle** end-to-end (frontend, backend, PWA
manifest, metadata) and already uses the logo's color family (lime accent on a
near-black green canvas). What is missing is the **actual logo mark** — the
hexagon-whistle symbol — which has never been implemented. The current in-app
header shows a generic placeholder star, and the OG share images use a literal
letter "F".

This project implements the real logo across the product and clears the last
legacy "PitchProphet" references from code and docs.

### Source of truth

The provided vector `finalwhistle-logo-on-dark.svg` is the canonical logo. Key
properties from the file:

- Flat-top hexagon outline: path `M46 0h80l46 78-46 78H46L0 78 46 0Z`,
  `stroke-width` 9, rounded joins.
- Whistle (chamber + mouthpiece-to-the-right + top lanyard loop + pea hole),
  drawn as filled paths with dark cut-outs.
- Logo lime: `#b6ef45`. White: `#f5f7f2`. Dark bg: `#030706`.
- Wordmark font in the file: `Inter/Satoshi`, weight 800.

## Resolved decisions

1. **Brand green:** recolor the logo from `#b6ef45` → **`#9ee633`** (the app's
   existing `--win`/`--accent`). The UI color system is unchanged; the logo
   adopts the app green.
2. **Header treatment:** mark + **two-tone wordmark** (`Final` in foreground
   color, `Whistle` in lime), rendered as live text.
3. **Wordmark font:** keep **Bricolage Grotesque** (the app's display font). No
   new font is loaded.
4. **Cleanup scope:** code & docs only. Do **not** rename live Render infra in
   `render.yaml`.

## Design

### 1. Canonical logo, vendored & recolored

The logo is vendored into the repo so nothing depends on an external path.

- `frontend/components/Logo.tsx` (new) — exports:
  - `<BrandMark>` — the icon-only inline SVG (hexagon + whistle). Color comes
    from `currentColor` / the `text-win` utility so it inherits theme and can be
    sized via `className`. Dark cut-outs use `currentColor` against a
    transparent background where possible, or the surrounding surface color.
  - `<Logo>` — the full lockup: `<BrandMark>` + two-tone wordmark. Props for
    size and whether to show the wordmark.
- `frontend/public/logo.svg` (new) — the full lockup recolored to `#9ee633`,
  for any external/static reference.

The mark's path data is copied verbatim from the source file; only the fill /
stroke colors change to `#9ee633`.

### 2. In-app header & footer

- `frontend/components/SiteNav.tsx` (lines 34–41): replace the placeholder star
  `<svg>` with `<BrandMark>` inside the existing rounded chip. Render the
  wordmark two-tone — `Final` in `text-foreground`, `Whistle` in `text-win` —
  keeping the `font-display` (Bricolage Grotesque) styling. Add
  `aria-label="FinalWhistle home"` to the link for an accessible name.
- `frontend/app/layout.tsx` (footer, line 82): render the wordmark two-tone for
  consistency with the header.

### 3. OG / social share images

- `frontend/lib/og.tsx` (lines 38–48): replace the literal "F" box in `Shell`
  with the hexagon-whistle mark. Because next/og (Satori) supports only a
  flexbox CSS subset, the mark is embedded as an inline SVG **data-URI `<img>`**
  rather than raw SVG elements. Color `#9ee633` (already the OG `win` color, so
  no palette change). The wordmark text is unchanged.
- This propagates automatically to every OG route that uses `Shell`: root,
  `match/[id]`, `team/[id]`, `groups/[id]`.

### 4. Raster assets — icons, favicon, splash, native

- `frontend/app/icon.svg` (new) — the mark, so the browser favicon is crisp and
  vector. Keep the existing PNG entries in `layout.tsx` `metadata.icons` as
  fallbacks for older clients.
- Rebuild the master source images in `frontend/assets/`
  (`icon-only`, `icon-foreground`, `icon-background`, `splash`, `splash-dark`)
  from the new mark, then run **`@capacitor/assets generate`** to propagate to:
  - `frontend/public/icon-192.png`, `icon-512.png`,
    `icon-maskable-192.png`, `icon-maskable-512.png`, `apple-icon-180.png`
  - `frontend/ios/App/App/Assets.xcassets/**` (AppIcon + Splash)
  - `frontend/android/app/src/main/res/**` (mipmaps + splash drawables)

**Dependency check (implementation-time):** this requires `sharp` /
`@capacitor/assets` to be installable in the environment. If the generator
cannot run here, fall back to rendering the master PNGs from the SVG with a
small headless/`sharp` script and **explicitly report** which native asset sets
were and were not regenerated — no silent coverage gaps.

### 5. PitchProphet cleanup (code & docs, not live infra)

**Critical nuance:** most `pitchprophet` references are the **live backend's real
hostname** (`pitchprophet-api.onrender.com`) and DB name (`pitchprophet-db`),
derived from the Render service names we are deliberately keeping. Changing those
strings would break the production API fallback. So the safe cleanup is narrow.

Rename / fix:
- `frontend/package.json` — `pitchprophet-frontend` → `finalwhistle-frontend`
  (private package identifier; cosmetic, no infra impact). Update the matching
  `name` fields in `frontend/package-lock.json`.
- `DEPLOYMENT.md` — fix the **stale frontend URL** `https://pitchprophet.vercel.app`
  → `https://fifa-wc26-prediction.vercel.app` (lines 21, 137). This is a real
  documentation error (wrong Vercel URL), not infra.
- `render.yaml` — add a one-line comment noting the `pitchprophet-*` service
  names are legacy but load-bearing (names themselves unchanged).

Leave untouched (all tied to live infra or historical record):
- `frontend/app/sitemap.ts:4`, `tools/admin_dashboard.py:28` — the
  `pitchprophet-api.onrender.com` fallback is the real production API host.
- `.github/workflows/keep-warm.yml`, `smoke.yml` — ping the real host.
- `render.yaml` service/DB names (`pitchprophet-db` / `pitchprophet-api`).
- The `pitchprophet-api.onrender.com` / `pitchprophet-db` operational references
  inside `DEPLOYMENT.md` (accurate infra instructions).
- Dated historical `prd-*.md` / `tasks-*.md` files.

### 6. Testing & verification

- Add a focused test for `Logo` / `BrandMark`: renders without error and exposes
  an accessible name in the header link.
- Confirm existing branding-related tests still pass (e.g.
  `InstallAppPrompt`, manifest/metadata tests).
- Run the dev server and capture proof: header on desktop and mobile (with the
  hamburger menu open), the favicon, and at least one OG route render. Confirm
  no new console errors.

## Out of scope

- `store-assets/` App Store / Play Store screenshots (marketing collateral —
  separate task).
- Any change to the app's color system beyond recoloring the logo.
- Renaming live Render infrastructure.

## Affected files (reference)

| File | Change |
|------|--------|
| `frontend/components/Logo.tsx` | New — `<BrandMark>` + `<Logo>` |
| `frontend/public/logo.svg` | New — full lockup, recolored |
| `frontend/app/icon.svg` | New — favicon mark |
| `frontend/components/SiteNav.tsx` | Star → mark; two-tone wordmark; aria-label |
| `frontend/app/layout.tsx` | Footer two-tone wordmark |
| `frontend/lib/og.tsx` | "F" box → mark (data-URI img) |
| `frontend/assets/*` | New master sources for icon/splash |
| `frontend/public/icon-*.png`, `apple-icon-180.png` | Regenerated |
| `frontend/ios/**`, `frontend/android/**` | Regenerated native assets |
| `frontend/package.json` + `package-lock.json` | Rename to `finalwhistle-frontend` |
| `DEPLOYMENT.md` | Fix stale `pitchprophet.vercel.app` → real Vercel URL |
| `render.yaml` | Comment only (names untouched) |
| `frontend/app/sitemap.ts`, `tools/admin_dashboard.py`, workflows | **Unchanged** — live API host |
