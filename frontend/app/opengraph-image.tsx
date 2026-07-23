import { ImageResponse } from "next/og";
import { Shell, OG_SIZE, OG_CONTENT_TYPE, ogFooter, C } from "@/lib/og";
import { getTournament } from "@/lib/tournament";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;
// Static per the opengraph-image file convention (can't be resolved from the
// tournament without invoking the function) — kept sport-generic instead.
export const alt = "FinalWhistle — match predictions";

export default async function Image() {
  const tournament = await getTournament();
  return new ImageResponse(
    (
      <Shell eyebrow={tournament.name} footer={ogFooter(tournament.name)}>
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div style={{ display: "flex", fontSize: 76, fontWeight: 800, letterSpacing: -2, lineHeight: 1.05 }}>
            Predict {tournament.name},
          </div>
          <div style={{ display: "flex", fontSize: 76, fontWeight: 800, letterSpacing: -2, color: C.win, lineHeight: 1.05 }}>
            explained.
          </div>
          <div style={{ display: "flex", fontSize: 30, color: C.muted, marginTop: 10, maxWidth: 900 }}>
            Win probabilities, scorelines, group tables and a full bracket simulation —
            with the reasoning behind every number.
          </div>
        </div>
      </Shell>
    ),
    { ...size },
  );
}
