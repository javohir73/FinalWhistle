/** Embed widget configuration — parses the partner-supplied query string on the
 *  `/embed/[matchId]` route into a small, *validated* set of style/flags.
 *
 *  Everything here is defensive: the values land in inline `style`/`className`
 *  attributes on a page partners iframe into their own sites, so an unvalidated
 *  `accent` would be a CSS-injection vector. We allowlist a short palette of
 *  named accents (mapped to our own design tokens) and additionally accept a
 *  plain 3/6-digit hex, rejecting anything else back to the brand accent. */

/** Named accent → HSL triple (matches the tokens in globals.css). Keeping the
 *  raw `H S% L%` string lets callers build `hsl(var-like)` values and derive
 *  soft tints with `hsl(<triple> / <alpha>)`. */
const ACCENT_PRESETS: Record<string, string> = {
  lime: "84 66% 52%", // --win (brand default fill)
  green: "151 51% 14%", // --pitch (deep green)
  amber: "41 78% 51%", // --draw
  rose: "350 84% 62%", // --loss
  gold: "42 62% 48%", // --gold
  blue: "212 78% 52%",
  violet: "265 68% 60%",
  slate: "215 16% 47%",
};

/** The brand default accent (deep, AA-on-light lime — same as `--lime-deep`).
 *  Used for text/links/rings where the bright lime would fail contrast. */
export const DEFAULT_ACCENT = "108 56% 27%";

/** #RGB or #RRGGBB, case-insensitive. */
const HEX_RE = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;

export type EmbedMode = "light" | "dark";

export interface EmbedConfig {
  /** CSS color string for the accent (either `hsl(H S% L%)` or `#rrggbb`),
   *  always safe to drop into a style attribute. */
  accent: string;
  mode: EmbedMode;
  /** Render the tighter layout (drops secondary chrome, smaller paddings). */
  compact: boolean;
  /** Hide the "why" reasons list entirely. */
  hideReasons: boolean;
}

/** Next's `searchParams` values are `string | string[] | undefined`; take the
 *  first entry so `?accent=a&accent=b` can't smuggle an array through. */
type RawParam = string | string[] | undefined;
export type EmbedSearchParams = Record<string, RawParam>;

function first(v: RawParam): string | undefined {
  return Array.isArray(v) ? v[0] : v;
}

/** Truthy flag: present and one of 1/true/yes (case-insensitive). A bare
 *  `?compact` (empty value) does NOT enable — partners must pass `=1`. */
function flag(v: RawParam): boolean {
  const s = first(v);
  if (s == null) return false;
  return s === "1" || s.toLowerCase() === "true" || s.toLowerCase() === "yes";
}

/** Resolve the accent param to a safe CSS color. Order: named preset → bare hex
 *  (with a `#` prepended if omitted) → brand default. Never returns caller text
 *  verbatim beyond a strict hex match, so it can't break out of the attribute. */
export function resolveAccent(raw: RawParam): string {
  const value = first(raw)?.trim().toLowerCase();
  if (!value) return `hsl(${DEFAULT_ACCENT})`;

  if (value in ACCENT_PRESETS) return `hsl(${ACCENT_PRESETS[value]})`;

  // Accept `abc`/`aabbcc` or `#abc`/`#aabbcc`.
  const hex = value.startsWith("#") ? value : `#${value}`;
  if (HEX_RE.test(hex)) return hex;

  return `hsl(${DEFAULT_ACCENT})`;
}

/** The raw HSL triple (or hex) for the accent, without the `hsl(...)` wrapper —
 *  used to build soft tints via `hsl(<triple> / 0.15)`. Falls back to a solid
 *  color reference for hex accents (where per-channel alpha needs `color-mix`).
 */
export function accentTint(accent: string, alpha: number): string {
  // `hsl(H S% L%)` → inject an alpha: `hsl(H S% L% / a)`.
  const m = accent.match(/^hsl\((.+)\)$/);
  if (m) return `hsl(${m[1]} / ${alpha})`;
  // Hex or anything else: fall back to color-mix with transparent, which every
  // evergreen browser supports and keeps the value injection-safe.
  return `color-mix(in srgb, ${accent} ${Math.round(alpha * 100)}%, transparent)`;
}

/** Parse the full query string into a validated {@link EmbedConfig}. */
export function parseEmbedConfig(searchParams: EmbedSearchParams): EmbedConfig {
  const modeRaw = first(searchParams.mode)?.toLowerCase();
  const mode: EmbedMode = modeRaw === "dark" ? "dark" : "light";

  return {
    accent: resolveAccent(searchParams.accent),
    mode,
    compact: flag(searchParams.compact),
    hideReasons: flag(searchParams.hideReasons),
  };
}
