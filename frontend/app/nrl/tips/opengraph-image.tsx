import { ImageResponse } from "next/og";
import { Shell, OG_SIZE, OG_CONTENT_TYPE, ogFooter, C } from "@/lib/og";
import { getNrlTipsheetServer } from "@/lib/api";
import type { NrlTipsheetMatch } from "@/lib/types";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;
export const alt = "NRL round tips — FinalWhistle";

// NRL isn't the site's "active tournament" (that's a football/WC26 concept,
// see lib/tournament.ts) -- ogFooter takes a plain literal here instead.
const FOOTER = ogFooter("NRL");

const pc = (n: number) => `${Math.round(n * 100)}%`;

function pickLine(m: NrlTipsheetMatch): string {
  const p = m.prediction!;
  const team = p.pick === "home" ? m.home : p.pick === "away" ? m.away : "Draw";
  return `${team} ${pc(p.pick_confidence)}`;
}

export default async function Image() {
  const tipsheet = await getNrlTipsheetServer().catch(() => null);

  if (!tipsheet) {
    return new ImageResponse(
      (
        <Shell eyebrow="NRL tips" footer={FOOTER}>
          <div style={{ display: "flex", fontSize: 64, fontWeight: 800 }}>NRL round tips</div>
        </Shell>
      ),
      { ...size },
    );
  }

  const picked = tipsheet.matches.filter((m) => m.prediction != null).slice(0, 4);
  const { record } = tipsheet;

  return new ImageResponse(
    (
      <Shell eyebrow="NRL tips" footer={FOOTER}>
        <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
          <div style={{ display: "flex", fontSize: 68, fontWeight: 800, letterSpacing: -1 }}>
            Round {tipsheet.round} tips
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {picked.map((m) => (
              <div key={m.match_no} style={{ display: "flex", justifyContent: "space-between", fontSize: 32 }}>
                <div style={{ display: "flex", fontWeight: 700 }}>
                  {m.home} vs {m.away}
                </div>
                <div style={{ display: "flex", fontWeight: 800, color: C.win }}>{pickLine(m)}</div>
              </div>
            ))}
          </div>

          <div
            style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              borderTop: `1px solid ${C.line}`, paddingTop: 24, fontSize: 28,
            }}
          >
            <div style={{ display: "flex", color: C.muted }}>Season record</div>
            <div style={{ display: "flex", fontWeight: 800 }}>
              {record.winner_accuracy != null ? pc(record.winner_accuracy) : "—"}{" "}
              <span style={{ display: "flex", marginLeft: 10, color: C.muted, fontWeight: 400 }}>
                ({record.evaluated_matches} graded)
              </span>
            </div>
          </div>
        </div>
      </Shell>
    ),
    { ...size },
  );
}
