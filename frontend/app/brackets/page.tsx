import type { Metadata } from "next";
import { APP_NAME } from "@/lib/constants";
import {
  getKnockoutOddsServer,
  getGroupsServer,
  getOfficialBracketServer,
} from "@/lib/api";
import { BracketsClient } from "./BracketsClient";

export const metadata: Metadata = {
  title: `Bracket — ${APP_NAME}`,
  description:
    "The projected WC26 knockout bracket and title odds, updated as the model refreshes.",
};

/** Server-rendered: title odds + projected bracket are in the first HTML. Tabs
 *  and team links hydrate client-side; data refreshes in the background. */
export default async function BracketsPage() {
  const [initialOdds, initialGroups, initialBracket] = await Promise.all([
    getKnockoutOddsServer().catch(() => null),
    getGroupsServer().catch(() => null),
    getOfficialBracketServer().catch(() => null),
  ]);
  return (
    <BracketsClient
      initialOdds={initialOdds ?? undefined}
      initialGroups={initialGroups ?? undefined}
      initialBracket={initialBracket ?? undefined}
    />
  );
}
