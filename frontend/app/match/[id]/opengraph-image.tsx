import { ImageResponse } from "next/og";
import { Shell, OgFlag, OG_SIZE, OG_CONTENT_TYPE, ogFooter, C } from "@/lib/og";
import { getMatchServer } from "@/lib/api";
import { getTournament } from "@/lib/tournament";
import { flagUrl } from "@/lib/flags";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;
export const alt = "Match prediction — FinalWhistle";

const pc = (n: number) => `${Math.round(n * 100)}%`;

/** Confidence tier → Floodlight colour. The tier WORD is always printed
 *  alongside (never colour alone) — see the pill in the rich card. */
const confColor: Record<"High" | "Medium" | "Low", string> = {
  High: C.win,
  Medium: C.draw,
  Low: C.muted,
};

export default async function Image({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [p, tournament] = await Promise.all([
    getMatchServer(id).catch(() => null),
    getTournament(),
  ]);

  if (!p) {
    return new ImageResponse(
      (
        <Shell eyebrow="Match prediction" footer={ogFooter(tournament.name)}>
          <div style={{ display: "flex", fontSize: 64, fontWeight: 800 }}>{tournament.name} match</div>
        </Shell>
      ),
      { ...size },
    );
  }

  const { home, away } = p.teams;
  const { home_win, draw, away_win } = p.probabilities;

  const Team = ({ name, prob }: { name: string; prob: number }) => (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: 360, gap: 14 }}>
      <OgFlag url={flagUrl(name)} size={104} />
      <div style={{ display: "flex", fontSize: 40, fontWeight: 800, textAlign: "center", letterSpacing: -1 }}>{name}</div>
      <div style={{ display: "flex", fontSize: 44, fontWeight: 800, color: C.win }}>{pc(prob)}</div>
    </div>
  );

  return new ImageResponse(
    (
      <Shell eyebrow={tournament.name} glow footer={ogFooter(tournament.name)}>
        <div style={{ display: "flex", flexDirection: "column", gap: 36 }}>
          {/* scorebug crest row: home crest — MOST LIKELY score — away crest */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <Team name={home} prob={home_win} />
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
              <div
                style={{
                  display: "flex",
                  fontSize: 22,
                  color: C.muted,
                  textTransform: "uppercase",
                  letterSpacing: 4,
                }}
              >
                Most likely
              </div>
              <div style={{ display: "flex", fontSize: 64, fontWeight: 800, letterSpacing: -1 }}>
                {p.predicted_score.home}–{p.predicted_score.away}
              </div>
              {p.confidence && (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    marginTop: 4,
                    padding: "6px 16px",
                    borderRadius: 999,
                    background: C.line,
                    fontSize: 20,
                    fontWeight: 800,
                    letterSpacing: 1,
                    color: confColor[p.confidence],
                  }}
                >
                  {p.confidence.toUpperCase()} CONFIDENCE
                </div>
              )}
            </div>
            <Team name={away} prob={away_win} />
          </div>

          {/* stacked W/D/L probability bar */}
          <div style={{ display: "flex", width: "100%", height: 22, borderRadius: 999, overflow: "hidden" }}>
            <div style={{ display: "flex", width: `${home_win * 100}%`, background: C.win }} />
            <div style={{ display: "flex", width: `${draw * 100}%`, background: C.draw }} />
            <div style={{ display: "flex", width: `${away_win * 100}%`, background: C.loss }} />
          </div>
          {/* printed labels — win/draw/loss coloured, bold so amber clears the a11y floor */}
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 26, fontWeight: 700 }}>
            <div style={{ display: "flex", color: C.win }}>{home} {pc(home_win)}</div>
            <div style={{ display: "flex", color: C.draw }}>Draw {pc(draw)}</div>
            <div style={{ display: "flex", color: C.loss }}>{away} {pc(away_win)}</div>
          </div>
        </div>
      </Shell>
    ),
    { ...size },
  );
}
