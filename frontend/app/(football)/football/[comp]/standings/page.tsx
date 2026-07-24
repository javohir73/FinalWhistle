import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { COMPETITIONS, isWiredFootballCompetition } from "@/lib/sports";
import { getGroupsServer } from "@/lib/api";
import { getTournament } from "@/lib/tournament";
import { StandingsClient } from "@/components/StandingsClient";

// Floodlight P2: the canonical standings URL for league-format football
// competitions. It has no legacy equivalent (WC26's standings live at /groups),
// so this is the single URL -- no redirect, no legacy page. Dormant in P2:
// isWiredFootballCompetition already 404s the disabled comps (epl/laliga/
// bundesliga stay enabled:false until their data lands) and non-football ones;
// the `format === "league"` check additionally 404s WC26, whose enabled
// knockout format belongs on /groups, not here. So today this path 404s for
// everything -- exactly the dormant state P2 wants.

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
    getGroupsServer().catch(() => null),
    getTournament(),
  ]);
  return (
    <StandingsClient comp={comp} initialGroups={initialGroups ?? undefined} tournament={tournament} />
  );
}
