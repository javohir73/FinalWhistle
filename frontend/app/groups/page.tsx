import { getGroupsServer } from "@/lib/api";
import { GroupsClient } from "./GroupsClient";

/** Server-rendered: the group tables are in the first HTML (no skeleton flash).
 *  The client island refreshes in the background and recovers if SSR data was
 *  unavailable (e.g. backend cold start). */
export default async function GroupsPage() {
  const initialGroups = await getGroupsServer().catch(() => null);
  return <GroupsClient initialGroups={initialGroups ?? undefined} />;
}
