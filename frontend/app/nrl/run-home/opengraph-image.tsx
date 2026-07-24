import { ImageResponse } from "next/og";
import { Shell, OG_SIZE, OG_CONTENT_TYPE, ogFooter, C } from "@/lib/og";
import { getNrlConditionalProjectionsServer, getNrlMatchesServer } from "@/lib/api";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;
export const alt = "Predict the NRL run home — FinalWhistle";

// Same literal-footer reasoning as /nrl/tips/opengraph-image.tsx: NRL isn't
// the site's "active tournament" concept, so no getTournament() call here.
const FOOTER = ogFooter("NRL");

const pc = (n: number) => `${Math.round(n * 100)}%`;

// next/og's convention files (opengraph-image.tsx) render from the route
// SEGMENT only -- they never see the request's query string (confirmed
// against every existing OG file in this repo). /nrl/run-home's real picks
// state is share-link-driven (?picks=...), so a truly picks-aware OG card
// would need a custom Route Handler reading request.nextUrl.searchParams
// instead of this convention -- deliberately out of scope here (see the
// design doc's recon pack: no query-string-driven OG mechanism exists yet).
// This card always renders the unconditioned baseline, same as visiting the
// page with no picks applied.
export default async function Image() {
  const fixtures = await getNrlMatchesServer().catch(() => null);
  const baseline =
    fixtures != null ? await getNrlConditionalProjectionsServer(fixtures.season).catch(() => null) : null;

  if (!baseline) {
    return new ImageResponse(
      (
        <Shell eyebrow="NRL finals odds" footer={FOOTER}>
          <div style={{ display: "flex", fontSize: 64, fontWeight: 800 }}>Predict the run home</div>
        </Shell>
      ),
      { ...size },
    );
  }

  const contenders = baseline.teams.slice(0, 5);

  return new ImageResponse(
    (
      <Shell eyebrow="NRL finals odds" footer={FOOTER}>
        <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
          <div style={{ display: "flex", fontSize: 60, fontWeight: 800, letterSpacing: -1 }}>
            Predict your run home
          </div>
          <div style={{ display: "flex", fontSize: 28, color: C.muted }}>
            Force a result, watch top 8 / top 4 / minor premiership odds move
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 8 }}>
            {contenders.map((t) => (
              <div key={t.team} style={{ display: "flex", justifyContent: "space-between", fontSize: 32 }}>
                <div style={{ display: "flex", fontWeight: 700 }}>{t.team}</div>
                <div style={{ display: "flex", fontWeight: 800, color: C.win }}>
                  Top 8 {pc(t.top8)}
                  <span style={{ display: "flex", marginLeft: 16, color: C.muted, fontWeight: 400 }}>
                    Top 4 {pc(t.top4)}
                  </span>
                </div>
              </div>
            ))}
          </div>

          <div
            style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              borderTop: `1px solid ${C.line}`, paddingTop: 24, fontSize: 28, color: C.muted,
            }}
          >
            from {baseline.n_sims.toLocaleString()} simulations
          </div>
        </div>
      </Shell>
    ),
    { ...size },
  );
}
