import { getUpcomingMatchesServer } from "@/lib/api";
import { MatchesClient } from "./MatchesClient";

/** Server-rendered: the fixture list is in the first HTML. The client island
 *  owns filters/sort and polls every 30s for live scores, seeded with this data. */
export default async function MatchesPage() {
  const initialMatches = await getUpcomingMatchesServer().catch(() => null);
  return <MatchesClient initialMatches={initialMatches ?? undefined} />;
}
