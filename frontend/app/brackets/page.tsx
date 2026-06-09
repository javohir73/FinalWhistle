import { getKnockoutOddsServer, getGroupsServer } from "@/lib/api";
import { BracketsClient } from "./BracketsClient";

/** Server-rendered: title odds + projected bracket are in the first HTML. Tabs
 *  and team links hydrate client-side; data refreshes in the background. */
export default async function BracketsPage() {
  const [initialOdds, initialGroups] = await Promise.all([
    getKnockoutOddsServer().catch(() => null),
    getGroupsServer().catch(() => null),
  ]);
  return (
    <BracketsClient
      initialOdds={initialOdds ?? undefined}
      initialGroups={initialGroups ?? undefined}
    />
  );
}
