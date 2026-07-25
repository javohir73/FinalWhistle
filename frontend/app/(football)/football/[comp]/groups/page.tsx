import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { APP_NAME } from "@/lib/constants";
import { COMPETITIONS, isWiredFootballCompetition } from "@/lib/sports";
import { renderGroupsPage } from "@/app/groups/GroupsPageContent";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ comp: string }>;
}): Promise<Metadata> {
  const { comp } = await params;
  const label = isWiredFootballCompetition(comp) ? COMPETITIONS[comp].label : "Football";
  return {
    title: `${label} standings — ${APP_NAME}`,
    description: `${label} group standings and qualification outlook.`,
  };
}

export default async function CompGroupsPage({
  params,
}: {
  params: Promise<{ comp: string }>;
}) {
  const { comp } = await params;
  if (!isWiredFootballCompetition(comp) || !COMPETITIONS[comp].hasGroups) notFound();
  return renderGroupsPage(comp);
}
