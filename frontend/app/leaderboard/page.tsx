import type { Metadata } from "next";
import { APP_NAME } from "@/lib/constants";
import { getLeaderboardServer } from "@/lib/api";
import { LeaderboardClient } from "./LeaderboardClient";

export const metadata: Metadata = {
  title: `Leaderboard — ${APP_NAME}`,
  description:
    "See how public brackets rank — points for group, knockout, finalist, and champion picks.",
};

/** Server-rendered: the leaderboard table (or empty state) is in the first HTML.
 *  The signed-in rank card hydrates client-side. */
export default async function LeaderboardPage() {
  const initialRows = await getLeaderboardServer().catch(() => null);
  return <LeaderboardClient initialRows={initialRows ?? undefined} />;
}
