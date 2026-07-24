import { notFound } from "next/navigation";
import { isWiredFootballCompetition } from "@/lib/sports";
import LegacyGroupDetailPage from "@/app/groups/[id]/page";

export { generateMetadata } from "@/app/groups/[id]/page";

// Floodlight P1 slice p1-s3: wraps app/groups/[id]/page.tsx. WC26-only guard
// on the body; generateMetadata re-exported above runs unguarded (harmless
// for an invalid comp, per the slice's ruling). isWiredFootballCompetition
// also 404s non-football competitions (e.g. nrl) reached via
// /football/<comp> -- NRL keeps its own space. The legacy page only reads
// params.id, so the wider { comp, id } promise passes straight through.
export default async function CompGroupDetailPage({
  params,
}: {
  params: Promise<{ comp: string; id: string }>;
}) {
  const { comp } = await params;
  if (!isWiredFootballCompetition(comp)) notFound();
  return <LegacyGroupDetailPage params={params} />;
}
