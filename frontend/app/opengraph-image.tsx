import { ImageResponse } from "next/og";
import { Shell, OG_SIZE, OG_CONTENT_TYPE, C } from "@/lib/og";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;
export const alt = "FinalWhistle — FIFA World Cup 2026 predictions";

export default function Image() {
  return new ImageResponse(
    (
      <Shell eyebrow="World Cup 2026">
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div style={{ display: "flex", fontSize: 76, fontWeight: 800, letterSpacing: -2, lineHeight: 1.05 }}>
            Predict the World Cup,
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
