import { notFound } from "next/navigation";
import { isWiredFootballCompetition } from "@/lib/sports";
import LegacyMatchDetailPage from "@/app/match/[id]/page";

export { generateMetadata } from "@/app/match/[id]/page";

// Floodlight P1 slice p1-s3: wraps app/match/[id]/page.tsx. WC26-only for
// now (see lib/sports.ts's `enabled` flags) -- notFound() guards the body
// only; generateMetadata re-exported above runs unguarded, which is fine
// (metadata for an invalid comp is harmless, per the slice's ruling).
// isWiredFootballCompetition also 404s non-football competitions (e.g. nrl)
// reached via /football/<comp> -- NRL keeps its own space. The legacy page
// only reads params.id, so the wider { comp, id } promise passes straight
// through untouched.
export default async function CompMatchDetailPage({
  params,
}: {
  params: Promise<{ comp: string; id: string }>;
}) {
  const { comp } = await params;
  if (!isWiredFootballCompetition(comp)) notFound();
  return <LegacyMatchDetailPage params={params} />;
}
