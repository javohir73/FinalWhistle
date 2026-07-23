/** Shared building blocks for dynamic Open Graph images (next/og).
 *  next/og supports only a flexbox subset of CSS, so everything here uses
 *  explicit display:flex + inline styles. */
import type { ReactNode } from "react";

export const OG_SIZE = { width: 1200, height: 630 };
export const OG_CONTENT_TYPE = "image/png";

/** Shared OG footer tagline, parameterized on the active tournament's name
 *  (see lib/tournament.ts) rather than a hardcoded "FIFA World Cup 2026". */
export const ogFooter = (tournamentName: string) =>
  `Explainable ${tournamentName} predictions · for analytics & entertainment`;

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

/** The FinalWhistle mark as an inline SVG data-URI. next/og (Satori) renders
 *  <img> data-URIs reliably; raw inline <svg> support is partial, so we embed. */
const MARK_DATA_URI =
  "data:image/svg+xml," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 172 156"><path d="M46 0h80l46 78-46 78H46L0 78 46 0Z" fill="none" stroke="${C.win}" stroke-width="9" stroke-linejoin="round"/><g transform="translate(36 44)"><path fill="${C.win}" d="M40 70c-20.4 0-37-15.4-37-34.4C3 16.6 19.6 1.2 40 1.2c13.5 0 25.3 6.8 31.7 17h37.7c8.1 0 14.6 6.3 14.6 14.1v23.9H91.5V40.1H76.4C74 57 58.6 70 40 70Z"/><path fill="${C.bg}" d="M87.8 29h24.6c2.3 0 4.2 1.8 4.2 4v12.6H87.8V29Z"/><circle cx="39.6" cy="35.6" r="10.2" fill="${C.bg}"/><path fill="${C.win}" d="M111.5 19h27.8c8 0 14.5 6.3 14.5 14.1v13.2h-29.9v-14c0-7.3-5.4-13.3-12.4-13.3Z"/></g></svg>`,
  );

/** Branded frame: wordmark header, centered content, footer tagline.
 *  `footer` is caller-supplied (rather than a hardcoded WC26 string) so every
 *  OG image can carry the active tournament's name — see lib/tournament.ts. */
export function Shell({
  eyebrow,
  footer,
  children,
}: {
  eyebrow?: string;
  footer: string;
  children: ReactNode;
}) {
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
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={MARK_DATA_URI} width={48} height={44} alt="" style={{ display: "flex" }} />
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
        {footer}
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
