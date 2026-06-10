"use client";

import { useState } from "react";
import { CountryOnboarding } from "@/components/CountryOnboarding";
import { AICalculationReveal } from "@/components/AICalculationReveal";
import { PersonalizedCountryHome } from "@/components/PersonalizedCountryHome";
import { useSelectedCountry } from "@/lib/useSelectedCountry";
import { useFetch } from "@/lib/useFetch";
import { getTeams, getGroups, getUpcomingMatches, getKnockoutOdds } from "@/lib/api";
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
  const groupsState = useFetch(getGroups, [], undefined, initialGroups);
  const matchesState = useFetch(getUpcomingMatches, [], undefined, initialMatches);
  const oddsState = useFetch(getKnockoutOdds, [], undefined, initialOdds);

  const teams = teamsState.status === "success" ? teamsState.data : initialTeams ?? [];
  const groups = groupsState.status === "success" ? groupsState.data : initialGroups ?? [];
  const matches = matchesState.status === "success" ? matchesState.data : initialMatches ?? [];
  const odds = oddsState.status === "success" ? oddsState.data : initialOdds ?? [];

  // Avoid an SSR/first-paint mismatch: render a quiet shell until localStorage
  // has been read (matches the server render, which can't know the selection).
  if (!hydrated) {
    return (
      <div className="mx-auto max-w-2xl py-16 sm:py-24" aria-hidden>
        <div className="mx-auto h-7 w-44 rounded-full skeleton" />
        <div className="mx-auto mt-5 h-12 w-3/4 rounded-2xl skeleton" />
        <div className="mt-9 h-40 rounded-2xl skeleton" />
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

  if (!changing && selection?.prediction_revealed && selectedTeam) {
    return (
      <PersonalizedCountryHome
        team={selectedTeam}
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
