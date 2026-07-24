import { notFound } from "next/navigation";
import { isWiredFootballCompetition } from "@/lib/sports";
import LegacyMatchesPage from "@/app/matches/page";

export { metadata } from "@/app/matches/page";

// Floodlight P1 slice p1-s3: wraps (does not move) app/matches/page.tsx --
// WC26 is the only enabled competition in P1 (see lib/sports.ts's `enabled`
// flags), so anything else 404s instead of rendering a page nobody has
// built for it yet. isWiredFootballCompetition also 404s non-football
// competitions (e.g. nrl) reached via /football/<comp> -- NRL keeps its own
// space. The legacy component only reads its own params, so this wrapper
// needs none from `params` beyond the comp guard.
export default async function CompFixturesPage({
  params,
}: {
  params: Promise<{ comp: string }>;
}) {
  const { comp } = await params;
  if (!isWiredFootballCompetition(comp)) notFound();
  return <LegacyMatchesPage />;
}
