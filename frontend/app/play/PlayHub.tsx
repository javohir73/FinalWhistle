"use client";

import { useState } from "react";
import { CompetitionLogo } from "@/components/CompetitionLogo";
import { LeagueTipsPlaySection } from "@/components/leagueTips/LeagueTipsPlaySection";
import { NrlTipsPlaySection } from "@/components/nrl/NrlTipsPlaySection";
import { PlayBracketCard, type BracketChampion } from "@/components/play/PlayBracketCard";
import { PlayLeaderboard } from "@/components/play/PlayLeaderboard";
import { ACTIVE_LEAGUES, DEFAULT_LEAGUE } from "@/lib/leagueConfig";
import { COMPETITIONS, type CompetitionId } from "@/lib/sports";
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

/** One competition-by-competition slate, matching the Floodlight prototype.
 *
 * Prediction loops remain connected only where their data pipeline is active.
 * Registered leagues without loaded prediction data still get a clearly
 * labelled section, never another league's picker or leaderboard.
 */
export function PlayHub({ nrlTipsheet, hasBrackets, champion }: PlayHubProps) {
  // The Football group's picker resolves the current matchweek client-side
  // (there's no public seed for it, unlike NRL). p5-s4 lifts it here so the one
  // unified leaderboard below can mount the football board on the same matchweek
  // the in-group section would have -- null until the picker resolves it.
  const [footballMatchweek, setFootballMatchweek] = useState<number | null>(null);

  return (
    <div>
      <p className="font-display text-[11px] uppercase tracking-wider text-muted">Play</p>
      <h1 className="mt-1 font-display text-3xl font-extrabold">The slate</h1>
      <p className="mt-1.5 text-[13px] text-muted">
        Make your picks against the model, organized by competition.
      </p>

      <PlayCompetitionSection competition="epl" subtitle="Score predictions">
        <div className="-mt-5">
          <LeagueTipsPlaySection
            defaultLeague={DEFAULT_LEAGUE}
            showLeaderboard={false}
            onMatchweekResolved={setFootballMatchweek}
          />
        </div>
      </PlayCompetitionSection>

      <UnavailableCompetition competition="laliga" />
      <UnavailableCompetition competition="bundesliga" />

      {hasBrackets && (
        <PlayCompetitionSection competition="wc26" subtitle="Knockout bracket">
          <PlayBracketCard champion={champion} className="mt-3" />
        </PlayCompetitionSection>
      )}

      <PlayCompetitionSection
        competition="nrl"
        subtitle={
          nrlTipsheet
            ? `Round ${nrlTipsheet.round} · ${nrlTipsheet.season}`
            : "Round tips"
        }
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
      </PlayCompetitionSection>

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

function PlayCompetitionSection({
  competition,
  subtitle,
  children,
}: {
  competition: CompetitionId;
  subtitle: string;
  children?: React.ReactNode;
}) {
  const config = COMPETITIONS[competition];
  const headingId = `play-competition-${competition}`;

  return (
    <section className="mt-8" aria-labelledby={headingId}>
      <div className="-mx-4 flex items-center gap-3 border-b border-border px-4 pb-3">
        <CompetitionLogo competition={competition} size={32} />
        <div>
          <h2 id={headingId} className="font-display text-xl font-extrabold">
            {config.label}
          </h2>
          <p className="text-[11px] text-muted">{subtitle}</p>
        </div>
      </div>

      {children}
    </section>
  );
}

function UnavailableCompetition({
  competition,
}: {
  competition: "laliga" | "bundesliga";
}) {
  return (
    <PlayCompetitionSection competition={competition} subtitle="Score predictions">
      <p className="glass mt-3 rounded-2xl p-4 text-[13px] text-muted">
        {COMPETITIONS[competition].label} picks will appear when its season feed is loaded.
      </p>
    </PlayCompetitionSection>
  );
}
