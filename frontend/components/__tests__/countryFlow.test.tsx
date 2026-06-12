/** Country-first home flow: choose a country → "Predict my team" → AI reveal,
 *  and a returning user (reveal already done) lands straight on the hub. The
 *  whole flow is anonymous and persisted in localStorage. */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { HomeExperience } from "@/app/HomeExperience";
import * as api from "@/lib/api";
import type { Team } from "@/lib/types";

jest.mock("@/lib/api");

const teams: Team[] = [
  { id: 1, name: "Brazil", country_code: "BR", confederation: "CONMEBOL", fifa_rank: 3, elo_rating: 2042, is_host: false },
  { id: 2, name: "Mexico", country_code: "MX", confederation: "CONCACAF", fifa_rank: 14, elo_rating: 1885, is_host: true },
];

beforeEach(() => {
  localStorage.clear();
  (api.getTeams as jest.Mock).mockResolvedValue(teams);
  (api.getGroups as jest.Mock).mockResolvedValue([]);
  (api.getUpcomingMatches as jest.Mock).mockResolvedValue([]);
  (api.getKnockoutOdds as jest.Mock).mockResolvedValue([]);
  (api.getTeam as jest.Mock).mockResolvedValue({
    team: teams[0],
    group_id: 1,
    group_name: "C",
    recent_form: [],
    strengths: ["Elite attacking depth"],
    weaknesses: ["Shaky in defensive transitions"],
  });
});

afterEach(() => {
  jest.useRealTimers();
  jest.resetAllMocks();
});

it("lets an anonymous user choose a country and start the AI forecast", async () => {
  jest.useFakeTimers({ doNotFake: ["queueMicrotask"] });
  render(<HomeExperience initialTeams={teams} />);

  // Chooser appears (post-hydration).
  await waitFor(() => expect(screen.getByText("Choose your")).toBeInTheDocument());

  // Pick Brazil → focused preview with the Predict CTA.
  fireEvent.click(screen.getByRole("option", { name: /Brazil/ }));
  expect(screen.getByRole("button", { name: /Predict my team/ })).toBeInTheDocument();

  // Start the forecast → honest "preparing" reveal (no "generating live" copy).
  fireEvent.click(screen.getByRole("button", { name: /Predict my team/ }));
  expect(screen.getByText("Preparing your AI forecast")).toBeInTheDocument();

  // Selection persisted locally for the next visit.
  expect(localStorage.getItem("finalwhistle:selected-country:v1")).toContain("Brazil");
});

it("supports arrow-key navigation between country options (listbox contract)", async () => {
  render(<HomeExperience initialTeams={teams} />);
  await waitFor(() => expect(screen.getByText("Choose your")).toBeInTheDocument());

  const brazil = screen.getByRole("option", { name: /Brazil/ });
  const mexico = screen.getByRole("option", { name: /Mexico/ });

  brazil.focus();
  fireEvent.keyDown(brazil, { key: "ArrowDown" });
  expect(mexico).toHaveFocus();
  fireEvent.keyDown(mexico, { key: "ArrowUp" });
  expect(brazil).toHaveFocus();
  fireEvent.keyDown(brazil, { key: "End" });
  expect(mexico).toHaveFocus();
  fireEvent.keyDown(mexico, { key: "Home" });
  expect(brazil).toHaveFocus();
});

it("sends a returning user straight to the personalized hub", async () => {
  localStorage.setItem(
    "finalwhistle:selected-country:v1",
    JSON.stringify({ team_id: 1, team: "Brazil", selected_at: "2026-06-01T00:00:00Z", prediction_revealed: true }),
  );

  // /api/groups serves the LIVE table (real results) — names come prefixed.
  const groups = [{
    id: 3,
    name: "Group C",
    standings: [
      { team_id: 1, team: "Brazil", projected_points: 3, projected_goals_for: 2, projected_goal_diff: 2, qualification_prob: 0.9 },
      { team_id: 9, team: "Scotland", projected_points: 0, projected_goals_for: 0, projected_goal_diff: -2, qualification_prob: 0.2 },
    ],
  }];
  (api.getGroups as jest.Mock).mockResolvedValue(groups);

  render(<HomeExperience initialTeams={teams} initialGroups={groups} initialMatches={[]} initialOdds={[]} />);

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Brazil" })).toBeInTheDocument(),
  );
  expect(screen.getByText("Your predictions for Brazil")).toBeInTheDocument();

  // The hub shows the LIVE group table: real points (3 after a win, not a
  // simulated average) and no doubled "Group Group C" heading.
  expect(screen.getByText("Live table")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /^Group C/ })).toBeInTheDocument();
  expect(screen.queryByText(/Group Group/)).not.toBeInTheDocument();
  const cells = screen.getAllByRole("cell").map((c) => c.textContent);
  expect(cells).toContain("3"); // Brazil's live points

  // Strengths come from the per-team profile fetch.
  await waitFor(() =>
    expect(screen.getByText("Elite attacking depth")).toBeInTheDocument(),
  );
});
