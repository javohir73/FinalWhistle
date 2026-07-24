"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { CountryOnboarding } from "@/components/CountryOnboarding";
import { AICalculationReveal } from "@/components/AICalculationReveal";
import { TeamSearch } from "@/components/TeamSearch";
import { Flag } from "@/components/Flag";
import { Eyebrow } from "@/components/Eyebrow";
import { FeatureHero } from "@/components/FeatureHero";
import { MatchCard } from "@/components/MatchCard";
import { IntelPanel } from "@/components/IntelPanel";
import { RetentionBridge } from "@/components/RetentionBridge";
import { useSelectedCountry } from "@/lib/useSelectedCountry";
import { useFetch } from "@/lib/useFetch";
import { useTimezone } from "@/lib/useTimezone";
import { getTeams, getGroups, getUpcomingMatches, getKnockoutOdds, getModelRecord } from "@/lib/api";
import { isLiveNow } from "@/lib/liveLabel";
import { relativeDayLabel } from "@/lib/datetime";
import { competitionFromPathname } from "@/lib/sports";
import type { Group, MatchSummary, Team, TournamentOdds } from "@/lib/types";

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
          // Root cause of the "loads pre-scrolled" bug: the AI-forecast reveal
          // is a tall (~700-900px) layout whose dismiss controls (the whole
          // section is clickable, plus an explicit "Skip" button) sit well
          // down the page — scrolling to reach them is the normal way to
          // interact with it. Reset scroll exactly once, right here at the
          // reveal→dashboard transition, so the much-shorter dashboard that
          // swaps in doesn't inherit that scrollY. Doing it here (rather than
          // on every HomeDashboard mount) means a returning user whose
          // `prediction_revealed` is already persisted — e.g. navigating away
          // from "/" and hitting Back — remounts straight into the dashboard
          // without this firing and stomping the browser's native scroll
          // restoration.
          window.scrollTo(0, 0);
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
      <>
        <RetentionBridge matches={matches} />
        <HomeDashboard
          team={selectedTeam}
          teams={teams}
          groups={groups}
          odds={odds}
          matches={matches}
          onChangeCountry={() => setChanging(true)}
        />
      </>
    );
  }

  return (
    <>
      <RetentionBridge matches={matches} />
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
    </>
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
 * "Today's movers" panel (biggest probability swings), the Floodlight
 * FeatureHero ("tonight's feature"), and compact "also on" rows. All real,
 * already-loaded data.
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
  // Which competition's terms/accent the hero wears. "/" resolves to WC26 (the
  // only enabled competition today); the /football/[comp] wrappers resolve their
  // own once P2 enables the leagues.
  const comp = competitionFromPathname(usePathname());

  // NOTE: scroll reset for the reveal→dashboard transition lives in
  // HomeExperience's AICalculationReveal onComplete, not here — see the
  // comment there. A mount effect here would also fire on a plain remount
  // (e.g. navigating away from "/" and Back, with `prediction_revealed`
  // already persisted), stomping the browser's native scroll restoration.

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

  // The FeatureHero's "tonight's feature": the soonest upcoming scheduled
  // fixture, else a live one. Never a past kickoff dressed up as upcoming --
  // when neither exists the hero renders its own honest empty state.
  const feature = useMemo(() => {
    const ts = (m: MatchSummary) => (m.kickoff_utc ? Date.parse(m.kickoff_utc) : NaN);
    const now = Date.now();
    const upcoming = matches
      .filter((m) => m.status === "scheduled" && !Number.isNaN(ts(m)) && ts(m) > now)
      .sort((a, b) => ts(a) - ts(b));
    if (upcoming.length) return upcoming[0];
    return matches.find((m) => isLiveNow(m)) ?? null;
  }, [matches]);

  const alsoToday = useMemo(
    () => today.filter((m) => m.match_id !== feature?.match_id),
    [today, feature],
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

      {/* ===== Tonight's feature (Floodlight FeatureHero) ===== */}
      <div className="mt-7">
        <FeatureHero match={feature} comp={comp} tz={tz} />
      </div>

      {/* ===== Also on ===== */}
      {alsoToday.length > 0 && (
        <section className="mt-7">
          <div className="mb-2.5">
            <Eyebrow tone="muted">Also on</Eyebrow>
          </div>
          <div className="flex flex-col gap-2.5">
            {alsoToday.map((m) => (
              <MatchCard key={m.match_id} match={m} tz={tz} variant="compact" />
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

      {/* ===== Beat the AI entry point (design doc: League Score Predictions,
       *  2026-07-24) -- same glass-card teaser idiom as /nrl/tips's "Finals
       *  race" card and /nrl's "State of Origin" card. ===== */}
      <Link href="/tips" className="card-hover glass mt-7 block rounded-2xl p-4 transition">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
              Beat the AI
            </p>
            <p className="mt-1 font-display text-lg font-extrabold">Predict the Premier League scoreline</p>
            <p className="mt-1 text-xs text-muted">Score picks, matchweek leaderboards, share your record.</p>
          </div>
          <span className="shrink-0 text-xs font-semibold text-lime-deep">Play now →</span>
        </div>
      </Link>

      {/* ===== AI record so far (real, verified track record) ===== */}
      {record && record.evaluated_matches > 0 && (
        <p className="mt-8 text-center text-sm text-muted">
          ML model record so far: {record.winners_correct}/{record.evaluated_matches} winners
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
