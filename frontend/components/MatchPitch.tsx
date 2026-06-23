"use client";

import { useState } from "react";
import { Flag } from "@/components/Flag";
import { PlayerShirt, layoutRows } from "@/components/FormationPitch";
import type { LineupPlayer, TeamLineup } from "@/lib/types";

/** Both starting XIs on ONE shared pitch — the familiar broadcast layout: the
 *  home team fills the top half (GK at the very top, attacking down toward the
 *  halfway line) and the away team the bottom half (GK at the very bottom,
 *  attacking up), mirrored around a centre line. Flag + name + formation label
 *  top and bottom. Display-only — no ratings or photos (the lineups feed has
 *  none). AA contrast, prefers-reduced-motion safe, keyboard accessible. */
export function MatchPitch({ home, away }: { home: TeamLineup; away: TeamLineup }) {
  // One shirt open at a time across both teams; tapping it again closes it.
  const [openKey, setOpenKey] = useState<string | null>(null);
  const toggle = (key: string) => setOpenKey((cur) => (cur === key ? null : key));

  const homeRows = layoutRows(home.start_xi, false); // GK at top, attacking down
  const awayRows = layoutRows(away.start_xi, true); // attacking up, GK at bottom

  return (
    <div>
      <TeamHeader team={home} tone="home" />
      <div
        className="panel-pitch relative overflow-hidden rounded-2xl px-2 py-3"
        role="group"
        aria-label={`Starting elevens — ${home.team} versus ${away.team}`}
      >
        {/* Pitch markings — decorative. Centre line + circle at the halfway point. */}
        <div aria-hidden className="pointer-events-none absolute inset-0">
          <div className="absolute left-0 right-0 top-1/2 h-px bg-white/25" />
          <div className="absolute left-1/2 top-1/2 h-16 w-16 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/20" />
        </div>

        <div className="relative flex flex-col gap-3">
          {homeRows.map((row, i) => (
            <PitchRow key={`h-${i}`} row={row} side="h" tone="home" rowIdx={i} openKey={openKey} onToggle={toggle} />
          ))}
          <div aria-hidden className="h-2" /> {/* breathing room across halfway */}
          {awayRows.map((row, i) => (
            <PitchRow key={`a-${i}`} row={row} side="a" tone="away" rowIdx={i} openKey={openKey} onToggle={toggle} />
          ))}
        </div>
      </div>
      <TeamHeader team={away} tone="away" />
    </div>
  );
}

function PitchRow({
  row,
  side,
  tone,
  rowIdx,
  openKey,
  onToggle,
}: {
  row: LineupPlayer[];
  side: "h" | "a";
  tone: "home" | "away";
  rowIdx: number;
  openKey: string | null;
  onToggle: (key: string) => void;
}) {
  return (
    <div className="flex items-start justify-around gap-1">
      {row.map((p, j) => {
        const key = `${side}-${p.number ?? "x"}-${rowIdx}-${j}-${p.name}`;
        return (
          <PlayerShirt
            key={key}
            player={p}
            tone={tone}
            open={openKey === key}
            onToggle={() => onToggle(key)}
            showName
          />
        );
      })}
    </div>
  );
}

function TeamHeader({ team, tone }: { team: TeamLineup; tone: "home" | "away" }) {
  return (
    <div className="flex items-center justify-between gap-2 px-1 py-2">
      <span className="flex min-w-0 items-center gap-2">
        {/* Colour key: matches this team's shirt colour on the pitch. */}
        <span
          aria-hidden
          className={
            "h-2.5 w-2.5 shrink-0 rounded-full ring-1 " +
            (tone === "away" ? "bg-win ring-win/50" : "bg-white ring-border")
          }
        />
        <Flag team={team.team} size={20} />
        <span className="truncate font-display text-sm font-bold text-foreground">{team.team}</span>
      </span>
      {team.formation && (
        <span className="shrink-0 rounded-full bg-surface-2 px-2 py-0.5 text-xs font-semibold tabular-nums text-lime-deep">
          {team.formation}
        </span>
      )}
    </div>
  );
}
