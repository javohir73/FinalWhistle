"use client";

import { useState } from "react";
import type { LineupPlayer, TeamLineup } from "@/lib/types";

/** Renders one team's starting XI on a vertical pitch, positioned from each
 *  player's API-Football `grid` ("row:col"). Row 1 is the goalkeeper line and
 *  rows climb toward attack, so we place row 1 at the BOTTOM and higher rows
 *  nearer the top (the team attacks upward). `col` runs left→right within a line.
 *
 *  Each shirt is a toggle button: tap / Enter / Space reveals the player's name
 *  and position. Display-only — never feeds the prediction model. AA contrast,
 *  prefers-reduced-motion safe (no animation), fully keyboard accessible. */
export function FormationPitch({ lineup }: { lineup: TeamLineup }) {
  // Track which shirt is "open" (name+position revealed). Single-open keeps the
  // pitch readable; toggling the same shirt closes it.
  const [openKey, setOpenKey] = useState<string | null>(null);

  const rows = layoutRows(lineup.start_xi);

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <span className="font-display text-sm font-bold text-foreground">{lineup.team}</span>
        {lineup.formation && (
          <span className="text-xs font-semibold tabular-nums text-lime-deep">
            {lineup.formation}
          </span>
        )}
      </div>

      {/* Pitch: deep-green panel with centre line + circle. The XI is laid out in
          rows from defence (bottom) to attack (top). */}
      <div
        className="panel-pitch relative overflow-hidden rounded-2xl px-2 py-3"
        role="group"
        aria-label={`${lineup.team} starting eleven${
          lineup.formation ? `, ${lineup.formation}` : ""
        }`}
      >
        {/* Pitch markings — decorative only. */}
        <div aria-hidden className="pointer-events-none absolute inset-0">
          <div className="absolute left-0 right-0 top-1/2 h-px bg-white/20" />
          <div className="absolute left-1/2 top-1/2 h-14 w-14 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/20" />
        </div>

        <div className="relative flex flex-col gap-3">
          {rows.map((row, i) => (
            <div key={i} className="flex items-start justify-around gap-1">
              {row.map((p, j) => {
                const key = playerKey(p, i, j);
                return (
                  <PlayerShirt
                    key={key}
                    player={p}
                    open={openKey === key}
                    onToggle={() => setOpenKey((cur) => (cur === key ? null : key))}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {lineup.coach && (
        <p className="mt-2 text-xs text-muted">
          Coach: <span className="text-foreground/90">{lineup.coach}</span>
        </p>
      )}
    </div>
  );
}

export function PlayerShirt({
  player,
  open,
  onToggle,
  showName = false,
  tone = "home",
}: {
  player: LineupPlayer;
  open: boolean;
  onToggle: () => void;
  /** Keep the name visible under the shirt (used on the dense two-team pitch);
   *  when false the name is sr-only until the shirt is tapped. */
  showName?: boolean;
  /** Chip colour, so the two teams are distinguishable on the shared pitch:
   *  "home" is a white shirt, "away" a lime shirt. Single-team pitches stay
   *  white (the default). Identity never relies on colour alone — flag, name,
   *  position and the top/bottom halves all still distinguish the teams. */
  tone?: "home" | "away";
}) {
  const chip =
    tone === "away"
      ? "bg-win text-pitch ring-win/50 hover:ring-white"
      : "bg-white text-pitch ring-white/70 hover:ring-win";
  const label = [
    player.number != null ? `#${player.number}` : null,
    player.name,
    player.position ? `(${player.position})` : null,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="flex min-w-0 flex-col items-center">
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={open}
        aria-label={label}
        title={player.name}
        className={
          "grid h-8 w-8 place-items-center rounded-full font-display text-[13px] font-extrabold tabular-nums ring-1 motion-safe:transition hover:ring-2 sm:h-9 sm:w-9 " +
          chip
        }
      >
        <span aria-hidden>{player.number ?? "·"}</span>
      </button>
      <span
        className={
          "mt-1 max-w-[72px] truncate text-center text-[10px] leading-tight text-white " +
          (open || showName ? "" : "sr-only")
        }
      >
        {lastName(player.name)}
        {open && player.position ? (
          <span className="block text-white/70">{player.position}</span>
        ) : null}
      </span>
    </div>
  );
}

/** Group the XI into rows keyed by the grid `row` (1 = GK line), then order each
 *  row left→right by `col`. Players with no parsable grid fall into a trailing
 *  "unpositioned" row so all eleven always render.
 *
 *  `attackingUp` (default) emits the highest row first, so stacked top→bottom the
 *  attackers sit on top and the GK at the bottom (a team attacking upward — the
 *  single-team pitch). Pass `false` for a team attacking DOWNWARD (the top half
 *  of the shared match pitch): emits row 1 first, putting the GK at the top. */
export function layoutRows(players: LineupPlayer[], attackingUp = true): LineupPlayer[][] {
  const byRow = new Map<number, { col: number; player: LineupPlayer }[]>();
  const unpositioned: LineupPlayer[] = [];

  for (const p of players) {
    const parsed = parseGrid(p.grid);
    if (!parsed) {
      unpositioned.push(p);
      continue;
    }
    const bucket = byRow.get(parsed.row) ?? [];
    bucket.push({ col: parsed.col, player: p });
    byRow.set(parsed.row, bucket);
  }

  const orderedRows = Array.from(byRow.keys()).sort((a, b) => (attackingUp ? b - a : a - b));
  const rows = orderedRows.map((r) =>
    byRow
      .get(r)!
      .sort((a, b) => a.col - b.col)
      .map((x) => x.player),
  );

  if (unpositioned.length > 0) rows.push(unpositioned);
  return rows;
}

/** Parse an API-Football grid string "row:col" into numbers, or null if absent
 *  or malformed (defensive — bench players carry a null grid). */
function parseGrid(grid: string | null): { row: number; col: number } | null {
  if (!grid) return null;
  const m = /^(\d+):(\d+)$/.exec(grid.trim());
  if (!m) return null;
  return { row: Number(m[1]), col: Number(m[2]) };
}

/** Stable key per shirt — number is unique within a real XI, but fall back to
 *  name + grid position so duplicate/missing numbers don't collide. */
function playerKey(p: LineupPlayer, rowIdx: number, colIdx: number): string {
  return `${p.number ?? "x"}-${rowIdx}-${colIdx}-${p.name}`;
}

/** Last token of a name for the compact on-pitch label (full name stays in the
 *  button's aria-label and title). */
function lastName(name: string): string {
  const parts = name.trim().split(/\s+/);
  return parts[parts.length - 1] || name;
}
