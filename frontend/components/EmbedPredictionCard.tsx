import type { CSSProperties } from "react";
import { APP_NAME, SITE_URL } from "@/lib/constants";
import { pct, formatScore, topOutcome } from "@/lib/format";
import { accentTint, type EmbedConfig } from "@/lib/embed-utils";
import type { Prediction } from "@/lib/types";

/** Compact, brandable, self-contained prediction card for the white-label embed.
 *
 *  Unlike the in-app match components (which lean on the global "Daylight" CSS
 *  tokens and `.glass`), this card carries its *own* palette via inline CSS
 *  variables so it renders correctly in a bare iframe on a partner's site — in
 *  either light or dark mode — without depending on our theme cascade. It stays
 *  legible at ~340px wide and reuses the same shared helpers (`pct`,
 *  `formatScore`, `topOutcome`) the main app uses, so the numbers match exactly.
 *
 *  Server-renderable (no hooks/state): the embed page renders it directly. */
export function EmbedPredictionCard({
  prediction,
  config,
}: {
  prediction: Prediction;
  config: EmbedConfig;
}) {
  const { accent, mode, compact, hideReasons } = config;
  const { home, away } = prediction.teams;
  const p = prediction.probabilities;
  const dark = mode === "dark";

  // Self-contained palette. Light values mirror the "Daylight" tokens; dark is a
  // deep, neutral surface that keeps the accent readable. Exposed as CSS vars so
  // the JSX below stays declarative.
  const palette = dark
    ? {
        surface: "#12130f",
        surface2: "#1c1e18",
        foreground: "#f3f5ef",
        muted: "#9aa39a",
        border: "#2a2d25",
      }
    : {
        surface: "#ffffff",
        surface2: "#eef1ea",
        foreground: "#0f2117",
        muted: "#6b7c71",
        border: "#e6eae0",
      };

  // Neutral W/D/L segment colors (fixed hues so the bar reads the same on any
  // partner background); only the winner emphasis + chrome use the accent.
  const winColor = "#8fd633";
  const drawColor = dark ? "#e3a51f" : "#e3a51f";
  const lossColor = "#ef4d68";

  const pad = compact ? "0.875rem" : "1.125rem";
  const cardStyle: CSSProperties = {
    boxSizing: "border-box",
    width: "100%",
    maxWidth: 340,
    padding: pad,
    borderRadius: 16,
    background: palette.surface,
    border: `1px solid ${palette.border}`,
    color: palette.foreground,
    fontFamily:
      "var(--font-body, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif)",
    lineHeight: 1.4,
  };
  const displayFont =
    "var(--font-display, var(--font-body, ui-sans-serif, system-ui, sans-serif))";

  const seg = (w: number): CSSProperties => ({
    width: `${Math.max(0, Math.min(1, w)) * 100}%`,
  });

  const top = topOutcome(p);
  const predictedWinner = top === "home" ? home : top === "away" ? away : null;
  const score = formatScore(prediction.predicted_score.home, prediction.predicted_score.away);
  const reasons = hideReasons ? [] : prediction.reasons.slice(0, compact ? 2 : 3);

  const confChip = confidenceChip(prediction.confidence, dark, palette);

  return (
    <div style={cardStyle} data-embed-mode={mode}>
      {/* Header: matchup + confidence chip */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <span
          style={{
            fontFamily: displayFont,
            fontWeight: 800,
            fontSize: compact ? 14 : 15,
            letterSpacing: "-0.01em",
          }}
        >
          {home} <span style={{ color: palette.muted, fontWeight: 600 }}>vs</span> {away}
        </span>
        {confChip}
      </div>

      {/* Predicted-winner headline + most-likely score */}
      <div style={{ marginTop: compact ? 8 : 10, display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
        <span style={{ fontSize: 12, color: palette.muted }}>
          {predictedWinner ? (
            <>
              Model favours{" "}
              <span style={{ color: accent, fontWeight: 700 }}>{predictedWinner}</span>
            </>
          ) : (
            <span style={{ fontWeight: 700 }}>Too close to call</span>
          )}
        </span>
        <span style={{ fontFamily: displayFont, fontSize: compact ? 16 : 18, fontWeight: 800, fontVariantNumeric: "tabular-nums" }}>
          {score}
        </span>
      </div>

      {/* W/D/L probability bar */}
      <div style={{ marginTop: compact ? 8 : 10 }}>
        <div
          role="img"
          aria-label={`${home} win ${pct(p.home_win)}, draw ${pct(p.draw)}, ${away} win ${pct(p.away_win)}`}
          style={{ display: "flex", height: 10, width: "100%", gap: 2, overflow: "hidden", borderRadius: 999 }}
        >
          <div style={{ ...seg(p.home_win), background: winColor, borderTopLeftRadius: 999, borderBottomLeftRadius: 999 }} />
          <div style={{ ...seg(p.draw), background: drawColor }} />
          <div style={{ ...seg(p.away_win), background: lossColor, borderTopRightRadius: 999, borderBottomRightRadius: 999 }} />
        </div>
        <div style={{ marginTop: 6, display: "flex", justifyContent: "space-between", fontSize: 11, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
          <span style={{ color: dark ? winColor : "#2f6b1e" }}>{pct(p.home_win)}</span>
          <span style={{ color: palette.muted }}>{pct(p.draw)} draw</span>
          <span style={{ color: lossColor }}>{pct(p.away_win)}</span>
        </div>
      </div>

      {/* "Why" reasons (top 2–3, truncated) */}
      {reasons.length > 0 && (
        <ul style={{ margin: compact ? "10px 0 0" : "12px 0 0", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
          {reasons.map((r, i) => (
            <li key={i} style={{ display: "flex", gap: 8, fontSize: 12, color: palette.foreground }}>
              <span
                aria-hidden
                style={{
                  marginTop: 1,
                  flexShrink: 0,
                  width: 14,
                  height: 14,
                  borderRadius: 999,
                  display: "grid",
                  placeItems: "center",
                  background: accentTint(accent, dark ? 0.22 : 0.15),
                  color: accent,
                  fontSize: 9,
                  fontWeight: 800,
                  lineHeight: 1,
                }}
              >
                ✓
              </span>
              <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>
                {r}
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* Footer: disclaimer + Powered by */}
      <div style={{ marginTop: compact ? 10 : 12, paddingTop: 8, borderTop: `1px solid ${palette.border}`, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <span style={{ fontSize: 10, color: palette.muted, lineHeight: 1.3 }}>
          Not betting advice
        </span>
        <a
          href={`${SITE_URL}/match/${prediction.match_id}?utm_source=embed`}
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontSize: 10, fontWeight: 700, color: accent, textDecoration: "none", whiteSpace: "nowrap" }}
        >
          Powered by {APP_NAME} ↗
        </a>
      </div>
    </div>
  );
}

/** Small confidence pill, self-styled (no dependency on the app's ConfidenceBadge
 *  which relies on global token classes). */
function confidenceChip(
  level: Prediction["confidence"],
  dark: boolean,
  palette: { muted: string; surface2: string; border: string },
) {
  if (!level) return null;
  const colors: Record<string, { fg: string; bg: string }> = {
    High: { fg: dark ? "#a7e05a" : "#2f6b1e", bg: dark ? "rgba(143,214,51,0.18)" : "rgba(143,214,51,0.15)" },
    Medium: { fg: dark ? "#e3a51f" : "#9a730f", bg: dark ? "rgba(227,165,31,0.18)" : "rgba(227,165,31,0.15)" },
    Low: { fg: "#ef4d68", bg: "rgba(239,77,104,0.15)" },
  };
  const c = colors[level] ?? { fg: palette.muted, bg: palette.surface2 };
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        flexShrink: 0,
        padding: "3px 8px",
        borderRadius: 999,
        fontSize: 10,
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.03em",
        color: c.fg,
        background: c.bg,
      }}
    >
      <span aria-hidden style={{ width: 5, height: 5, borderRadius: 999, background: "currentColor" }} />
      {level}
    </span>
  );
}
