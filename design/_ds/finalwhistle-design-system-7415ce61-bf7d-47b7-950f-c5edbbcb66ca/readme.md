# FinalWhistle Design System

**FinalWhistle** is an explainable-AI prediction platform for the FIFA World Cup 2026. Users follow their nation, see match win/draw/loss probabilities, build personal brackets, compare their picks with the AI model, and climb a public leaderboard — all without betting, wagering, or real-money play.

The product is a **Next.js PWA** installable on iOS and Android (also submitted to the App Store / Play Store via Capacitor), a **FastAPI backend**, and a Python ML pipeline (Elo ratings + Poisson goals model + Monte Carlo tournament simulation over 49 000 historical internationals).

---

## Sources

| Source | Access |
|---|---|
| GitHub repo | https://github.com/javohir73/fifa-wc26-prediction |
| Local codebase | `FIFA WC26 Prediction/` (mounted read-only) |
| Store screenshots | `store-assets/` in the repo (App Store 6.7" + Play Store) |
| App Store / Play Store listing | `docs/STORE-LISTING.md` in the repo |
| Product PRD | `tasks/prd-wc26-prediction-platform.md` |

The GitHub repo is public. Explore it further to get the most accurate picture of the codebase — the frontend lives in `frontend/` (Next.js + Tailwind), the ML pipeline in `pipeline/` and `ml/`.

---

## Content Fundamentals

**Voice & tone:** Confident, precise, and sports-commentator sharp. FinalWhistle sounds like an expert analyst who explains the numbers rather than hiding behind them. It never hedges with vague language, but always flags that predictions are probabilistic.

**Key phrases to copy:**
- "Every fixture by kickoff — win probabilities, scorelines, time, and venue."
- "Pick your nation. See what the AI thinks. Prove it wrong."
- "For analytics and entertainment only. Not betting advice."
- "Predictions are probabilistic and never guaranteed."

**Casing:**
- Headlines: sentence case always ("Match predictions", "Build your bracket")
- Labels / eyebrows: UPPERCASE TRACKED ("GROUP A", "FULL TIME", "HIGH CONFIDENCE")
- CTAs: title-case short verbs ("Sign in", "Use this", "Save across devices", "Share")

**Tone rules:**
- Direct and inviting. "Choose your World Cup team" not "Select a team to continue."
- Short sentences. Imperative verbs in CTAs ("Build", "Follow", "Pick", "Climb").
- Football vocabulary: "fixture", "kickoff", "bracket", "group stage", "knockout", "FT", "AET", "pens".
- Disclaimer always present but never alarmist — short, factual, small type.
- No emoji anywhere in the product UI (emoji appear only in documentation/dev tools).
- Numbers formatted with tabular figures (`font-variant-numeric: tabular-nums`).

**Perspective:** Second-person "you". Product speaks to the user directly.

**Disclaimers:** Every surface carries the standing disclaimer in muted type: *"For analytics and entertainment only. Not betting advice."* A yellow-triangle (⚠) warning banner is pinned at the very top on every page.

---

## Visual Foundations

### Colors
The palette is called the "broadcast terminal" — it references pitch-side broadcast graphics and football stadium floodlights at night.

| Role | Token | Hex | HSL |
|---|---|---|---|
| Canvas | `--c-background` | `#0a1410` | `156 30% 5%` |
| Card surface | `--c-surface` | `#101d16` | `156 22% 9%` |
| Raised surface | `--c-surface-2` | `#151f19` | `156 18% 12%` |
| Text | `--c-foreground` | `#f3f6f3` | `150 20% 96%` |
| Muted text | `--c-muted` | `#94a897` | `150 9% 64%` |
| Hairline | `--c-border` | `#243028` | `153 18% 18%` |
| Win (lime) | `--c-win` | `#9ee633` | `84 78% 55%` |
| Draw (amber) | `--c-draw` | `#f9b030` | `41 96% 60%` |
| Loss (rose) | `--c-loss` | `#f6516b` | `351 90% 65%` |
| Gold | `--c-gold` | `#e0b64a` | `43 74% 62%` |

**Color philosophy:** The canvas is not pure black — it has a slight green warmth (`156°`) that reads as a deep night-time football pitch. Lime (`--c-win`, `#9ee633`) is the single dominant accent used for: the brand mark, active states, CTA buttons, win bars, and gradient text. The amber/rose/gold trio exists only in data contexts (draw, loss, HOST). Never use lime for loss or vice versa — the semantic mapping is strict.

### Typography
Two grotesques, both from Google Fonts:

| Role | Family | Weights | CSS var |
|---|---|---|---|
| Display | **Bricolage Grotesque** | 400–800 | `--font-display` |
| Body | **Hanken Grotesk** | 400–800 | `--font-body` |

Bricolage Grotesque is condensed and chunky — used for team names, headlines, scores, eyebrow labels. Hanken Grotesk is clean and neutral — used for body copy, UI labels, probability percentages. Both are antialiased; tabular figures are on by default via `font-feature-settings: "tnum"`.

Display text always uses tight tracking (`letter-spacing: -0.02em`). Eyebrows and label caps use wide tracking (`letter-spacing: 0.08em`). Score and data figures use `font-variant-numeric: tabular-nums`.

The wordmark splits "Final" (foreground) + "Whistle" (lime) — this two-tone rule is strictly preserved at every size.

### Backgrounds
A fixed three-layer radial glow sits behind all content:
1. **Lime radial** at top-right (80% -10%): subtle win-color ambient glow
2. **Gold radial** at top-left (-10% 10%): very faint warmth
3. **Deep green** at bottom (50% 120%): grounds the canvas

Over this, a **film grain** at ~3.5% opacity adds analogue texture without visible noise. The atmosphere is always `position: fixed` and `pointer-events: none`. See `--atmosphere` token and `tokens/base.css`.

### Cards
All cards use the **glass card** pattern: translucent `linear-gradient` from `--c-surface` to `--c-surface-2`, `backdrop-filter: blur(12px)`, and a `1px` border at `hsl(var(--c-border) / 0.8)`. Corner radius is `--radius-2xl` (20px) for match cards and panels; `--radius-xl` (16px) for inner chips.

**Hover lift:** Clickable cards rise `translateY(-3px)` with a lime-tinted `box-shadow` (see `--shadow-hover`) and a lime border accent. Transition uses `--ease-out-expo` (expo deceleration, feels snappy). Live matches get an additional `ring-1` border in rose (`--c-loss / 0.4`).

### Motion
- **Easing:** `cubic-bezier(0.22, 1, 0.36, 1)` (expo out) for all entrance/lift transitions. Never linear or ease-in.
- **Fade-up entrance:** `fwFadeUp` keyframe — opacity 0→1 + translateY(14px→0), 0.55s.
- **Skeleton shimmer:** horizontal gradient sweep, 1.5s loop.
- **Floating elements:** `floatY` ±14px, 6–9s loop (hero elements only).
- **Reduced motion:** all animations disabled, transitions removed, `reveal` pre-revealed.

### Hover / press states
- Cards: `translateY(-3px)` + lime border + lime-tinted shadow
- Nav links: `bg-surface-2/60` tint, `text-foreground`
- Active nav link: `bg-surface-2/70` + `text-foreground`
- Buttons: `primary` → background opacity steps up; `solid` → `brightness(1.06)`
- Bottom nav: inactive = `--text-muted`, active = `--c-win`

### Layout
- Max content width: `72rem` (1152px), `px-4 sm:px-5` gutter
- Nav height: `3.75rem` (sticky, `backdrop-blur-xl`)
- Mobile tab bar: fixed bottom, `safe-area-inset-bottom` aware
- Grid: 2-column country chooser; single-column match list; full-width bracket rows

### Iconography — see ICONOGRAPHY section below

### Corner radii
- Chips / score tags: `--radius-sm` (6px)
- Buttons / inputs: `--radius-md` (8px) – `--radius-xl` (16px)
- Cards / panels: `--radius-xl` (16px) – `--radius-2xl` (20px)
- Hero panels: `--radius-3xl` (24px)
- Flags, dots, pills: `--radius-pill` (999px)

### Transparency & blur
- Nav: `bg-background/70` + `backdrop-blur-xl`
- Bottom sheet / mobile menu: `bg-background/95` + `backdrop-blur-xl`
- Cards: `glass` = translucent gradient + `blur(12px)`
- Overlays: `bg-background/40` + `backdrop-blur-[2px]` (lightest touch)

---

## Iconography

Icons are **inline stroke SVGs**, styled with `currentColor`, `stroke-width: 2`, `viewBox="0 0 24 24"`, `fill="none"`. They are never image files or an icon font. No icon library is used — all icons are hand-authored as minimal SVG path/shape primitives, closely matching the Lucide icon visual style (24px grid, 2px stroke, rounded linecaps).

**CDN substitute:** If you need more icons beyond the handful in the UI, use **Lucide Icons** (`https://unpkg.com/lucide@latest`) — same 24px grid, same 2px stroke weight, same rounded style. This is the closest CDN match. Flag the substitution to the team if used.

**Flags:** National-team flags are loaded from **flagcdn.com** (`https://flagcdn.com/w80/{iso-code}.png`), displayed as circular chips with a `ring-1 ring-border/80` hairline. The iso-code map is in `components/brand/Flag.jsx`. Always include the typographic fallback (team initials on dark chip) for unknown nations or CDN failures.

**Brand mark:** The FinalWhistle hexagon-whistle SVG (see `components/brand/Logo.jsx` and `assets/icon.svg`) is a single-path group, always lime (`hsl(var(--c-win))`), never recolored to white or muted.

**App icons (assets/):**
- `assets/icon.svg` — scalable SVG icon (lime mark on `#08120d` rounded square)
- `assets/icon-192.png` — PWA 192×192 icon
- `assets/icon-512.png` — PWA 512×512 icon
- `assets/icon-maskable-512.png` — Android adaptive icon (safe zone padded)
- `assets/apple-icon-180.png` — Apple 180×180 touch icon

No emoji, no Unicode symbols used as icons in the product UI.

---

## Files & Index

```
styles.css                  ← Link this. @import manifest for all tokens.
tokens/
  colors.css                Color tokens (raw HSL triplets + semantic aliases)
  typography.css            Font families, type scale, weights, tracking
  spacing.css               4px-base spacing, radii, layout tokens
  effects.css               Shadows, glass, glows, atmosphere, easing
  fonts.css                 @import of Google Fonts (Bricolage + Hanken)
  base.css                  Body atmosphere, helpers (.fw-glass, .fw-card-hover, etc.), keyframes

assets/
  icon.svg                  App icon (SVG, scalable)
  icon-192.png              PWA icon 192×192
  icon-512.png              PWA icon 512×512
  icon-maskable-512.png     Android adaptive icon
  apple-icon-180.png        Apple touch icon

components/
  core/
    Button.jsx/.d.ts/.prompt.md    Primary/solid/secondary/ghost buttons
    Badge.jsx/.d.ts/.prompt.md     Pill badges (win/draw/loss/gold/neutral)
    Card.jsx/.d.ts/.prompt.md      Glass card container (hover-lift variant)
    Input.jsx/.d.ts/.prompt.md     Search / text input with lime focus ring
  brand/
    Logo.jsx/.d.ts/.prompt.md      BrandMark, Wordmark, Logo lockup
    Flag.jsx/.d.ts/.prompt.md      National-flag chip (flagcdn + fallback)
    ProbabilityBar.jsx/.d.ts       W/D/L stacked bar — the signature visual
    MatchCard.jsx/.d.ts/.prompt.md Composite match card (composes all above)

guidelines/
  colors-canvas.card.html    Specimen: canvas + surface colors
  colors-accents.card.html   Specimen: win/draw/loss/gold accents
  type-display.card.html     Specimen: Bricolage Grotesque scale
  type-body.card.html        Specimen: Hanken Grotesk scale
  spacing-scale.card.html    Specimen: spacing token bars
  spacing-radii.card.html    Specimen: border radius showcase
  spacing-elevation.card.html Specimen: shadow + glass elevation
  brand-logo.card.html       Specimen: mark, wordmark, lockup
  brand-atmosphere.card.html  Specimen: atmospheric glow + grain

ui_kits/
  finalwhistle/
    index.html              ← Interactive 4-screen mobile app prototype
                               Screens: Home (country chooser + team hub),
                               Matches (filters + match cards), Bracket builder,
                               Leaderboard table.
```
