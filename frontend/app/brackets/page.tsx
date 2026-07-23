import type { Metadata } from "next";
import Link from "next/link";
import { APP_NAME } from "@/lib/constants";
import {
  getKnockoutOddsServer,
  getGroupsServer,
  getOfficialBracketServer,
} from "@/lib/api";
import { getTournament } from "@/lib/tournament";
import { Empty } from "@/components/States";
import { BracketsClient } from "./BracketsClient";

export async function generateMetadata(): Promise<Metadata> {
  const tournament = await getTournament();
  if (!tournament.has_brackets) {
    return {
      title: `Bracket — ${APP_NAME}`,
      description: `${tournament.name} is a league — there's no knockout bracket to project.`,
    };
  }
  return {
    title: `Bracket — ${APP_NAME}`,
    description: `The projected ${tournament.name} knockout bracket and title odds, updated as the model refreshes.`,
  };
}

/** Server-rendered: title odds + projected bracket are in the first HTML. Tabs
 *  and team links hydrate client-side; data refreshes in the background.
 *  C6: a tournament with no knockout stage (has_brackets: false) gets a
 *  friendly empty state instead — see docs/LEAGUE-PIVOT-PLAN.md D6. */
export default async function BracketsPage() {
  const tournament = await getTournament();
  if (!tournament.has_brackets) {
    return (
      <Empty
        label={`${tournament.name} doesn't have a knockout bracket — it's decided on the table.`}
        action={
          <Link
            href="/matches"
            className="rounded-lg bg-win px-4 py-2 text-sm font-bold text-pitch transition hover:brightness-110"
          >
            See fixtures
          </Link>
        }
      />
    );
  }

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
