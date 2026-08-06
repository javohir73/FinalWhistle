"use client";

import { useMemo } from "react";
import Link from "next/link";
import { CompetitionLogo } from "@/components/CompetitionLogo";
import { Eyebrow } from "@/components/Eyebrow";
import { FeatureHero } from "@/components/FeatureHero";
import { MatchCard } from "@/components/MatchCard";
import { StandingsTable } from "@/components/StandingsTable";
import { TeamSearch } from "@/components/TeamSearch";
import { getGroups, getTeams, getUpcomingMatches } from "@/lib/api";
import { COMPETITIONS, type CompetitionId } from "@/lib/sports";
import type { Group, MatchSummary, Team } from "@/lib/types";
import { useFetch } from "@/lib/useFetch";
import { useTimezone } from "@/lib/useTimezone";
import { isLiveNow } from "@/lib/liveLabel";

interface CompetitionHomeProps {
  competition: CompetitionId;
  initialTeams?: Team[];
  initialGroups?: Group[];
  initialMatches?: MatchSummary[];
}

/** League home built from one competition-scoped payload.
 *
 * It deliberately does not fall back to global football data. If a registered
 * league's season feed has not been loaded yet, the page stays useful as a
 * navigation destination and explains the empty state instead of displaying
 * another competition's clubs.
 */
export function CompetitionHome({
  competition,
  initialTeams,
  initialGroups,
  initialMatches,
}: CompetitionHomeProps) {
  const config = COMPETITIONS[competition];
  const { tz } = useTimezone();
  const teamsState = useFetch(
    () => getTeams(competition),
    [competition],
    undefined,
    initialTeams,
  );
  const groupsState = useFetch(
    () => getGroups(competition),
    [competition],
    30_000,
    initialGroups,
  );
  const matchesState = useFetch(
    () => getUpcomingMatches(competition),
    [competition],
    30_000,
    initialMatches,
  );

  const teams = useMemo(
    () => (teamsState.status === "success" ? teamsState.data : initialTeams ?? []),
    [initialTeams, teamsState],
  );
  const groups = useMemo(
    () => (groupsState.status === "success" ? groupsState.data : initialGroups ?? []),
    [groupsState, initialGroups],
  );
  const matches = useMemo(
    () => (matchesState.status === "success" ? matchesState.data : initialMatches ?? []),
    [initialMatches, matchesState],
  );
  const feature = useMemo(() => {
    const now = Date.now();
    const scheduled = matches
      .filter((match) => {
        if (match.status !== "scheduled" || !match.kickoff_utc) return false;
        const kickoff = Date.parse(match.kickoff_utc);
        return !Number.isNaN(kickoff) && kickoff > now;
      })
      .sort((a, b) => (a.kickoff_utc ?? "").localeCompare(b.kickoff_utc ?? ""));
    return matches.find((match) => isLiveNow(match)) ?? scheduled[0] ?? matches[0] ?? null;
  }, [matches]);
  const alsoOn = matches
    .filter((match) => match.match_id !== feature?.match_id)
    .slice(0, 4);
  const table = groups[0]?.standings ?? [];
  const basePath = config.basePath;

  if (teams.length === 0 && groups.length === 0 && matches.length === 0) {
    return (
      <div className="mx-auto max-w-2xl py-8 sm:py-10">
        <header className="flex items-center gap-3">
          <CompetitionLogo competition={competition} size={48} />
          <div>
            <Eyebrow>{config.shortLabel}</Eyebrow>
            <h1 className="font-display text-3xl font-extrabold tracking-tight">
              {config.label}
            </h1>
          </div>
        </header>
        <section className="glass mt-8 rounded-2xl p-6 text-center">
          <h2 className="font-display text-xl font-bold">Season data is not loaded yet</h2>
          <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted">
            {config.label} stays separate from the other competitions, so no World Cup or
            Premier League teams are shown here while its fixtures and standings are unavailable.
          </p>
          <Link
            href="/play"
            className="mt-5 inline-flex min-h-[44px] items-center rounded-xl bg-win px-4 font-display text-sm font-bold text-pitch"
          >
            Browse the Play slate
          </Link>
        </section>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl py-8 sm:py-10">
      <header className="flex items-center gap-3">
        <CompetitionLogo competition={competition} size={48} />
        <div>
          <Eyebrow>{config.shortLabel}</Eyebrow>
          <h1 className="font-display text-3xl font-extrabold tracking-tight">
            {config.label}
          </h1>
          <p className="mt-0.5 text-sm text-muted">
            {teams.length} clubs · {matches.length} fixtures
          </p>
        </div>
      </header>

      <div className="mt-6">
        <TeamSearch teams={teams} teamBasePath={`${basePath}/team`} />
      </div>

      <div className="mt-7">
        <FeatureHero
          match={feature}
          comp={competition}
          tz={tz}
          badge="club"
          href={feature ? `${basePath}/match/${feature.match_id}` : null}
          eyebrow="Next up"
        />
      </div>

      {alsoOn.length > 0 && (
        <section className="mt-7" aria-labelledby={`${competition}-also-on`}>
          <div className="mb-3 flex items-center justify-between">
            <h2
              id={`${competition}-also-on`}
              className="font-display text-label font-semibold uppercase tracking-wider text-muted"
            >
              Also on
            </h2>
            <Link
              href={`${basePath}/fixtures`}
              className="text-xs font-semibold text-lime-deep hover:underline"
            >
              All fixtures →
            </Link>
          </div>
          <div className="flex flex-col gap-2.5">
            {alsoOn.map((match) => (
              <MatchCard
                key={match.match_id}
                match={match}
                tz={tz}
                variant="compact"
                badge="club"
                href={`${basePath}/match/${match.match_id}`}
              />
            ))}
          </div>
        </section>
      )}

      {table.length > 0 && (
        <section className="mt-8" aria-labelledby={`${competition}-standings`}>
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2
                id={`${competition}-standings`}
                className="font-display text-xl font-extrabold"
              >
                Standings
              </h2>
              <p className="text-xs text-muted">Clubs stay scoped to {config.label}.</p>
            </div>
            <Link
              href={`${basePath}/standings`}
              className="text-xs font-semibold text-lime-deep hover:underline"
            >
              Full table →
            </Link>
          </div>
          <div className="glass rounded-2xl p-4">
            <StandingsTable
              standings={table}
              zones={config.zones}
              badge="club"
              teamBasePath={`${basePath}/team`}
            />
          </div>
        </section>
      )}
    </div>
  );
}
