import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { COMPETITIONS, isWiredFootballCompetition } from "@/lib/sports";
import { getGroupsServer } from "@/lib/api";
import { getCompetitionTournament } from "@/lib/tournament";
import { StandingsClient } from "@/components/StandingsClient";

// Canonical standings URL for league-format football competitions. WC26 keeps
// its group-table implementation at /football/wc26/groups, even though the
// visible navigation label is the clearer, prototype-aligned “Standings.”

export async function generateMetadata({
  params,
}: {
  params: Promise<{ comp: string }>;
}): Promise<Metadata> {
  const { comp } = await params;
  const label = isWiredFootballCompetition(comp) ? COMPETITIONS[comp].label : "Football";
  return { title: `${label} standings` };
}

export default async function CompStandingsPage({
  params,
}: {
  params: Promise<{ comp: string }>;
}) {
  const { comp } = await params;
  if (!isWiredFootballCompetition(comp) || COMPETITIONS[comp].format !== "league") notFound();

  const [initialGroups, tournament] = await Promise.all([
    getGroupsServer(comp).catch(() => null),
    getCompetitionTournament(comp),
  ]);
  return (
    <StandingsClient comp={comp} initialGroups={initialGroups ?? undefined} tournament={tournament} />
  );
}
