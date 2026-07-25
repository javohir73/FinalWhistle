import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { COMPETITIONS, isWiredFootballCompetition } from "@/lib/sports";
import LegacyGroupDetailPage, { generateMetadata as legacyGenerateMetadata } from "@/app/groups/[id]/page";

// The group-detail implementation is a World Cup surface. The hasGroups guard
// prevents a league URL from ever rendering WC26 data.
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
  if (!isWiredFootballCompetition(comp) || !COMPETITIONS[comp].hasGroups) notFound();
  return <LegacyGroupDetailPage params={params} />;
}
