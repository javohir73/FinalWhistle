"use client";

import { useMemo } from "react";
import Link from "next/link";
import { Flag } from "@/components/Flag";
import { FormStrip } from "@/components/FormStrip";
import { QualificationBar } from "@/components/QualificationBar";
import { LocationPicker } from "@/components/LocationPicker";
import { UserPredictionCard } from "@/components/UserPredictionCard";
import { useFetch } from "@/lib/useFetch";
import { useMatchPicks } from "@/lib/useMatchPicks";
import { useTimezone } from "@/lib/useTimezone";
import { getTeam } from "@/lib/api";
import { pct } from "@/lib/format";
import type { Group, MatchSummary, Team, TournamentOdds } from "@/lib/types";

const NAV = [
  { href: "/matches", label: "All matches" },
  { href: "/groups", label: "Groups" },
  { href: "/brackets", label: "Bracket" },
  { href: "/my-bracket", label: "My Bracket" },
  { href: "/leaderboard", label: "Leaderboard" },
];

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface/50 px-3 py-3 text-center">
      <div className="font-display text-2xl font-extrabold text-win">{value}</div>
      <div className="mt-0.5 text-[11px] uppercase tracking-wider text-muted">{label}</div>
    </div>
  );
}

/**
 * The personalized hub shown once a country's forecast has been revealed:
 * outlook, odds, strengths/weaknesses, that nation's fixtures as interactive
 * prediction cards, and its group table — plus links into the full platform.
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

  return (
    <div className="py-8 sm:py-10">
      {/* ===== Header ===== */}
      <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <span className="grid shrink-0 place-items-center rounded-2xl bg-win/10 p-2.5 ring-1 ring-win/30">
            <Flag team={team.name} size={56} />
          </span>
          <div>
            <h1 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
              {team.name}
            </h1>
            <p className="mt-1 text-sm text-muted">
              {group ? `Group ${group.name}` : "Group TBC"}
              {team.confederation ? ` · ${team.confederation}` : ""}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onChangeCountry}
          className="inline-flex items-center gap-1.5 self-start rounded-lg border border-border bg-surface/60 px-3 py-2 text-sm font-medium text-muted transition hover:border-win/40 hover:text-foreground sm:self-auto"
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5" strokeLinejoin="round" />
          </svg>
          Change country
        </button>
      </header>

      {/* Secondary nav into the full platform */}
      <nav className="mt-5 flex flex-wrap gap-2">
        {NAV.map((n) => (
          <Link
            key={n.href}
            href={n.href}
            className="rounded-full border border-border bg-surface/60 px-3.5 py-1.5 text-sm text-muted transition hover:border-win/40 hover:text-foreground"
          >
            {n.label}
          </Link>
        ))}
      </nav>

      {/* ===== Key numbers ===== */}
      <div className="mt-7 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="FIFA rank" value={team.fifa_rank != null ? `#${team.fifa_rank}` : "—"} />
        <Stat label="Elo rating" value={team.elo_rating != null ? `${Math.round(team.elo_rating)}` : "—"} />
        <Stat label="Reach knockouts" value={teamOdds?.make_knockout != null ? pct(teamOdds.make_knockout) : "—"} />
        <Stat label="Win title" value={teamOdds?.win_title != null ? pct(teamOdds.win_title) : "—"} />
      </div>

      {/* ===== Outlook + strengths/weaknesses ===== */}
      <section className="mt-7 grid gap-4 lg:grid-cols-3">
        <div className="glass rounded-2xl p-5 lg:col-span-1">
          <h2 className="font-display text-sm font-bold uppercase tracking-wider text-win">AI outlook</h2>
          {outlook && outlook.length > 0 ? (
            <p className="mt-2.5 text-sm leading-relaxed text-foreground/90">
              The model gives <span className="font-semibold">{team.name}</span> {outlook.join(", ")}.
            </p>
          ) : (
            <p className="mt-2.5 text-sm text-muted">
              Tournament odds for {team.name} will appear once the simulation runs.
            </p>
          )}
          {profile && profile.recent_form.length > 0 && (
            <div className="mt-4">
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted">Recent form</p>
              <FormStrip form={profile.recent_form} />
            </div>
          )}
          <Link
            href={`/team/${team.id}`}
            className="mt-4 inline-block text-sm font-medium text-win underline-offset-2 hover:underline"
          >
            Full team profile →
          </Link>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:col-span-2">
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
      </section>

      {/* ===== Prediction cards ===== */}
      <section className="mt-9">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-xl font-extrabold tracking-tight">
            Your predictions for {team.name}
          </h2>
          <LocationPicker />
        </div>
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
      </section>

      {/* ===== Group table ===== */}
      {group && (
        <section className="mt-9">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-display text-xl font-extrabold tracking-tight">Group {group.name}</h2>
            <Link href={`/groups/${group.id}`} className="text-sm font-medium text-win underline-offset-2 hover:underline">
              Full group →
            </Link>
          </div>
          <div className="overflow-hidden rounded-2xl border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-surface-2/50 text-left text-[11px] uppercase tracking-wider text-muted">
                  <th className="px-3 py-2 font-semibold">Team</th>
                  <th className="px-3 py-2 text-right font-semibold">Pts</th>
                  <th className="px-3 py-2 text-right font-semibold">Qualify</th>
                </tr>
              </thead>
              <tbody>
                {group.standings.map((s) => {
                  const isTeam = s.team_id === team.id;
                  return (
                    <tr
                      key={s.team_id}
                      className={isTeam ? "bg-win/10" : "border-t border-border/60"}
                    >
                      <td className="px-3 py-2.5">
                        <span className="flex items-center gap-2">
                          <Flag team={s.team} size={20} />
                          <span className={isTeam ? "font-bold" : "font-medium"}>{s.team}</span>
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums">{s.projected_points}</td>
                      <td className="px-3 py-2.5">
                        <div className="flex justify-end">
                          <QualificationBar prob={s.qualification_prob} />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
