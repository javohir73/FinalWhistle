import {
  getTeamsServer,
  getGroupsServer,
  getUpcomingMatchesServer,
  getKnockoutOddsServer,
} from "@/lib/api";
import { HomeExperience } from "./HomeExperience";

/** Country-first home: the first useful action is choosing a nation to follow.
 *  Data is server-rendered (ISR) so the chooser and any returning user's hub
 *  paint with real content; the interactive flow lives in a client island.
 *  No fw_sport cookie redirect here -- that logic belonged to the deleted
 *  SportSwitcher and was dropped, not carried forward, when the
 *  CompetitionOverlay became the one switcher surface (see
 *  lib/competitionPrefs.ts). A stale fw_sport=nrl cookie from before this
 *  change must not be able to trap a user away from this page. */
export default async function HomePage() {
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
