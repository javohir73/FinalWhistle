import type { Metadata } from "next";
import { APP_NAME } from "@/lib/constants";
import { getGroupsServer } from "@/lib/api";
import { GroupsClient } from "./GroupsClient";

export const metadata: Metadata = {
  title: `Group tables — ${APP_NAME}`,
  description:
    "Live WC26 group standings with each team's model-projected chance of finishing in the top two.",
};

/** Server-rendered: the group tables are in the first HTML (no skeleton flash).
 *  The client island refreshes in the background and recovers if SSR data was
 *  unavailable (e.g. backend cold start). */
export default async function GroupsPage() {
  const initialGroups = await getGroupsServer().catch(() => null);
  return <GroupsClient initialGroups={initialGroups ?? undefined} />;
}
