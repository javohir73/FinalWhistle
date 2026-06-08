import { ImageResponse } from "next/og";
import { Shell, OgFlag, OG_SIZE, OG_CONTENT_TYPE, C } from "@/lib/og";
import { getGroupServer } from "@/lib/api";
import { flagUrl } from "@/lib/flags";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;
export const alt = "Group projection — FinalWhistle";

export default async function Image({ params }: { params: { id: string } }) {
  const g = await getGroupServer(params.id).catch(() => null);

  if (!g) {
    return new ImageResponse(
      (
        <Shell eyebrow="Group projection">
          <div style={{ display: "flex", fontSize: 64, fontWeight: 800 }}>World Cup 2026 group</div>
        </Shell>
      ),
      { ...size },
    );
  }

  return new ImageResponse(
    (
      <Shell eyebrow="Projected standings">
        <div style={{ display: "flex", flexDirection: "column", gap: 24, width: "100%" }}>
          <div style={{ display: "flex", fontSize: 60, fontWeight: 800, letterSpacing: -1 }}>{g.name}</div>
          <div style={{ display: "flex", flexDirection: "column", width: "100%" }}>
            {g.standings.slice(0, 4).map((r, i) => (
              <div
                key={r.team_id}
                style={{
                  display: "flex", alignItems: "center", gap: 20,
                  padding: "14px 8px", fontSize: 34,
                  borderTop: `1px solid ${C.line}`,
                  color: i < 2 ? C.fg : C.muted,
                }}
              >
                <div style={{ display: "flex", width: 36, color: C.muted, fontSize: 26 }}>{i + 1}</div>
                <OgFlag url={flagUrl(r.team)} size={44} />
                <div style={{ display: "flex", flex: 1, fontWeight: i < 2 ? 700 : 500 }}>{r.team}</div>
                <div style={{ display: "flex", width: 90, justifyContent: "flex-end", fontWeight: 700 }}>{r.projected_points} pts</div>
                <div style={{ display: "flex", width: 130, justifyContent: "flex-end", color: i < 2 ? C.win : C.muted }}>
                  {r.qualification_prob != null ? `${Math.round(r.qualification_prob * 100)}%` : "—"}
                </div>
              </div>
            ))}
          </div>
        </div>
      </Shell>
    ),
    { ...size },
  );
}
