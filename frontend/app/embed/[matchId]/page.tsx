import type { CSSProperties } from "react";
import { getMatchServer } from "@/lib/api";
import { APP_NAME, SITE_URL } from "@/lib/constants";
import { parseEmbedConfig, type EmbedConfig, type EmbedSearchParams } from "@/lib/embed-utils";
import { EmbedPredictionCard } from "@/components/EmbedPredictionCard";

/** White-label prediction widget — server component.
 *
 *  Fetches the match + prediction via the same server helper the in-app match
 *  page uses (`getMatchServer`, ISR-cached), then renders the compact
 *  {@link EmbedPredictionCard}. Partners iframe `/embed/{matchId}` with optional
 *  style query params (see lib/embed-utils.ts). It must NEVER hard-crash: a
 *  missing match, an unpredicted fixture, or a backend hiccup all fall back to a
 *  small "prediction unavailable" card so the partner's iframe stays graceful. */
export default async function EmbedPage({
  params,
  searchParams,
}: {
  params: Promise<{ matchId: string }>;
  searchParams: Promise<EmbedSearchParams>;
}) {
  const { matchId } = await params;
  const config = parseEmbedConfig(await searchParams);

  // getMatchServer returns null on a 404; a transient backend error would throw,
  // which we also want to render as the graceful card rather than a 500 inside
  // someone else's page.
  const prediction = await getMatchServer(matchId).catch(() => null);

  if (!prediction) {
    return <Unavailable config={config} />;
  }

  return <EmbedPredictionCard prediction={prediction} config={config} />;
}

/** Minimal, self-contained fallback card (mirrors EmbedPredictionCard's palette
 *  and footer so it looks intentional, not broken). */
function Unavailable({ config }: { config: EmbedConfig }) {
  const dark = config.mode === "dark";
  const palette = dark
    ? { surface: "#12130f", foreground: "#f3f5ef", muted: "#9aa39a", border: "#2a2d25" }
    : { surface: "#ffffff", foreground: "#0f2117", muted: "#6b7c71", border: "#e6eae0" };

  const cardStyle: CSSProperties = {
    boxSizing: "border-box",
    width: "100%",
    maxWidth: 340,
    padding: "1.125rem",
    borderRadius: 16,
    background: palette.surface,
    border: `1px solid ${palette.border}`,
    color: palette.foreground,
    fontFamily:
      "var(--font-body, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif)",
    textAlign: "center",
  };

  return (
    <div style={cardStyle}>
      <p
        style={{
          margin: 0,
          fontFamily: "var(--font-display, var(--font-body, ui-sans-serif, system-ui, sans-serif))",
          fontSize: 14,
          fontWeight: 700,
        }}
      >
        Prediction unavailable
      </p>
      <p style={{ margin: "6px 0 0", fontSize: 12, color: palette.muted, lineHeight: 1.4 }}>
        This match&apos;s prediction isn&apos;t ready yet. Check back closer to kickoff.
      </p>
      <div style={{ marginTop: 12, paddingTop: 8, borderTop: `1px solid ${palette.border}` }}>
        <a
          href={`${SITE_URL}?utm_source=embed`}
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontSize: 10, fontWeight: 700, color: config.accent, textDecoration: "none" }}
        >
          Powered by {APP_NAME} ↗
        </a>
      </div>
    </div>
  );
}
