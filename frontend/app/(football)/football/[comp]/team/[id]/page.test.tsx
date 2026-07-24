/** Regression test for the Floodlight P1 canonical-URL bug: this wrapper's
 *  generateMetadata used to be a bare re-export of the legacy page's
 *  generateMetadata, which hardcodes alternates.canonical to `/team/${id}` --
 *  a path next.config.mjs now 301s straight back to this very page. Assert
 *  the canonical instead resolves to the live /football/{comp}/team/{id}
 *  URL this page actually serves. */
import { generateMetadata } from "./page";
import { getTeamServer } from "@/lib/api";
import type { TeamProfile } from "@/lib/types";

jest.mock("@/lib/api");
const mockGet = getTeamServer as jest.MockedFunction<typeof getTeamServer>;

const teamProfile: TeamProfile = {
  team: {
    id: 10,
    name: "Brazil",
    country_code: "BR",
    confederation: "CONMEBOL",
    fifa_rank: 1,
    elo_rating: 2100,
    is_host: false,
  },
  group_id: 3,
  group_name: "Group C",
  recent_form: [],
  strengths: ["Attack"],
  weaknesses: ["Defense"],
};

afterEach(() => jest.resetAllMocks());

it("points the canonical at the live /football/{comp}/team/{id} URL, not the redirecting legacy path", async () => {
  mockGet.mockResolvedValue(teamProfile);
  const meta = await generateMetadata({ params: Promise.resolve({ comp: "wc26", id: "10" }) });

  expect(meta.alternates?.canonical).toBe("/football/wc26/team/10");
  // Title still comes through from the legacy generateMetadata.
  expect(meta.title).toContain("Brazil");
});
