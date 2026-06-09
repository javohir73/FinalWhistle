import { getGroupsServer, getUpcomingMatchesServer, getKnockoutOddsServer } from "@/lib/api";
import { MyBracketClient } from "./MyBracketClient";

/** Server-rendered scaffolding (groups, fixtures, odds) so the builder paints with
 *  real content immediately. The bracket picks themselves live in localStorage and
 *  the account actions hydrate client-side. */
export default async function MyBracketPage() {
  const [initialGroups, initialMatches, initialOdds] = await Promise.all([
    getGroupsServer().catch(() => null),
    getUpcomingMatchesServer().catch(() => null),
    getKnockoutOddsServer().catch(() => null),
  ]);
  return (
    <MyBracketClient
      initialGroups={initialGroups ?? undefined}
      initialMatches={initialMatches ?? undefined}
      initialOdds={initialOdds ?? undefined}
    />
  );
}
