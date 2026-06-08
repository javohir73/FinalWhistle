import { ImageResponse } from "next/og";
import { Shell, OgFlag, OG_SIZE, OG_CONTENT_TYPE, C } from "@/lib/og";
import { getTeamServer } from "@/lib/api";
import { flagUrl } from "@/lib/flags";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;
export const alt = "Team profile — FinalWhistle";

export default async function Image({ params }: { params: { id: string } }) {
  const data = await getTeamServer(params.id).catch(() => null);

  if (!data) {
    return new ImageResponse(
      (
        <Shell eyebrow="Team profile">
          <div style={{ display: "flex", fontSize: 64, fontWeight: 800 }}>World Cup 2026 team</div>
        </Shell>
      ),
      { ...size },
    );
  }

  const t = data.team;
  const Stat = ({ label, value }: { label: string; value: string }) => (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", fontSize: 48, fontWeight: 800, color: C.win }}>{value}</div>
      <div style={{ display: "flex", fontSize: 24, color: C.muted, textTransform: "uppercase", letterSpacing: 1 }}>{label}</div>
    </div>
  );

  return new ImageResponse(
    (
      <Shell eyebrow="Team profile">
        <div style={{ display: "flex", flexDirection: "column", gap: 40 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
            <OgFlag url={flagUrl(t.name)} size={120} />
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "flex", fontSize: 68, fontWeight: 800, letterSpacing: -2 }}>{t.name}</div>
              <div style={{ display: "flex", fontSize: 28, color: C.muted }}>
                {data.group_name ?? "World Cup 2026"}{t.is_host ? " · Host nation" : ""}
              </div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 80 }}>
            <Stat label="Elo rating" value={t.elo_rating != null ? String(Math.round(t.elo_rating)) : "—"} />
            <Stat label="FIFA rank" value={t.fifa_rank != null ? `#${t.fifa_rank}` : "—"} />
            <Stat label="Confederation" value={t.confederation ?? "—"} />
          </div>
        </div>
      </Shell>
    ),
    { ...size },
  );
}
