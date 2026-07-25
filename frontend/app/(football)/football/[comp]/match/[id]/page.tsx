import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { isWiredFootballCompetition } from "@/lib/sports";
import {
  generateMatchMetadata,
  renderMatchDetailPage,
} from "@/app/match/[id]/MatchPageContent";

// One scoped match surface for every wired football competition. Both metadata
// and page data validate that the match belongs to the URL's competition.
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
  const meta = isWiredFootballCompetition(comp)
    ? await generateMatchMetadata(Promise.resolve({ id }), comp)
    : await generateMatchMetadata(Promise.resolve({ id }));
  return { ...meta, alternates: { canonical: `/football/${comp}/match/${id}` } };
}

export default async function CompMatchDetailPage({
  params,
}: {
  params: Promise<{ comp: string; id: string }>;
}) {
  const { comp } = await params;
  if (!isWiredFootballCompetition(comp)) notFound();
  return renderMatchDetailPage(params, comp);
}
