/** MyBracketClient accessibility: the compact group-fixture buttons keep their
 *  short visible labels ("Draw", team names) but expose full match context to
 *  assistive tech via aria-label — so a screen-reader user can tell the ~72
 *  "Draw" buttons (and the repeated team-name buttons) apart. */
import { render, screen, waitFor } from "@testing-library/react";
import { MyBracketClient } from "./MyBracketClient";
import * as api from "@/lib/api";
import type { Group, MatchSummary } from "@/lib/types";

// Light mocks: the sync hook and account panel pull in auth/network that this
// accessibility test doesn't exercise. The api is mocked so the seeded page's
// background refresh resolves to the same fixtures (per-test, below) instead of
// hitting the network and wiping the seeded content.
jest.mock("@/lib/api");
jest.mock("@/lib/useBracketSync", () => ({
  useBracketSync: () => ({ status: "idle", signedIn: false }),
}));
jest.mock("@/components/AccountPanel", () => ({
  AccountPanel: () => null,
}));

const mockGetGroups = api.getGroups as jest.Mock;
const mockGetUpcomingMatches = api.getUpcomingMatches as jest.Mock;
const mockGetKnockoutOdds = api.getKnockoutOdds as jest.Mock;

const initialGroups: Group[] = [
  {
    id: 1,
    name: "Group A",
    standings: [
      { team_id: 10, team: "Mexico", projected_points: 0, projected_goals_for: 0, projected_goal_diff: 0, qualification_prob: 0.6 },
      { team_id: 11, team: "South Africa", projected_points: 0, projected_goals_for: 0, projected_goal_diff: 0, qualification_prob: 0.3 },
    ],
  },
];

const initialMatches: MatchSummary[] = [
  {
    match_id: 100,
    stage: "Group Stage",
    group: "Group A",
    kickoff_utc: null,
    venue: null,
    venue_city: null,
    venue_country: null,
    is_neutral: true,
    status: "scheduled",
    score_home: null,
    score_away: null,
    minute: null,
    period: null,
    injury_time: null,
    penalty_home: null,
    penalty_away: null,
    teams: { home: "Mexico", away: "South Africa" },
    predicted_winner: null,
    probabilities: null,
    predicted_score: null,
    confidence: null,
  },
];

beforeEach(() => {
  localStorage.clear();
  // Background refresh returns the same fixtures, so seeded content persists.
  mockGetGroups.mockResolvedValue(initialGroups);
  mockGetUpcomingMatches.mockResolvedValue(initialMatches);
  mockGetKnockoutOdds.mockResolvedValue([]);
});
afterEach(() => jest.clearAllMocks());

it("gives each group-fixture pick button a full match-context accessible name", async () => {
  render(<MyBracketClient initialGroups={initialGroups} initialMatches={initialMatches} initialOdds={[]} />);

  // Screen-reader-only accessible names carry the match context…
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Predict a draw between Mexico and South Africa" }),
    ).toBeInTheDocument(),
  );
  expect(
    screen.getByRole("button", { name: "Pick Mexico to beat South Africa" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Pick South Africa to beat Mexico" }),
  ).toBeInTheDocument();
});

it("keeps the compact visible labels unchanged", async () => {
  render(<MyBracketClient initialGroups={initialGroups} initialMatches={initialMatches} initialOdds={[]} />);
  await waitFor(() => expect(screen.getByText("Draw")).toBeInTheDocument());

  // …while the visible text stays short: "Draw" and the bare team names.
  // (Team names also appear in the mini-table, so scope each check to its
  // fixture button — the visible span text is unchanged even though the
  // accessible name now carries the full match context.)
  expect(screen.getByText("Draw")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Pick Mexico to beat South Africa" }),
  ).toHaveTextContent("Mexico");
  expect(
    screen.getByRole("button", { name: "Pick South Africa to beat Mexico" }),
  ).toHaveTextContent("South Africa");
});
