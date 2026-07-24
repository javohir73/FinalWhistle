import { ImageResponse } from "next/og";
import { Shell, OG_SIZE, OG_CONTENT_TYPE, ogFooter, C } from "@/lib/og";
import { getNrlTipsShareServer } from "@/lib/api";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;
export const alt = "NRL tips result — FinalWhistle";

// Same literal-footer reasoning as the other NRL opengraph-image files: NRL
// isn't the site's "active tournament" (that's a football/WC26 concept).
const FOOTER = ogFooter("NRL");

function parseIntParam(s: string): number | null {
  return /^\d+$/.test(s) ? Number(s) : null;
}

export default async function Image({
  params,
}: {
  params: Promise<{ season: string; round: string; handle: string }>;
}) {
  const { season: seasonParam, round: roundParam, handle } = await params;
  const season = parseIntParam(seasonParam);
  const round = parseIntParam(roundParam);
  const share =
    season != null && round != null
      ? await getNrlTipsShareServer(season, round, handle).catch(() => null)
      : null;

  if (!share) {
    return new ImageResponse(
      (
        <Shell eyebrow="NRL tips" footer={FOOTER}>
          <div style={{ display: "flex", fontSize: 64, fontWeight: 800 }}>NRL tips result</div>
        </Shell>
      ),
      { ...size },
    );
  }

  const playerWon = share.player_points > share.model_points;
  const aiWon = share.player_points < share.model_points;
  const verdictColor = playerWon ? C.win : aiWon ? C.loss : C.draw;

  return new ImageResponse(
    (
      <Shell eyebrow={`NRL Round ${share.round} · ${share.season}`} footer={FOOTER}>
        <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
          <div style={{ display: "flex", fontSize: 56, fontWeight: 800, letterSpacing: -1 }}>
            {share.handle_display}
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 24 }}>
            <div style={{ display: "flex", fontSize: 64, fontWeight: 800, color: verdictColor }}>
              {share.player_points}/{share.player_of}
            </div>
            <div style={{ display: "flex", fontSize: 32, fontWeight: 400, color: C.muted }}>vs the AI</div>
            <div style={{ display: "flex", fontSize: 64, fontWeight: 800, color: C.muted }}>
              {share.model_points}/{share.model_of}
            </div>
          </div>
          {!share.round_complete && (
            // Grading is per finished match, not per whole round, so a
            // partially-graded round must not read as a final result on a
            // public/social image (see page.tsx's matching "so far" copy).
            <div style={{ display: "flex", fontSize: 26, color: C.muted }}>Round still in progress</div>
          )}
          {share.margin_note && (
            <div style={{ display: "flex", fontSize: 26, color: C.muted }}>{share.margin_note}</div>
          )}
        </div>
      </Shell>
    ),
    { ...size },
  );
}
