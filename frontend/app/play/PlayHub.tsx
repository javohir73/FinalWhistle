"use client";

import Link from "next/link";
import { useState } from "react";
import { CompetitionLogo } from "@/components/CompetitionLogo";
import { LeagueTipsPlaySection } from "@/components/leagueTips/LeagueTipsPlaySection";
import { NrlTipsPlaySection } from "@/components/nrl/NrlTipsPlaySection";
import { PlayBracketCard, type BracketChampion } from "@/components/play/PlayBracketCard";
import { PlayLeaderboard } from "@/components/play/PlayLeaderboard";
import { ACTIVE_LEAGUES } from "@/lib/leagueConfig";
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
 * Every active football league owns its picker and resolved matchweek; no
 * league can borrow another competition's state.
 */
export function PlayHub({ nrlTipsheet, hasBrackets, champion }: PlayHubProps) {
  const [footballMatchweeks, setFootballMatchweeks] = useState<
    Partial<Record<string, number | null>>
  >({});

  function setLeagueMatchweek(league: string, matchweek: number | null) {
    setFootballMatchweeks((current) => ({ ...current, [league]: matchweek }));
  }

  return (
    <div>
      <p className="font-display text-label uppercase tracking-wider text-muted">Play</p>
      <h1 className="mt-1 font-display text-3xl font-extrabold">The slate</h1>
      <p className="mt-1.5 text-body text-muted">
        Make your picks against the model, organized by competition.
      </p>

      {ACTIVE_LEAGUES.map((league) => (
        <PlayCompetitionSection
          key={league}
          competition={league as CompetitionId}
          subtitle="Score predictions"
        >
          <div className="-mt-5">
            <LeagueTipsPlaySection
              defaultLeague={league}
              showLeaderboard={false}
              showLeagueSwitcher={false}
              showClaim={league === ACTIVE_LEAGUES[0]}
              onMatchweekResolved={(matchweek) => setLeagueMatchweek(league, matchweek)}
            />
          </div>
        </PlayCompetitionSection>
      ))}

      <PlayCompetitionSection competition="ucl" subtitle="League-phase score predictions">
        <div className="glass mt-3 rounded-2xl p-4">
          <p className="text-body text-muted">
            Score tips open when the league-phase matchweeks are loaded. Qualifying model
            predictions are available now on the fixtures page.
          </p>
          <Link
            href="/football/ucl/fixtures"
            className="mt-3 inline-flex text-sm font-semibold text-accent hover:underline"
          >
            View Champions League fixtures →
          </Link>
        </div>
      </PlayCompetitionSection>

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
            <p className="text-body text-muted">NRL tips aren&apos;t available right now.</p>
          </div>
        )}
      </PlayCompetitionSection>

      {/* One board for every competition (p5-s4). It reuses the same shipped
          LeagueTipsLeaderboard / NrlTipsLeaderboard the sections used to render
          inline -- filtered by competition, seeded with the NRL season/round and
          the per-league football matchweeks resolved above. NRL off-season and
          football pre-resolution each show their own honest state. */}
      <PlayLeaderboard
        nrlSeason={nrlTipsheet?.season ?? null}
        nrlRound={nrlTipsheet?.round ?? null}
        footballLeagues={ACTIVE_LEAGUES}
        footballMatchweeks={footballMatchweeks}
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
          <p className="text-label text-muted">{subtitle}</p>
        </div>
      </div>

      {children}
    </section>
  );
}
