import type { Metadata } from "next";
import { APP_NAME } from "@/lib/constants";
import { getUpcomingMatchesServer } from "@/lib/api";
import { MatchesClient } from "./MatchesClient";

export const metadata: Metadata = {
  title: `Fixtures — ${APP_NAME}`,
  description:
    "Every WC26 fixture with live scores and the model's pre-kickoff win probabilities, filterable by upcoming, live, or finished.",
};

/** Server-rendered: the fixture list is in the first HTML. The client island
 *  owns filters/sort and polls every 30s for live scores, seeded with this data. */
export default async function MatchesPage() {
  const initialMatches = await getUpcomingMatchesServer().catch(() => null);
  return <MatchesClient initialMatches={initialMatches ?? undefined} />;
}
