"use client";

import { useState } from "react";
import { LeagueTipsPlaySection } from "@/components/leagueTips/LeagueTipsPlaySection";
import { NrlTipsPlaySection } from "@/components/nrl/NrlTipsPlaySection";
import { PlayBracketCard, type BracketChampion } from "@/components/play/PlayBracketCard";
import { PlayLeaderboard } from "@/components/play/PlayLeaderboard";
import { ACTIVE_LEAGUES, DEFAULT_LEAGUE } from "@/lib/leagueConfig";
import { SPORTS, type SportId } from "@/lib/sports";
import type { NrlTipsheet } from "@/lib/types";

interface PlayHubProps {
  /** Current-round NRL tipsheet, server-fetched to seed the NRL group's
   *  season/round. Null when the endpoint has no data yet -- the group still
   *  renders, just without the round line (honest degrade). */
  nrlTipsheet: NrlTipsheet | null;
  /** Whether the active tournament has a knockout bracket (app/brackets gates on
   *  the same `has_brackets`). False for a league-format tournament -- the
   *  Football group then renders the league tips only, no bracket entry. */
  hasBrackets: boolean;
  /** Predicted champion (top-`win_title` team) surfaced on the bracket card, or
   *  null when the odds fetch failed / the simulation hasn't run -- the card
   *  degrades to a plain link. Ignored when `hasBrackets` is false. */
  champion: BracketChampion | null;
}

/** The Floodlight "Play" hub (design: Floodlight Implementation Plan, P5) --
 *  one predictions surface that merges the WC26 bracket, league score tips and
 *  NRL round tips, grouped by sport. The Football group (p5-s2) composes the
 *  shipped /brackets route (via PlayBracketCard) plus the league tips loop
 *  (LeagueTipsPlaySection, reused whole); the NRL group (p5-s3) composes the
 *  shipped beat-the-AI loop (NrlTipsPlaySection, reused whole), seeded from the
 *  same current-round tipsheet /nrl/tips uses, and degrades to an honest empty
 *  state when that fetch has no data. The existing /tips, /brackets and
 *  /nrl/tips routes stay live and get linked in from here. Floodlight skin only
 *  -- lime is the sole action colour, numerics are tabular. */
export function PlayHub({ nrlTipsheet, hasBrackets, champion }: PlayHubProps) {
  // The Football group's picker resolves the current matchweek client-side
  // (there's no public seed for it, unlike NRL). p5-s4 lifts it here so the one
  // unified leaderboard below can mount the football board on the same matchweek
  // the in-group section would have -- null until the picker resolves it.
  const [footballMatchweek, setFootballMatchweek] = useState<number | null>(null);

  return (
    <div>
      <p className="font-display text-[11px] uppercase tracking-wider text-muted">Predictions</p>
      <h1 className="mt-1 font-display text-3xl font-extrabold">Play</h1>
      <p className="mt-1.5 text-[13px] text-muted">
        Make your picks against the model in one place — grouped by sport, graded on a public record.
      </p>

      <PlayGroup sport="football">
        {hasBrackets && <PlayBracketCard champion={champion} className="mt-3" />}
        {/* Reused whole: the exact /tips picker / you-vs-ai, with its
            league-switch remount keying intact. EPL is the only ACTIVE_LEAGUES
            entry, so the switcher never mounts and LaLiga/Bundesliga stay
            dormant -- no fabricated data. p5-s4 suppresses this section's own
            leaderboard (showLeaderboard=false) and instead learns its resolved
            matchweek, hoisting the board into the unified one below. */}
        <LeagueTipsPlaySection
          defaultLeague={DEFAULT_LEAGUE}
          showLeaderboard={false}
          onMatchweekResolved={setFootballMatchweek}
        />
        <p className="mt-6 text-[13px] text-muted">More leagues coming soon.</p>
      </PlayGroup>

      <PlayGroup
        sport="nrl"
        seed={nrlTipsheet ? `Round ${nrlTipsheet.round} · ${nrlTipsheet.season}` : null}
      >
        {/* Reused whole: the exact /nrl/tips beat-the-AI loop (claim, play the
            round, you-vs-ai), seeded with the same server-fetched season/round
            /nrl/tips uses. p5-s4 suppresses this section's own weekly
            leaderboard (showLeaderboard=false) -- it's hoisted into the unified
            board below. p5-s5 opts each play row into the shared ConfidenceRing
            (showConfidence) beside the model's call -- hub only; /nrl/tips stays
            unchanged. When the tipsheet fetch has no data (off-season / upstream
            down) we never invent a season/round -- the group degrades to an
            honest empty state. */}
        {nrlTipsheet ? (
          <NrlTipsPlaySection
            season={nrlTipsheet.season}
            round={nrlTipsheet.round}
            showLeaderboard={false}
            showConfidence
          />
        ) : (
          <div className="glass mt-3 rounded-2xl p-4">
            <p className="text-[13px] text-muted">NRL tips aren&apos;t available right now.</p>
          </div>
        )}
      </PlayGroup>

      {/* One board for every competition (p5-s4). It reuses the same shipped
          LeagueTipsLeaderboard / NrlTipsLeaderboard the sections used to render
          inline -- filtered by competition, seeded with the NRL season/round and
          the football matchweek resolved above. Dormant leagues degrade to a
          quiet "coming soon"; NRL off-season / football pre-resolution each show
          their own honest state. */}
      <PlayLeaderboard
        nrlSeason={nrlTipsheet?.season ?? null}
        nrlRound={nrlTipsheet?.round ?? null}
        footballLeagues={ACTIVE_LEAGUES}
        footballMatchweek={footballMatchweek}
      />
    </div>
  );
}

/** One sport's group: the sport label from the registry as a section heading
 *  (a plain full-bleed divider, not sticky -- the app shell's own sticky top bar
 *  owns top:0) over its body. Both groups pass their composed sections (or an
 *  honest empty state) as `children`. */
function PlayGroup({
  sport,
  seed,
  children,
}: {
  sport: SportId;
  seed?: string | null;
  children?: React.ReactNode;
}) {
  const headingId = `play-group-${sport}`;

  return (
    <section className="mt-8" aria-labelledby={headingId}>
      <div className="-mx-4 flex items-baseline justify-between gap-3 border-b border-border px-4 pb-2">
        <h2 id={headingId} className="font-display text-xl font-extrabold">
          {SPORTS[sport].label}
        </h2>
        {seed != null && <span className="shrink-0 text-xs tabular-nums text-muted">{seed}</span>}
      </div>

      {children}
    </section>
  );
}
