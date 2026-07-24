import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { isWiredFootballCompetition } from "@/lib/sports";
import LegacyMatchDetailPage, { generateMetadata as legacyGenerateMetadata } from "@/app/match/[id]/page";

// Floodlight P1 slice p1-s3: wraps app/match/[id]/page.tsx. WC26-only for
// now (see lib/sports.ts's `enabled` flags) -- notFound() guards the body
// only; generateMetadata below runs unguarded, which is fine (metadata for
// an invalid comp is harmless, per the slice's ruling). isWiredFootballCompetition
// also 404s non-football competitions (e.g. nrl) reached via /football/<comp>
// -- NRL keeps its own space. The legacy page only reads params.id, so the
// wider { comp, id } promise passes straight through untouched.
//
// generateMetadata is NOT re-exported as-is: the legacy function hardcodes
// alternates.canonical to `/match/${id}`, a path next.config.mjs now 301s
// straight back to this very page -- a canonical that redirects gets
// discarded by Google. Re-derive it here from the live /football/{comp}/...
// URL this page actually serves.
export async function generateMetadata({
  params,
}: {
  params: Promise<{ comp: string; id: string }>;
}): Promise<Metadata> {
  const { comp, id } = await params;
  const meta = await legacyGenerateMetadata({ params: Promise.resolve({ id }) });
  return { ...meta, alternates: { canonical: `/football/${comp}/match/${id}` } };
}

export default async function CompMatchDetailPage({
  params,
}: {
  params: Promise<{ comp: string; id: string }>;
}) {
  const { comp } = await params;
  if (!isWiredFootballCompetition(comp)) notFound();
  return <LegacyMatchDetailPage params={params} />;
}
