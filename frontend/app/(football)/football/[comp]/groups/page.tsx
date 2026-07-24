import { notFound } from "next/navigation";
import { isWiredFootballCompetition } from "@/lib/sports";
import LegacyGroupsPage from "@/app/groups/page";

export { metadata } from "@/app/groups/page";

// Floodlight P1 slice p1-s3: wraps app/groups/page.tsx -- WC26 only (see
// lib/sports.ts's `enabled` flags). isWiredFootballCompetition also 404s
// non-football competitions (e.g. nrl) reached via /football/<comp> -- NRL
// keeps its own space. The legacy component takes no params.
export default async function CompGroupsPage({
  params,
}: {
  params: Promise<{ comp: string }>;
}) {
  const { comp } = await params;
  if (!isWiredFootballCompetition(comp)) notFound();
  return <LegacyGroupsPage />;
}
