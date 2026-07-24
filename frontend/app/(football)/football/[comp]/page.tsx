import { notFound } from "next/navigation";
import { isWiredFootballCompetition } from "@/lib/sports";
import HomePage from "@/app/page";

// ARCHITECT RULING (Floodlight P1, slice p1-s3): WC26 is the only football
// competition wired in P1 -- epl/laliga/bundesliga are P2 and stay
// `enabled: false` in lib/sports.ts, so isWiredFootballCompetition() 404s
// them here rather than serving a page nothing links to yet. The football
// scope also 404s non-football competitions (e.g. nrl) that reach this
// route via /football/<comp> -- NRL keeps its own space. This route wraps
// (does not move) the existing root HomePage: same component, same data, so
// /football/wc26 renders identically to today's "/". No metadata export --
// app/page.tsx has none either; the root layout's generateMetadata covers it.
export default async function CompHomePage({
  params,
}: {
  params: Promise<{ comp: string }>;
}) {
  const { comp } = await params;
  if (!isWiredFootballCompetition(comp)) notFound();
  return <HomePage />;
}
