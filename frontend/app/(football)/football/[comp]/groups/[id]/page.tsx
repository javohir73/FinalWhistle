import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { isWiredFootballCompetition } from "@/lib/sports";
import LegacyGroupDetailPage, { generateMetadata as legacyGenerateMetadata } from "@/app/groups/[id]/page";

// Floodlight P1 slice p1-s3: wraps app/groups/[id]/page.tsx. WC26-only guard
// on the body; generateMetadata below runs unguarded (harmless for an
// invalid comp, per the slice's ruling). isWiredFootballCompetition also
// 404s non-football competitions (e.g. nrl) reached via /football/<comp> --
// NRL keeps its own space. The legacy page only reads params.id, so the
// wider { comp, id } promise passes straight through.
//
// generateMetadata is NOT re-exported as-is: the legacy function hardcodes
// alternates.canonical to `/groups/${id}`, a path next.config.mjs now 301s
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
  return { ...meta, alternates: { canonical: `/football/${comp}/groups/${id}` } };
}

export default async function CompGroupDetailPage({
  params,
}: {
  params: Promise<{ comp: string; id: string }>;
}) {
  const { comp } = await params;
  if (!isWiredFootballCompetition(comp)) notFound();
  return <LegacyGroupDetailPage params={params} />;
}
