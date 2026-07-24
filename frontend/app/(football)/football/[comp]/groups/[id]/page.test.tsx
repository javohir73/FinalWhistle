/** Regression test for the Floodlight P1 canonical-URL bug: this wrapper's
 *  generateMetadata used to be a bare re-export of the legacy page's
 *  generateMetadata, which hardcodes alternates.canonical to `/groups/${id}` --
 *  a path next.config.mjs now 301s straight back to this very page. Assert
 *  the canonical instead resolves to the live /football/{comp}/groups/{id}
 *  URL this page actually serves. */
import { generateMetadata } from "./page";
import { getGroupServer } from "@/lib/api";
import type { Group } from "@/lib/types";

jest.mock("@/lib/api");
const mockGet = getGroupServer as jest.MockedFunction<typeof getGroupServer>;

const group: Group = {
  id: 3,
  name: "Group C",
  standings: [
    { team_id: 1, team: "Brazil", projected_points: 6, projected_goals_for: 4, projected_goal_diff: 3, qualification_prob: 0.9 },
  ],
};

afterEach(() => jest.resetAllMocks());

it("points the canonical at the live /football/{comp}/groups/{id} URL, not the redirecting legacy path", async () => {
  mockGet.mockResolvedValue(group);
  const meta = await generateMetadata({ params: Promise.resolve({ comp: "wc26", id: "3" }) });

  expect(meta.alternates?.canonical).toBe("/football/wc26/groups/3");
  // Title still comes through from the legacy generateMetadata.
  expect(meta.title).toContain("Group C");
});
