import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { APP_NAME } from "@/lib/constants";
import { COMPETITIONS, isWiredFootballCompetition } from "@/lib/sports";
import { renderMatchesPage } from "@/app/matches/MatchesPageContent";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ comp: string }>;
}): Promise<Metadata> {
  const { comp } = await params;
  const label = isWiredFootballCompetition(comp) ? COMPETITIONS[comp].label : "Football";
  return {
    title: `${label} fixtures — ${APP_NAME}`,
    description: `Every ${label} fixture, organized by kickoff and match status.`,
  };
}

export default async function CompFixturesPage({
  params,
}: {
  params: Promise<{ comp: string }>;
}) {
  const { comp } = await params;
  if (!isWiredFootballCompetition(comp)) notFound();
  return renderMatchesPage(comp);
}
