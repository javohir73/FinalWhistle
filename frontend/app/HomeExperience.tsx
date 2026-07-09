"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { CountryOnboarding } from "@/components/CountryOnboarding";
import { AICalculationReveal } from "@/components/AICalculationReveal";
import { TeamSearch } from "@/components/TeamSearch";
import { Flag } from "@/components/Flag";
import { FavoriteStar } from "@/components/FavoriteStar";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { IntelPanel } from "@/components/IntelPanel";
import { Sparkline } from "@/components/Sparkline";
import { useSelectedCountry } from "@/lib/useSelectedCountry";
import { useFetch } from "@/lib/useFetch";
import { useTimezone } from "@/lib/useTimezone";
import { getTeams, getGroups, getUpcomingMatches, getKnockoutOdds, getModelRecord, getProbHistory } from "@/lib/api";
import { formatScore } from "@/lib/format";
import { prematchCall, predictionVerdict } from "@/lib/verdict";
import { ShootoutNote, BasisTag } from "@/components/ShootoutNote";
import { isLiveNow, liveLabel } from "@/lib/liveLabel";
import { kickoffTime, relativeDayLabel } from "@/lib/datetime";
import type { Group, MatchSummary, ProbHistoryPoint, Team, TournamentOdds } from "@/lib/types";

/** Country-first home. Decides between the chooser, the AI-forecast reveal, and
 *  the personalized hub from locally-stored selection state — all anonymous.
 *  Server-seeded data paints instantly; the hooks refresh it in the background. */
export function HomeExperience({
  initialTeams,
  initialGroups,
  initialMatches,
  initialOdds,
}: {
  initialTeams?: Team[];
  initialGroups?: Group[];
  initialMatches?: MatchSummary[];
  initialOdds?: TournamentOdds[];
}) {
  const { selection, hydrated, select, reveal, clear } = useSelectedCountry();
  const [calculating, setCalculating] = useState(false);
  const [changing, setChanging] = useState(false);

  const teamsState = useFetch(getTeams, [], undefined, initialTeams);
  // Poll fixtures + groups every 30s so live scores/clock and the live group
  // table on the country hub stay current (same cadence as /matches, /groups).
  const groupsState = useFetch(getGroups, [], 30_000, initialGroups);
  const matchesState = useFetch(getUpcomingMatches, [], 30_000, initialMatches);
  const oddsState = useFetch(getKnockoutOdds, [], undefined, initialOdds);

  const teams = teamsState.status === "success" ? teamsState.data : initialTeams ?? [];
  const groups = groupsState.status === "success" ? groupsState.data : initialGroups ?? [];
  const matches = matchesState.status === "success" ? matchesState.data : initialMatches ?? [];
  const odds = oddsState.status === "success" ? oddsState.data : initialOdds ?? [];

  // Avoid an SSR/first-paint mismatch: render a quiet shell until localStorage
  // has been read (matches the server render, which can't know the selection).
  if (!hydrated) {
    return (
      <div className="mx-auto max-w-2xl py-10 sm:py-12" aria-hidden>
        <div className="h-5 w-40 rounded-full skeleton" />
        <div className="mt-3 h-9 w-3/5 rounded-xl skeleton" />
        <div className="mt-7 h-32 rounded-2xl skeleton" />
        <div className="mt-6 h-60 rounded-2xl skeleton" />
      </div>
    );
  }

  const selectedTeam = selection ? teams.find((t) => t.id === selection.team_id) : undefined;

  if (calculating && selection) {
    return (
      <AICalculationReveal
        team={selection.team}
        onComplete={() => {
          reveal();
          setCalculating(false);
        }}
      />
    );
  }

  // Returning user with a revealed forecast: the Daylight home dashboard —
  // greeting, today's movers, match of the day, and the rest of today.
  if (!changing && selection?.prediction_revealed && selectedTeam) {
    return (
      <HomeDashboard
        team={selectedTeam}
        teams={teams}
        groups={groups}
        odds={odds}
        matches={matches}
        onChangeCountry={() => setChanging(true)}
      />
    );
  }

  return (
    <CountryOnboarding
      teams={teams}
      selection={changing ? null : selection}
      onSelect={(t) => {
        select(t.id, t.name);
        setChanging(false);
      }}
      onPredict={() => setCalculating(true)}
      onChangeCountry={() => setChanging(true)}
    />
  );
}

/** Time-of-day greeting in the viewer's local clock, optionally personalised
 *  with the viewer's first name ("Good evening, Javohir"). Purely presentational. */
function greeting(name?: string | null): string {
  const h = new Date().getHours();
  const part = h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  const first = name?.trim().split(/\s+/)[0];
  return first ? `${part}, ${first}` : part;
}

/**
 * The returning-user landing. A friendly greeting + today's count, the
 * "Today's movers" panel (biggest probability swings), the headline "Match of
 * the day", and compact "Also today" rows. All real, already-loaded data.
 */
function HomeDashboard({
  team,
  teams,
  groups,
  odds,
  matches,
  onChangeCountry,
}: {
  team: Team;
  teams: Team[];
  groups: Group[];
  odds: TournamentOdds[];
  matches: MatchSummary[];
  onChangeCountry: () => void;
}) {
  const { tz } = useTimezone();

  // The model's verified track record, for the honest footer line. Background
  // fetch — only rendered once at least one match has been scored.
  const recordState = useFetch(getModelRecord, []);
  const record = recordState.status === "success" ? recordState.data : null;

  // Today's fixtures, in the viewer's timezone, earliest first.
  const today = useMemo(
    () =>
      matches
        .filter((m) => m.kickoff_utc && relativeDayLabel(m.kickoff_utc, tz) === "Today")
        .sort((a, b) => (a.kickoff_utc ?? "z").localeCompare(b.kickoff_utc ?? "z")),
    [matches, tz],
  );

  // The single best-billed fixture — always something genuinely relevant, never
  // a past kickoff dressed up as an upcoming prediction:
  //   1. a live game, 2. the soonest fixture still to come, 3. the most recent
  //   result to recap, 4. (fallback) the highest-confidence of today's slate.
  const matchOfDay = useMemo(() => {
    const ts = (m: MatchSummary) => (m.kickoff_utc ? Date.parse(m.kickoff_utc) : NaN);
    const now = Date.now();
    const live = matches.find((m) => isLiveNow(m));
    if (live) return live;
    const upcoming = matches
      .filter((m) => m.status !== "finished" && !Number.isNaN(ts(m)) && ts(m) > now)
      .sort((a, b) => ts(a) - ts(b));
    if (upcoming.length) return upcoming[0];
    const recent = matches
      .filter((m) => m.status === "finished" && m.score_home != null && !Number.isNaN(ts(m)))
      .sort((a, b) => ts(b) - ts(a));
    if (recent.length) return recent[0];
    const rank = (c: MatchSummary["confidence"]) =>
      c === "High" ? 3 : c === "Medium" ? 2 : c === "Low" ? 1 : 0;
    return [...today].sort((a, b) => rank(b.confidence) - rank(a.confidence))[0] ?? null;
  }, [today, matches]);

  const alsoToday = useMemo(
    () => today.filter((m) => m.match_id !== matchOfDay?.match_id),
    [today, matchOfDay],
  );

  return (
    <div className="mx-auto max-w-2xl py-8 sm:py-10">
      {/* ===== Greeting ===== */}
      <p className="text-sm font-semibold text-muted">{greeting()}</p>
      <h1 className="mt-1 font-display text-2xl font-extrabold tracking-tight sm:text-3xl">
        {today.length > 0
          ? `${today.length} ${today.length === 1 ? "match" : "matches"} today`
          : "No matches today"}
      </h1>

      {/* ===== Followed team, with a quiet way back to the chooser ===== */}
      <p className="mt-1.5 flex items-center gap-1.5 text-xs text-muted">
        <Flag team={team.name} size={16} />
        Following {team.name}
        <button
          type="button"
          onClick={onChangeCountry}
          className="text-xs font-semibold text-lime-deep hover:underline"
        >
          Change team
        </button>
      </p>

      {/* ===== Jump to any team ===== */}
      <div className="mt-5">
        <TeamSearch teams={teams} />
      </div>

      <IntelPanel sport="football" />

      {/* ===== Match of the day ===== */}
      {matchOfDay && (
        <section className="mt-7">
          <p className="mb-2.5 font-display text-[11px] font-bold uppercase tracking-wider text-muted">
            Match of the day
          </p>
          <MatchOfDayCard match={matchOfDay} tz={tz} />
        </section>
      )}

      {/* ===== Also today ===== */}
      {alsoToday.length > 0 && (
        <section className="mt-7">
          <p className="mb-2.5 font-display text-[11px] font-bold uppercase tracking-wider text-muted">
            Also today
          </p>
          <div className="space-y-2.5">
            {alsoToday.map((m) => (
              <AlsoTodayRow key={m.match_id} match={m} tz={tz} />
            ))}
          </div>
        </section>
      )}

      {/* Empty-today state: still give returning users a way forward. */}
      {matches.length === 0 && (
        <p className="mt-7 rounded-2xl border border-border bg-surface px-4 py-6 text-center text-sm text-muted">
          No fixtures to show right now — check back as the schedule firms up.
        </p>
      )}

      {/* ===== AI record so far (real, verified track record) ===== */}
      {record && record.evaluated_matches > 0 && (
        <p className="mt-8 text-center text-sm text-muted">
          AI record so far: {record.winners_correct}/{record.evaluated_matches} winners
          {" · "}
          {record.exact_score_hits} exact score{record.exact_score_hits === 1 ? "" : "s"}
          {" · "}
          <Link href="/record" className="font-semibold text-lime-deep underline-offset-2 hover:underline">
            Full track record
          </Link>
        </p>
      )}

      <p className="mt-8 text-center text-sm text-muted">
        Looking for more?{" "}
        <Link href="/matches" className="font-semibold text-lime-deep underline-offset-2 hover:underline">
          All matches
        </Link>
        {" · "}
        <Link href="/brackets" className="font-semibold text-lime-deep underline-offset-2 hover:underline">
          Road to the final
        </Link>
      </p>
    </div>
  );
}

/** The big "Match of the day" card. Before kickoff it shows the AI scoreline +
 *  W/D/L bar + plain verdict; once live or finished it promotes the ACTUAL score
 *  and (at full time) how the model's call did. Links to the full match page. */
function MatchOfDayCard({ match, tz }: { match: MatchSummary; tz: string }) {
  const { teams, probabilities, predicted_score } = match;
  const live = isLiveNow(match);
  const finished = match.status === "finished" || (match.status === "in_play" && !live);
  const hasScore = match.score_home != null && match.score_away != null;
  const showActual = (live || finished) && hasScore;
  const call = prematchCall(probabilities, teams);
  const verdict = finished ? predictionVerdict(match) : null;
  const predScore =
    predicted_score && predicted_score.home != null && predicted_score.away != null
      ? `${predicted_score.home}–${predicted_score.away}`
      : null;
  const shownProbs = (live ? match.live_probabilities : null) ?? probabilities;

  // Prediction-history sparklines (Task 6): one-time fetch per match, same
  // active-flag cleanup idiom as MoversPanel (frontend/components/MoversPanel.tsx:39-53).
  const [history, setHistory] = useState<ProbHistoryPoint[] | null>(null);
  useEffect(() => {
    let active = true;
    setHistory(null);
    getProbHistory(match.match_id)
      .then((res) => {
        if (active) setHistory(res.points);
      })
      .catch(() => {
        if (active) setHistory([]);
      });
    return () => {
      active = false;
    };
  }, [match.match_id]);
  const homeSeries = history?.map((p) => p.p_home) ?? [];
  const awaySeries = history?.map((p) => p.p_away) ?? [];
  const homeTrendUp = homeSeries.length >= 2 && homeSeries[homeSeries.length - 1] >= homeSeries[0];
  const awayTrendUp = awaySeries.length >= 2 && awaySeries[awaySeries.length - 1] >= awaySeries[0];

  return (
    <Link
      href={`/match/${match.match_id}`}
      className={`card-hover glass group block rounded-2xl p-5 ${live ? "ring-1 ring-loss/40" : ""}`}
    >
      <div className="mb-4 flex items-center justify-between">
        {live ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-loss/15 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-loss">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-loss" aria-hidden />
            {liveLabel(match)}
          </span>
        ) : finished ? (
          <span className="inline-flex items-center rounded-full bg-surface-2 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide text-muted">
            Full time
          </span>
        ) : match.kickoff_utc ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-draw/15 px-2.5 py-1 text-[11px] font-semibold text-amber-ink">
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" strokeLinecap="round" />
            </svg>
            {kickoffTime(match.kickoff_utc, tz)}
          </span>
        ) : (
          <span />
        )}
        <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
          {match.group ?? match.stage}
        </span>
      </div>

      <div className="mb-5 flex items-center justify-between gap-3">
        <div className="flex min-w-0 flex-1 flex-col items-center gap-2 text-center">
          <Flag team={teams.home} size={52} />
          <span className="truncate font-display text-[15px] font-bold tracking-tight">{teams.home}</span>
          <Sparkline values={homeSeries} tone={homeTrendUp ? "up" : "down"} />
        </div>
        <div className="shrink-0 text-center">
          <p className="font-display text-[11px] font-bold uppercase tracking-wide text-muted">
            {showActual ? (live ? "Live" : "Final") : "AI predicts"}
          </p>
          <p className="mt-0.5 font-display text-3xl font-extrabold tabular-nums tracking-tight">
            {showActual ? formatScore(match.score_home, match.score_away) : (predScore ?? "—")}
          </p>
        </div>
        <div className="flex min-w-0 flex-1 flex-col items-center gap-2 text-center">
          <Flag team={teams.away} size={52} />
          <span className="truncate font-display text-[15px] font-bold tracking-tight">{teams.away}</span>
          <Sparkline values={awaySeries} tone={awayTrendUp ? "up" : "down"} />
        </div>
      </div>

      {probabilities ? (
        <ProbabilityBar
          probabilities={shownProbs ?? probabilities}
          homeLabel={teams.home}
          awayLabel={teams.away}
        />
      ) : (
        <p className="text-sm text-muted">Prediction pending…</p>
      )}

      <div className="mt-4 flex items-start gap-2.5 rounded-xl bg-surface-2 px-3.5 py-3">
        {verdict ? (
          <>
            <span aria-hidden className={`mt-0.5 text-sm font-bold ${verdict.kind === "miss" ? "text-loss" : "text-lime-deep"}`}>
              {verdict.kind === "miss" ? "✕" : "✓"}
            </span>
            <span className="text-[13px] font-medium text-foreground">
              {verdict.kind === "miss"
                ? "Upset — we missed it."
                : verdict.kind === "exact"
                  ? "Exact score — called it!"
                  : "Called it."}
              <BasisTag verdict={verdict} />{" "}
              <span className="font-semibold text-lime-deep">See the result →</span>
            </span>
          </>
        ) : (
          <>
            <svg viewBox="0 0 24 24" className="mt-0.5 h-4 w-4 shrink-0 text-lime-deep" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M13 2 4.5 13H11l-1 9 9.5-12H13l0-8Z" strokeLinejoin="round" />
            </svg>
            <span className="text-[13px] font-medium text-foreground">
              {live ? "In play now." : call ? `${call.label}.` : "AI prediction ready."}{" "}
              <span className="font-semibold text-lime-deep">See why →</span>
            </span>
          </>
        )}
      </div>
      {verdict && <ShootoutNote verdict={verdict} />}
    </Link>
  );
}

/** Compact "Also today" row: paired flags, matchup, then either the kickoff +
 *  pick (upcoming) or the live/final score + how the call did (live/finished). */
function AlsoTodayRow({ match, tz }: { match: MatchSummary; tz: string }) {
  const { teams, probabilities } = match;
  const live = isLiveNow(match);
  const finished = match.status === "finished" || (match.status === "in_play" && !live);
  const hasScore = match.score_home != null && match.score_away != null;
  const showActual = (live || finished) && hasScore;
  const call = prematchCall(probabilities, teams);
  const verdict = finished ? predictionVerdict(match) : null;

  return (
    <Link
      href={`/match/${match.match_id}`}
      className="card-hover glass group flex items-center gap-3 rounded-2xl p-3.5"
    >
      <div className="flex shrink-0 -space-x-1.5">
        <Flag team={teams.home} size={32} />
        <Flag team={teams.away} size={32} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate font-display text-sm font-bold tracking-tight">
          {teams.home} v {teams.away}
        </p>
        <p className="mt-0.5 truncate text-xs text-muted">
          {live ? (
            <span className="font-semibold text-loss">{liveLabel(match)}</span>
          ) : finished ? (
            <span className="font-semibold">Full time</span>
          ) : match.kickoff_utc ? (
            kickoffTime(match.kickoff_utc, tz)
          ) : null}
          {verdict ? (
            <>
              {" · "}
              <span className={`font-semibold ${verdict.kind === "miss" ? "text-loss" : "text-lime-deep"}`}>
                {verdict.kind === "miss" ? "Upset" : "Called it"}
              </span>
              {verdict.shootout && (
                <span className="text-muted"> · {verdict.shootout.winner} on pens</span>
              )}
            </>
          ) : call ? (
            <>
              {(live || match.kickoff_utc) ? " · " : ""}
              <span className={`font-semibold ${call.tone === "draw" ? "text-amber-ink" : "text-lime-deep"}`}>
                {call.label}
              </span>
            </>
          ) : null}
        </p>
      </div>
      {showActual && (
        <span className="shrink-0 font-display text-base font-extrabold tabular-nums">
          {formatScore(match.score_home, match.score_away)}
        </span>
      )}
      <FavoriteStar team={teams.home} />
    </Link>
  );
}
