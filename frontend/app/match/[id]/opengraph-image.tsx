import { ImageResponse } from "next/og";
import { Shell, OgFlag, OG_SIZE, OG_CONTENT_TYPE, C } from "@/lib/og";
import { getMatchServer } from "@/lib/api";
import { flagUrl } from "@/lib/flags";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;
export const alt = "Match prediction — FinalWhistle";

const pc = (n: number) => `${Math.round(n * 100)}%`;

export default async function Image({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const p = await getMatchServer(id).catch(() => null);

  if (!p) {
    return new ImageResponse(
      (
        <Shell eyebrow="Match prediction">
          <div style={{ display: "flex", fontSize: 64, fontWeight: 800 }}>World Cup 2026 match</div>
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
      <Shell eyebrow="Match prediction">
        <div style={{ display: "flex", flexDirection: "column", gap: 36 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <Team name={home} prob={home_win} />
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
              <div style={{ display: "flex", fontSize: 28, color: C.muted }}>most likely</div>
              <div style={{ display: "flex", fontSize: 56, fontWeight: 800 }}>
                {p.predicted_score.home}–{p.predicted_score.away}
              </div>
            </div>
            <Team name={away} prob={away_win} />
          </div>

          <div style={{ display: "flex", width: "100%", height: 22, borderRadius: 999, overflow: "hidden" }}>
            <div style={{ display: "flex", width: `${home_win * 100}%`, background: C.win }} />
            <div style={{ display: "flex", width: `${draw * 100}%`, background: C.draw }} />
            <div style={{ display: "flex", width: `${away_win * 100}%`, background: C.loss }} />
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 26 }}>
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
