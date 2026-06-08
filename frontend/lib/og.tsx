/** Shared building blocks for dynamic Open Graph images (next/og).
 *  next/og supports only a flexbox subset of CSS, so everything here uses
 *  explicit display:flex + inline styles. */
import type { ReactNode } from "react";

export const OG_SIZE = { width: 1200, height: 630 };
export const OG_CONTENT_TYPE = "image/png";

export const C = {
  bg: "#08120d",
  bg2: "#0c1a12",
  fg: "#eef3f0",
  muted: "#93a69b",
  line: "#1c2c23",
  win: "#9ee633",
  draw: "#f2b134",
  loss: "#f4607a",
  gold: "#d9b25a",
};

/** Branded frame: wordmark header, centered content, footer tagline. */
export function Shell({ eyebrow, children }: { eyebrow?: string; children: ReactNode }) {
  return (
    <div
      style={{
        height: "100%",
        width: "100%",
        display: "flex",
        flexDirection: "column",
        background: `linear-gradient(135deg, ${C.bg}, ${C.bg2})`,
        color: C.fg,
        padding: "64px 72px",
        fontFamily: "sans-serif",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
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
          <div style={{ fontSize: 30, fontWeight: 800, letterSpacing: -1 }}>FinalWhistle</div>
        </div>
        {eyebrow && (
          <div style={{ display: "flex", fontSize: 22, color: C.muted, textTransform: "uppercase", letterSpacing: 2 }}>
            {eyebrow}
          </div>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", flex: 1, justifyContent: "center" }}>
        {children}
      </div>

      <div style={{ display: "flex", fontSize: 22, color: C.muted }}>
        Explainable FIFA World Cup 2026 predictions · for analytics &amp; entertainment
      </div>
    </div>
  );
}

/** Flag image (flagcdn) with graceful fallback to nothing. */
export function OgFlag({ url, size = 64 }: { url: string | null; size?: number }) {
  if (!url) return <div style={{ display: "flex", width: size, height: size }} />;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={url} width={size} height={size} style={{ borderRadius: 8, objectFit: "cover" }} alt="" />;
}
