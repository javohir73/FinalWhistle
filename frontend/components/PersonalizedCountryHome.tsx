"use client";

import { useMemo } from "react";
import Link from "next/link";
import { Flag } from "@/components/Flag";
import { FormStrip } from "@/components/FormStrip";
import { GroupTable } from "@/components/GroupTable";
import { LocationPicker } from "@/components/LocationPicker";
import { MatchCard } from "@/components/MatchCard";
import { UserPredictionCard } from "@/components/UserPredictionCard";
import { useFetch } from "@/lib/useFetch";
import { useMatchPicks } from "@/lib/useMatchPicks";
import { useTimezone } from "@/lib/useTimezone";
import { getTeam, getModelRecord } from "@/lib/api";
import { pct } from "@/lib/format";
import type { Group, MatchSummary, Team, TournamentOdds } from "@/lib/types";

/**
 * The personalized hub shown once a country's forecast has been revealed.
 * Top-to-bottom: header → AI outlook hero (the main payoff) → that nation's
 * upcoming fixtures as read-only AI prediction cards → a collapsible "More
 * about" drawer (strengths/weaknesses, form, group table, profile links) →
 * a collapsible "Make your own call" drawer with interactive pick cards.
 */
export function PersonalizedCountryHome({
  team,
  groups,
  odds,
  matches,
  onChangeCountry,
}: {
  team: Team;
  groups: Group[];
  odds: TournamentOdds[];
  matches: MatchSummary[];
  onChangeCountry: () => void;
}) {
  const { tz } = useTimezone();
  const { picks, setPick } = useMatchPicks();
  const profileState = useFetch(() => getTeam(team.id), [team.id]);
  const profile = profileState.status === "success" ? profileState.data : null;
  const recordState = useFetch(getModelRecord, []);
  const record = recordState.status === "success" ? recordState.data : null;

  const group = useMemo(
    () => groups.find((g) => g.standings.some((s) => s.team_id === team.id)) ?? null,
    [groups, team.id],
  );
  const teamOdds = useMemo(
    () => odds.find((o) => o.team_id === team.id) ?? null,
    [odds, team.id],
  );
  const teamMatches = useMemo(
    () =>
      matches
        .filter((m) => m.teams.home === team.name || m.teams.away === team.name)
        .sort((a, b) => (a.kickoff_utc ?? "z").localeCompare(b.kickoff_utc ?? "z")),
    [matches, team.name],
  );

  const outlook = useMemo(() => {
    if (!teamOdds) return null;
    const bits: string[] = [];
    if (teamOdds.make_knockout != null)
      bits.push(`${pct(teamOdds.make_knockout)} to reach the knockouts`);
    if (teamOdds.reach_final != null && teamOdds.reach_final >= 0.03)
      bits.push(`${pct(teamOdds.reach_final)} to reach the final`);
    if (teamOdds.win_title != null && teamOdds.win_title >= 0.01)
      bits.push(`${pct(teamOdds.win_title)} to lift the trophy`);
    return bits;
  }, [teamOdds]);

  const hasOutlook = Boolean(outlook && outlook.length > 0 && teamOdds);

  return (
    <div className="py-8 sm:py-10">
      {/* ===== A. Header ===== */}
      <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-4">
          <span className="grid shrink-0 place-items-center rounded-2xl bg-win/10 p-2.5 ring-1 ring-win/30">
            <Flag team={team.name} size={56} />
          </span>
          <div className="min-w-0">
            <h1 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
              {team.name}
            </h1>
            <p className="mt-1 text-sm text-muted">
              {/* group.name is already "Group A" — no extra prefix */}
              {group ? group.name : "Group TBC"}
              {team.confederation ? ` · ${team.confederation}` : ""}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onChangeCountry}
          className="inline-flex shrink-0 items-center gap-1.5 self-start rounded-lg border border-border bg-surface/60 px-3 py-2 text-sm font-medium text-muted transition hover:border-win/40 hover:text-foreground sm:self-auto"
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5" strokeLinejoin="round" />
          </svg>
          Change country
        </button>
      </header>

      {/* ===== C. AI outlook hero — the main payoff ===== */}
      <section className="mt-7 glass rounded-2xl p-5 sm:p-6">
        <h2 className="font-display text-sm font-bold uppercase tracking-wider text-win">AI outlook</h2>
        {hasOutlook ? (
          <>
            <p className="mt-3 font-display text-xl font-extrabold leading-snug tracking-tight sm:text-2xl">
              Our AI gives <span className="text-win">{team.name}</span>{" "}
              {teamOdds?.make_knockout == null
                ? "a fighting chance in the tournament"
                : teamOdds.make_knockout >= 0.5
                  ? "a strong chance to reach the knockouts"
                  : "a shot at the knockouts"}
              {teamOdds?.win_title != null && teamOdds.win_title >= 0.01 && (
                <>
                  {" "}and a{" "}
                  <span className="text-win">{pct(teamOdds.win_title)}</span> title chance
                </>
              )}
              .
            </p>
            <div className="mt-4 flex flex-wrap gap-3">
              {teamOdds?.make_knockout != null && (
                <div className="min-w-0 rounded-xl border border-border bg-surface/50 px-4 py-3 text-center">
                  <div className="font-display text-2xl font-extrabold text-win sm:text-3xl">
                    {pct(teamOdds.make_knockout)}
                  </div>
                  <div className="mt-0.5 text-[11px] uppercase tracking-wider text-muted">Reach knockouts</div>
                </div>
              )}
              {teamOdds?.reach_final != null && teamOdds.reach_final >= 0.03 && (
                <div className="min-w-0 rounded-xl border border-border bg-surface/50 px-4 py-3 text-center">
                  <div className="font-display text-2xl font-extrabold text-win sm:text-3xl">
                    {pct(teamOdds.reach_final)}
                  </div>
                  <div className="mt-0.5 text-[11px] uppercase tracking-wider text-muted">Reach final</div>
                </div>
              )}
              {teamOdds?.win_title != null && teamOdds.win_title >= 0.01 && (
                <div className="min-w-0 rounded-xl border border-border bg-surface/50 px-4 py-3 text-center">
                  <div className="font-display text-2xl font-extrabold text-win sm:text-3xl">
                    {pct(teamOdds.win_title)}
                  </div>
                  <div className="mt-0.5 text-[11px] uppercase tracking-wider text-muted">Win title</div>
                </div>
              )}
            </div>
          </>
        ) : (
          <p className="mt-3 text-sm text-muted">
            We&apos;re still loading the full tournament outlook for this team.
          </p>
        )}
        {record && record.evaluated_matches > 0 && (
          <p className="mt-4 text-xs text-muted">
            AI record so far: {record.winners_correct}/{record.evaluated_matches} winners, {record.exact_score_hits} exact scores.
          </p>
        )}
      </section>

      {/* ===== D. Upcoming matches with AI predictions ===== */}
      <section className="mt-9">
        <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <h2 className="font-display text-xl font-extrabold tracking-tight">
              {team.name}&apos;s upcoming matches
            </h2>
            <p className="mt-1 text-sm text-muted">AI prediction for every fixture.</p>
          </div>
          {/* Full width on mobile (the picker's banner is wide); compact beside the heading on sm+ */}
          <div className="w-full min-w-0 sm:w-auto">
            <LocationPicker />
          </div>
        </div>
        {teamMatches.length > 0 ? (
          <div className="grid gap-3 sm:grid-cols-2">
            {teamMatches.map((m) => (
              <MatchCard key={m.match_id} match={m} tz={tz} />
            ))}
          </div>
        ) : (
          <p className="rounded-xl border border-border bg-surface/50 px-4 py-6 text-center text-sm text-muted">
            No scheduled fixtures for {team.name} yet — check back as the schedule firms up.
          </p>
        )}
      </section>

      {/* ===== E. More about {team} (collapsed by default) ===== */}
      <details className="group mt-9 overflow-hidden rounded-2xl border border-border bg-surface/50">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-4 font-display font-bold tracking-tight [&::-webkit-details-marker]:hidden sm:p-5">
          <span>More about {team.name}</span>
          <svg
            viewBox="0 0 24 24"
            className="h-4 w-4 shrink-0 text-muted transition-transform duration-200 group-open:rotate-180"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </summary>

        <div className="border-t border-border p-4 sm:p-5">
          {/* Strengths + Weak points */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-2xl border border-border bg-surface/50 p-5">
              <h3 className="flex items-center gap-2 font-display text-sm font-bold text-win">
                <span className="text-base">↑</span> Strengths
              </h3>
              <ul className="mt-3 space-y-2 text-sm text-foreground/90">
                {profile?.strengths.length ? (
                  profile.strengths.map((s, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-win" />{s}
                    </li>
                  ))
                ) : (
                  <li className="text-muted">{profileState.status === "loading" ? "Analyzing…" : "—"}</li>
                )}
              </ul>
            </div>
            <div className="rounded-2xl border border-border bg-surface/50 p-5">
              <h3 className="flex items-center gap-2 font-display text-sm font-bold text-loss">
                <span className="text-base">↓</span> Weak points
              </h3>
              <ul className="mt-3 space-y-2 text-sm text-foreground/90">
                {profile?.weaknesses.length ? (
                  profile.weaknesses.map((s, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-loss" />{s}
                    </li>
                  ))
                ) : (
                  <li className="text-muted">{profileState.status === "loading" ? "Analyzing…" : "—"}</li>
                )}
              </ul>
            </div>
          </div>

          {/* Recent form */}
          {profile && profile.recent_form.length > 0 && (
            <div className="mt-5">
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted">Recent form</p>
              <FormStrip form={profile.recent_form} />
            </div>
          )}

          {/* Small stats line */}
          <p className="mt-5 text-sm text-muted">
            FIFA rank {team.fifa_rank != null ? `#${team.fifa_rank}` : "—"} · Elo{" "}
            {team.elo_rating != null ? Math.round(team.elo_rating) : "—"}
          </p>

          {/* Group table */}
          {group && (
            <div className="mt-5">
              <p className="mb-2 text-sm text-muted">Projected to finish in {group.name}.</p>
              <div className="glass rounded-2xl p-4 sm:p-5">
                <GroupTable standings={group.standings} highlightTeamId={team.id} />
              </div>
            </div>
          )}

          {/* Links */}
          <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2">
            {group && (
              <Link
                href={`/groups/${group.id}`}
                className="text-sm font-medium text-win underline-offset-2 hover:underline"
              >
                Full group →
              </Link>
            )}
            <Link
              href={`/team/${team.id}`}
              className="text-sm font-medium text-win underline-offset-2 hover:underline"
            >
              Full team profile →
            </Link>
          </div>
        </div>
      </details>

      {/* ===== F. Make your own call (collapsed by default) ===== */}
      <details className="group mt-7 overflow-hidden rounded-2xl border border-border bg-surface/50">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-4 font-display font-bold tracking-tight [&::-webkit-details-marker]:hidden sm:p-5">
          <span>Make your own call</span>
          <svg
            viewBox="0 0 24 24"
            className="h-4 w-4 shrink-0 text-muted transition-transform duration-200 group-open:rotate-180"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </summary>

        <div className="border-t border-border p-4 sm:p-5">
          <p className="mb-4 text-sm text-muted">
            Think the AI&apos;s got it wrong? Pick each result and see how your calls compare to the model.
          </p>
          {teamMatches.length > 0 ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {teamMatches.map((m) => (
                <UserPredictionCard
                  key={m.match_id}
                  match={m}
                  country={team.name}
                  pick={picks[m.match_id]}
                  onPick={(pk) => setPick(m.match_id, pk)}
                  tz={tz}
                />
              ))}
            </div>
          ) : (
            <p className="rounded-xl border border-border bg-surface/50 px-4 py-6 text-center text-sm text-muted">
              No scheduled fixtures for {team.name} yet — check back as the schedule firms up.
            </p>
          )}
        </div>
      </details>
    </div>
  );
}
