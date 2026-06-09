import { getLeaderboardServer } from "@/lib/api";
import { LeaderboardClient } from "./LeaderboardClient";

/** Server-rendered: the leaderboard table (or empty state) is in the first HTML.
 *  The signed-in rank card hydrates client-side. */
export default async function LeaderboardPage() {
  const initialRows = await getLeaderboardServer().catch(() => null);
  return <LeaderboardClient initialRows={initialRows ?? undefined} />;
}
