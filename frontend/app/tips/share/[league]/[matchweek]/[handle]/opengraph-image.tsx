import { ImageResponse } from "next/og";
import { Shell, OG_SIZE, OG_CONTENT_TYPE, ogFooter, C } from "@/lib/og";
import { getLeagueTipsShareServer } from "@/lib/api";
import { getTournament } from "@/lib/tournament";
import { leagueLabel } from "@/lib/leagueConfig";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;
export const alt = "Beat the AI tips result — FinalWhistle";

function parseIntParam(s: string): number | null {
  return /^\d+$/.test(s) ? Number(s) : null;
}

export default async function Image({
  params,
}: {
  params: Promise<{ league: string; matchweek: string; handle: string }>;
}) {
  const { league, matchweek: matchweekParam, handle } = await params;
  const matchweek = parseIntParam(matchweekParam);
  const [share, tournament] = await Promise.all([
    matchweek != null ? getLeagueTipsShareServer(league, matchweek, handle).catch(() => null) : Promise.resolve(null),
    // Unlike the NRL share image (which hardcodes an "NRL" footer because NRL
    // sits alongside the site's real "active tournament" concept), football
    // IS that concept -- so the footer names whatever league is actually
    // live rather than a literal string.
    getTournament(),
  ]);
  const footer = ogFooter(tournament.name);

  if (!share) {
    return new ImageResponse(
      (
        <Shell eyebrow={`${leagueLabel(league)} tips`} footer={footer}>
          <div style={{ display: "flex", fontSize: 64, fontWeight: 800 }}>Tips result</div>
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
      <Shell eyebrow={`${leagueLabel(share.league)} Matchweek ${share.matchweek}`} footer={footer}>
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
          {!share.matchweek_complete && (
            // Grading is per finished match, not per whole matchweek, so a
            // partially-graded matchweek must not read as a final result on
            // a public/social image (see page.tsx's matching "so far" copy).
            <div style={{ display: "flex", fontSize: 26, color: C.muted }}>Matchweek still in progress</div>
          )}
        </div>
      </Shell>
    ),
    { ...size },
  );
}
