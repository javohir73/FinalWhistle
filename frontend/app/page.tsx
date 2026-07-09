import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  getTeamsServer,
  getGroupsServer,
  getUpcomingMatchesServer,
  getKnockoutOddsServer,
} from "@/lib/api";
import { HomeExperience } from "./HomeExperience";

/** Country-first home: the first useful action is choosing a nation to follow.
 *  Data is server-rendered (ISR) so the chooser and any returning user's hub
 *  paint with real content; the interactive flow lives in a client island. */
export default async function HomePage() {
  const store = await cookies();
  if (store.get("fw_sport")?.value === "nrl") redirect("/nrl");

  const [teams, groups, matches, odds] = await Promise.all([
    getTeamsServer().catch(() => null),
    getGroupsServer().catch(() => null),
    getUpcomingMatchesServer().catch(() => null),
    getKnockoutOddsServer().catch(() => null),
  ]);

  return (
    <HomeExperience
      initialTeams={teams ?? undefined}
      initialGroups={groups ?? undefined}
      initialMatches={matches ?? undefined}
      initialOdds={odds ?? undefined}
    />
  );
}
