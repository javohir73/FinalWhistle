/** Country-first home flow: choose a country → "Predict my team" → AI reveal,
 *  and a returning user (reveal already done) lands on the Daylight home
 *  DASHBOARD — greeting, the "Today's movers" panel, and today's
 *  match-of-the-day. The detailed team hub lives on /team/[id]; this surface
 *  is the lightweight landing. Whole flow is anonymous + local. */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { HomeExperience } from "@/app/HomeExperience";
import * as api from "@/lib/api";
import type { MatchSummary, Team } from "@/lib/types";

jest.mock("@/lib/api");

// The returning-user dashboard now mounts the team-search combobox, which uses
// the App Router. Stub it so these (navigation-agnostic) flow tests don't need a
// router context.
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

// Relative kickoffs so the match-of-the-day assertions don't time-bomb: a fixed
// future date eventually becomes "yesterday" and (in UTC CI) falls out of the
// upcoming/today window. Anchor to "now" instead.
const hoursFromNow = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();
const daysAgo = (d: number) => new Date(Date.now() - d * 86_400_000).toISOString();

const teams: Team[] = [
  { id: 1, name: "Brazil", country_code: "BR", confederation: "CONMEBOL", fifa_rank: 3, elo_rating: 2042, is_host: false },
  { id: 2, name: "Mexico", country_code: "MX", confederation: "CONCACAF", fifa_rank: 14, elo_rating: 1885, is_host: true },
];

const REVEALED = JSON.stringify({
  team_id: 1, team: "Brazil", selected_at: "2026-06-01T00:00:00Z", prediction_revealed: true,
});

beforeEach(() => {
  localStorage.clear();
  (api.getTeams as jest.Mock).mockResolvedValue(teams);
  (api.getGroups as jest.Mock).mockResolvedValue([]);
  (api.getUpcomingMatches as jest.Mock).mockResolvedValue([]);
  (api.getKnockoutOdds as jest.Mock).mockResolvedValue([]);
  (api.getMovers as jest.Mock).mockResolvedValue({
    sport: "football",
    as_of: null,
    movers: [],
    disclaimer: "test",
  });
  // IntelPanel (replaces MoversPanel on the dashboard) falls back to the
  // movers panel above when the sport has no fresh market data.
  (api.getIntel as jest.Mock).mockResolvedValue({
    sport: "football",
    has_data: false,
    updated_at: null,
    matches: [],
    storylines: [],
    disclaimer: "test",
  });
  (api.getProbHistory as jest.Mock).mockResolvedValue({
    match_id: 1,
    points: [],
    disclaimer: "test",
  });
  (api.getTeam as jest.Mock).mockResolvedValue({
    team: teams[0],
    group_id: 1,
    group_name: "C",
    recent_form: [],
    strengths: ["Elite attacking depth"],
    weaknesses: ["Shaky in defensive transitions"],
  });
  (api.getModelRecord as jest.Mock).mockResolvedValue({
    evaluated_matches: 2,
    winner_accuracy: 1.0,
    winners_correct: 2,
    exact_score_hits: 1,
    avg_brier: null,
    avg_log_loss: null,
    calibration: [],
    best_calls: [],
    biggest_misses: [],
    last_updated: null,
    model_version: "test",
    disclaimer: "test",
  });
});

afterEach(() => {
  jest.useRealTimers();
  jest.resetAllMocks();
});

it("lets an anonymous user choose a country and start the ML model forecast", async () => {
  jest.useFakeTimers({ doNotFake: ["queueMicrotask"] });
  render(<HomeExperience initialTeams={teams} />);

  // Chooser appears (post-hydration).
  await waitFor(() => expect(screen.getByText("Choose your")).toBeInTheDocument());

  // Pick Brazil → focused preview with the Predict CTA.
  fireEvent.click(screen.getByRole("option", { name: /Brazil/ }));
  expect(screen.getByRole("button", { name: /Predict my team/ })).toBeInTheDocument();

  // Start the forecast → honest "preparing" reveal (no "generating live" copy).
  fireEvent.click(screen.getByRole("button", { name: /Predict my team/ }));
  expect(screen.getByText("Preparing your ML model forecast")).toBeInTheDocument();

  // Selection persisted locally for the next visit.
  expect(localStorage.getItem("finalwhistle:selected-country:v1")).toContain("Brazil");
});

it("resets scroll position when the dashboard swaps in after the AI reveal", async () => {
  // Simulate the page having scrolled down to reach the reveal's "Skip"
  // control (a real user, or a browser-automation tool bringing an
  // off-screen element into view before clicking it, both do this) — the
  // regression was that this leftover scrollY carried straight into the
  // much-shorter dashboard, hiding "Following {team}" above the fold.
  const scrollToSpy = jest.spyOn(window, "scrollTo").mockImplementation(() => {});
  jest.useFakeTimers({ doNotFake: ["queueMicrotask"] });
  render(<HomeExperience initialTeams={teams} />);

  await waitFor(() => expect(screen.getByText("Choose your")).toBeInTheDocument());
  fireEvent.click(screen.getByRole("option", { name: /Brazil/ }));
  fireEvent.click(screen.getByRole("button", { name: /Predict my team/ }));
  expect(screen.getByText("Preparing your ML model forecast")).toBeInTheDocument();

  // Finish the reveal (skip button also works; the timeout is simplest here).
  fireEvent.click(screen.getByRole("button", { name: /Skip|Continue/ }));

  await waitFor(() => expect(screen.getByText(/Following Brazil/)).toBeInTheDocument());
  expect(scrollToSpy).toHaveBeenCalledWith(0, 0);

  scrollToSpy.mockRestore();
});

it("does not reset scroll on a plain dashboard remount (only the reveal transition does)", async () => {
  // Regression check for the fix: a returning user whose `prediction_revealed`
  // is already persisted — e.g. navigating away from "/" and hitting Back —
  // mounts straight into HomeDashboard without ever going through
  // AICalculationReveal. That mount must NOT call scrollTo, or it would stomp
  // the browser's native scroll restoration on every such remount.
  localStorage.setItem("finalwhistle:selected-country:v1", REVEALED);
  const scrollToSpy = jest.spyOn(window, "scrollTo").mockImplementation(() => {});

  render(
    <HomeExperience initialTeams={teams} initialGroups={[]} initialMatches={[]} initialOdds={[]} />,
  );

  await waitFor(() => expect(screen.getByText("Following Brazil")).toBeInTheDocument());
  expect(scrollToSpy).not.toHaveBeenCalled();

  scrollToSpy.mockRestore();
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

it("sends a returning user to their Daylight home dashboard", async () => {
  localStorage.setItem("finalwhistle:selected-country:v1", REVEALED);

  const groups = [{
    id: 3,
    name: "Group C",
    standings: [
      { team_id: 1, team: "Brazil", projected_points: 3, projected_goals_for: 2, projected_goal_diff: 2, qualification_prob: 0.9 },
      { team_id: 9, team: "Scotland", projected_points: 0, projected_goals_for: 0, projected_goal_diff: -2, qualification_prob: 0.2 },
    ],
  }];
  (api.getGroups as jest.Mock).mockResolvedValue(groups);

  render(
    <HomeExperience initialTeams={teams} initialGroups={groups} initialMatches={[]} initialOdds={[]} />,
  );

  // The greeting + today's count paint for the returning user…
  await waitFor(() => expect(screen.getByText("No matches today")).toBeInTheDocument());
  // …and the search box to jump to any team is available.
  expect(screen.getByRole("combobox")).toBeInTheDocument();
});

it("features an upcoming fixture as a clickable match-of-the-day card", async () => {
  localStorage.setItem("finalwhistle:selected-country:v1", REVEALED);

  const fixture: MatchSummary = {
    match_id: 101, stage: "group", group: "C", kickoff_utc: hoursFromNow(3),
    venue: "Estadio Test", venue_city: "Test City", venue_country: "Testland", is_neutral: true,
    status: "scheduled", score_home: null, score_away: null, minute: null,
    period: null, injury_time: null, penalty_home: null, penalty_away: null,
    teams: { home: "Brazil", away: "Scotland" },
    predicted_winner: "Brazil",
    probabilities: { home_win: 0.62, draw: 0.24, away_win: 0.14 },
    predicted_score: { home: 2, away: 0, probability: 0.1 },
    confidence: "High",
    goal_events: [],
  };
  (api.getUpcomingMatches as jest.Mock).mockResolvedValue([fixture]);

  const { container } = render(
    <HomeExperience initialTeams={teams} initialGroups={[]} initialMatches={[fixture]} initialOdds={[]} />,
  );

  await waitFor(() => expect(screen.getByText("Match of the day")).toBeInTheDocument());
  // The card carries the AI scoreline and links into the full match page.
  expect(container.querySelector('a[href="/match/101"]')).not.toBeNull();
});

it("a finished-only slate falls back to the no-matches-today state without crashing", async () => {
  localStorage.setItem("finalwhistle:selected-country:v1", REVEALED);

  const finished: MatchSummary = {
    match_id: 202, stage: "group", group: "C", kickoff_utc: daysAgo(7),
    venue: "Estadio Test", venue_city: "Test City", venue_country: "Testland", is_neutral: true,
    status: "finished", score_home: 4, score_away: 1, minute: null,
    period: null, injury_time: null, penalty_home: null, penalty_away: null,
    teams: { home: "Brazil", away: "Paraguay" },
    predicted_winner: "Brazil",
    probabilities: { home_win: 0.62, draw: 0.24, away_win: 0.14 },
    predicted_score: { home: 1, away: 0, probability: 0.1 },
    confidence: "Medium",
    goal_events: [],
  };
  (api.getUpcomingMatches as jest.Mock).mockResolvedValue([finished]);

  render(
    <HomeExperience initialTeams={teams} initialGroups={[]} initialMatches={[finished]} initialOdds={[]} />,
  );

  await waitFor(() => expect(screen.getByText("No matches today")).toBeInTheDocument());
});

it("lets a returning user switch teams from the dashboard (routes back to the chooser)", async () => {
  localStorage.setItem("finalwhistle:selected-country:v1", REVEALED);

  render(<HomeExperience initialTeams={teams} initialGroups={[]} initialMatches={[]} initialOdds={[]} />);

  await waitFor(() => expect(screen.getByText("Following Brazil")).toBeInTheDocument());

  fireEvent.click(screen.getByRole("button", { name: /Change team/ }));
  await waitFor(() => expect(screen.getByText("Choose your")).toBeInTheDocument());
});

it("survives a corrupted stored timezone without crashing the dashboard", async () => {
  // A stale/garbage zone (e.g. left by an older build) must NOT reach
  // Intl.DateTimeFormat and throw — useTimezone should reject it and fall back.
  localStorage.setItem("pp:timezone", JSON.stringify({ tz: "Not/AReal_Zone", confirmed: true }));
  localStorage.setItem("finalwhistle:selected-country:v1", REVEALED);

  const fixture: MatchSummary = {
    match_id: 303, stage: "group", group: "C", kickoff_utc: hoursFromNow(3),
    venue: "Estadio Test", venue_city: "Test City", venue_country: "Testland", is_neutral: true,
    status: "scheduled", score_home: null, score_away: null, minute: null,
    period: null, injury_time: null, penalty_home: null, penalty_away: null,
    teams: { home: "Brazil", away: "Scotland" },
    predicted_winner: "Brazil",
    probabilities: { home_win: 0.62, draw: 0.24, away_win: 0.14 },
    predicted_score: { home: 2, away: 0, probability: 0.1 },
    confidence: "High",
    goal_events: [],
  };
  (api.getUpcomingMatches as jest.Mock).mockResolvedValue([fixture]);

  const { container } = render(
    <HomeExperience initialTeams={teams} initialGroups={[]} initialMatches={[fixture]} initialOdds={[]} />,
  );

  // The dashboard renders the fixture card without the bad zone crashing the tree.
  await waitFor(() => expect(container.querySelector('a[href^="/match/"]')).not.toBeNull());
});
