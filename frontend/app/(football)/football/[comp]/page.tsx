import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { COMPETITIONS, isWiredFootballCompetition } from "@/lib/sports";
import { APP_NAME } from "@/lib/constants";
import {
  getGroupsServer,
  getTeamsServer,
  getUpcomingMatchesServer,
} from "@/lib/api";
import { CompetitionHome } from "@/components/CompetitionHome";
import { renderHomePage } from "@/app/HomePageContent";

// The football scope 404s non-football competitions (for example NRL) that
// reach /football/<comp>; NRL keeps its own namespace. WC26 reuses the
// existing tournament home, while league-format competitions use the scoped
// league home below. A registered league with no loaded feed gets an honest
// empty state rather than another competition's teams.
export async function generateMetadata({
  params,
}: {
  params: Promise<{ comp: string }>;
}): Promise<Metadata> {
  const { comp } = await params;
  const label = isWiredFootballCompetition(comp) ? COMPETITIONS[comp].label : "Football";
  return {
    title: `${label} predictions — ${APP_NAME}`,
    description: `Fixtures, standings, and explainable predictions for ${label}.`,
  };
}

export default async function CompHomePage({
  params,
}: {
  params: Promise<{ comp: string }>;
}) {
  const { comp } = await params;
  if (!isWiredFootballCompetition(comp)) notFound();
  if (COMPETITIONS[comp].format === "knockout") {
    return renderHomePage(comp);
  }

  const [teams, groups, matches] = await Promise.all([
    getTeamsServer(comp).catch(() => null),
    getGroupsServer(comp).catch(() => null),
    getUpcomingMatchesServer(comp).catch(() => null),
  ]);
  return (
    <CompetitionHome
      competition={comp}
      initialTeams={teams ?? undefined}
      initialGroups={groups ?? undefined}
      initialMatches={matches ?? undefined}
    />
  );
}
