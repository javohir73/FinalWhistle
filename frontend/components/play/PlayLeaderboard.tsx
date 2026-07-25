"use client";

import { useState } from "react";
import { CompetitionLogo } from "@/components/CompetitionLogo";
import { LeagueTipsLeaderboard } from "@/components/leagueTips/LeagueTipsLeaderboard";
import { NrlTipsLeaderboard } from "@/components/nrl/NrlTipsLeaderboard";
import { Loading } from "@/components/States";
import { COMPETITIONS, type Competition, type CompetitionId } from "@/lib/sports";
import { cn } from "@/lib/utils";

/** The competitions the filter offers: every tips-carrying league-format comp,
 *  in registry order (epl, laliga, bundesliga, nrl). WC26 is dropped -- its
 *  "tips" are the knockout bracket (composed in the Football group), not a
 *  score-tip leaderboard, so it has no board to hoist here. */
const TIPS_COMPETITIONS: Competition[] = Object.values(COMPETITIONS).filter(
  (c) => c.hasTips && c.format === "league",
);

interface PlayLeaderboardProps {
  /** Current NRL season/round from the seeded tipsheet (same source /nrl/tips
   *  uses); null off-season / when the fetch had no data -- the NRL filter then
   *  degrades to an honest empty state rather than fetching a guessed round. */
  nrlSeason: number | null;
  nrlRound: number | null;
  /** The football leagues with a live tips loop today (lib/leagueConfig's
   *  ACTIVE_LEAGUES). A registered-but-dormant league (LaLiga, Bundesliga)
   *  renders as a "coming soon" preview chip and is never fetched. */
  footballLeagues: string[];
  /** The matchweek the Football group's picker resolved, or null until it has.
   *  Mirrors LeagueTipsPlaySection's own guard: the football board only mounts
   *  once this is known, so it never has to guess which matchweek is current. */
  footballMatchweek: number | null;
}

/** The Play hub's single, competition-filtered leaderboard (Floodlight P5,
 *  p5-s4). Replaces the per-section boards: a segmented filter picks a
 *  competition and the matching shipped leaderboard mounts unchanged --
 *  LeagueTipsLeaderboard for a football league, NrlTipsLeaderboard for NRL.
 *  No new leaderboard/scoring logic lives here; this is composition + honest
 *  degrade only. Floodlight skin -- lime is the sole active-chip colour,
 *  numerics stay tabular (the reused boards already are). */
export function PlayLeaderboard({
  nrlSeason,
  nrlRound,
  footballLeagues,
  footballMatchweek,
}: PlayLeaderboardProps) {
  // A football comp is dormant when it has no live tips loop yet; NRL is always
  // an active competition (it just degrades to an empty state off-season), so
  // it's never a dormant chip.
  const isDormant = (c: Competition) => c.sport === "football" && !footballLeagues.includes(c.id);

  // Default to the first selectable competition (EPL today); fall back to the
  // first chip so the panel always has a valid selection to render.
  const [selected, setSelected] = useState<CompetitionId>(
    () => TIPS_COMPETITIONS.find((c) => !isDormant(c))?.id ?? TIPS_COMPETITIONS[0].id,
  );

  const active = COMPETITIONS[selected];

  return (
    <section className="mt-10" aria-labelledby="play-leaderboard-heading">
      <h2 id="play-leaderboard-heading" className="font-display text-xl font-extrabold">
        Leaderboard
      </h2>
      <p className="mt-0.5 text-[13px] text-muted">Filter the public record by competition.</p>

      <div
        role="group"
        aria-label="Filter leaderboard by competition"
        className="-mx-1 mt-3 flex gap-2 overflow-x-auto px-1 pb-1"
      >
        {TIPS_COMPETITIONS.map((c) => {
          const dormant = isDormant(c);
          const isActive = c.id === selected;
          return (
            <button
              key={c.id}
              type="button"
              onClick={() => setSelected(c.id)}
              aria-pressed={isActive}
              aria-label={dormant ? `${c.label} (coming soon)` : undefined}
              className={cn(
                "flex min-h-[44px] shrink-0 items-center gap-2 rounded-xl px-2.5 text-[13px] font-semibold transition",
                isActive
                  ? "bg-win text-pitch"
                  : dormant
                    ? "bg-surface-2 text-muted/50"
                    : "bg-surface-2 text-muted hover:text-foreground",
              )}
            >
              <CompetitionLogo competition={c.id} size={24} />
              {c.label}
            </button>
          );
        })}
      </div>

      <div className="mt-3">
        <LeaderboardPanel
          competition={active}
          dormant={isDormant(active)}
          nrlSeason={nrlSeason}
          nrlRound={nrlRound}
          footballMatchweek={footballMatchweek}
        />
      </div>
    </section>
  );
}

/** The board (or honest empty state) for the selected competition. Kept apart
 *  from the chip row so the fetch-bearing reused boards only ever mount for the
 *  competition actually selected -- a dormant chip renders copy, never a board,
 *  so no dormant competition is ever fetched. */
function LeaderboardPanel({
  competition,
  dormant,
  nrlSeason,
  nrlRound,
  footballMatchweek,
}: {
  competition: Competition;
  dormant: boolean;
  nrlSeason: number | null;
  nrlRound: number | null;
  footballMatchweek: number | null;
}) {
  if (dormant) {
    return <EmptyPanel>{competition.label} tips are coming soon.</EmptyPanel>;
  }

  if (competition.id === "nrl") {
    if (nrlSeason == null || nrlRound == null) {
      return <EmptyPanel>NRL tips aren&apos;t available right now.</EmptyPanel>;
    }
    return <NrlTipsLeaderboard season={nrlSeason} round={nrlRound} />;
  }

  // A live football league: mirror LeagueTipsPlaySection's guard -- hold the
  // board back until the picker has resolved the current matchweek.
  if (footballMatchweek == null) {
    return <Loading label="Loading leaderboard…" />;
  }
  return <LeagueTipsLeaderboard league={competition.id} matchweek={footballMatchweek} />;
}

function EmptyPanel({ children }: { children: React.ReactNode }) {
  return <p className="glass rounded-2xl p-4 text-center text-sm text-muted">{children}</p>;
}
