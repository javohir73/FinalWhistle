import type { Metadata } from "next";
import { APP_NAME } from "@/lib/constants";
import { getGroupsServer } from "@/lib/api";
import { getCompetitionTournament } from "@/lib/tournament";
import { GroupsClient } from "./GroupsClient";
import type { CompetitionId } from "@/lib/sports";

export const metadata: Metadata = {
  title: `Group tables — ${APP_NAME}`,
  description:
    "Live WC26 group standings with each team's model-projected chance of finishing in the top two.",
};

/** Server-rendered: the group tables are in the first HTML (no skeleton flash).
 *  The client island refreshes in the background and recovers if SSR data was
 *  unavailable (e.g. backend cold start). Also resolves the active tournament
 *  so GroupsClient can switch to the D1 league-table layout (single Group). */
export async function renderGroupsPage(competition: CompetitionId = "wc26") {
  const [initialGroups, tournament] = await Promise.all([
    getGroupsServer(competition).catch(() => null),
    getCompetitionTournament(competition),
  ]);
  return (
    <GroupsClient
      initialGroups={initialGroups ?? undefined}
      tournament={tournament}
      competition={competition}
    />
  );
}

export default async function GroupsPage() {
  return renderGroupsPage();
}
