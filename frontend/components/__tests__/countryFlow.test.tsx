/** Country-first home flow: choose a country → "Predict my team" → AI reveal,
 *  and a returning user (reveal already done) lands straight on the hub. The
 *  whole flow is anonymous and persisted in localStorage. */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { HomeExperience } from "@/app/HomeExperience";
import * as api from "@/lib/api";
import type { MatchSummary, Team } from "@/lib/types";

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
  expect(screen.getByText("Brazil's upcoming matches")).toBeInTheDocument();

  // The "More about" drawer still carries the LIVE group table: real points
  // (3 after a win, not a simulated average) and the projected-finish line uses
  // the already-prefixed group name (no doubled "Group Group C").
  expect(screen.getByText(/Projected to finish in Group C/)).toBeInTheDocument();
  expect(screen.queryByText(/Group Group/)).not.toBeInTheDocument();
  const cells = screen.getAllByRole("cell").map((c) => c.textContent);
  expect(cells).toContain("3"); // Brazil's live points

  // Strengths come from the per-team profile fetch.
  await waitFor(() =>
    expect(screen.getByText("Elite attacking depth")).toBeInTheDocument(),
  );

  // Model record line appears once the record has loaded (evaluated_matches > 0).
  await waitFor(() =>
    expect(screen.getByText(/AI record so far/)).toBeInTheDocument(),
  );
});

it("keeps the first view simple — advanced detail and the pick game stay collapsed", async () => {
  localStorage.setItem(
    "finalwhistle:selected-country:v1",
    JSON.stringify({ team_id: 1, team: "Brazil", selected_at: "2026-06-01T00:00:00Z", prediction_revealed: true }),
  );

  const fixture: MatchSummary = {
    match_id: 101, stage: "group", group: "C", kickoff_utc: "2026-06-20T18:00:00Z",
    venue: "Estadio Test", venue_city: "Test City", venue_country: "Testland", is_neutral: true,
    status: "scheduled", score_home: null, score_away: null, minute: null,
    period: null, injury_time: null, penalty_home: null, penalty_away: null,
    teams: { home: "Brazil", away: "Scotland" },
    predicted_winner: "Brazil",
    probabilities: { home_win: 0.62, draw: 0.24, away_win: 0.14 },
    predicted_score: { home: 2, away: 0, probability: 0.1 },
    confidence: "High",
  };
  (api.getUpcomingMatches as jest.Mock).mockResolvedValue([fixture]);

  const { container } = render(
    <HomeExperience initialTeams={teams} initialGroups={[]} initialMatches={[fixture]} initialOdds={[]} />,
  );

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Brazil's upcoming matches" })).toBeInTheDocument(),
  );

  // Both advanced drawers render COLLAPSED by default — the first view is the
  // payoff, not a dashboard. (jsdom keeps <details> content in the DOM even
  // when closed, so we assert the `open` attribute, not element presence.)
  const drawers = container.querySelectorAll("details");
  expect(drawers).toHaveLength(2);
  drawers.forEach((d) => expect(d).not.toHaveAttribute("open"));
  expect(screen.getByText("More about Brazil")).toBeInTheDocument();
  expect(screen.getByText("Make your own call")).toBeInTheDocument();

  // The default view shows the read-only AI prediction card (a link to the
  // match detail), outside any drawer.
  const matchLink = container.querySelector('a[href^="/match/"]');
  expect(matchLink).not.toBeNull();
  expect(matchLink?.closest("details")).toBeNull();

  // The hub isn't grouped under day headers, so each card must show the kickoff
  // DATE (a month name), not just the time.
  expect(matchLink?.textContent).toMatch(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/);

  // The interactive pick game lives ONLY inside the collapsed "Make your own
  // call" drawer — there are no pick buttons in the default first view.
  const helper = screen.getByText(/Think the AI.s got it wrong/);
  const pickDrawer = helper.closest("details");
  expect(pickDrawer).not.toBeNull();
  expect(pickDrawer).not.toHaveAttribute("open");
  expect(pickDrawer?.querySelector("summary")?.textContent).toContain("Make your own call");
  expect(pickDrawer?.querySelectorAll('button[aria-pressed]').length ?? 0).toBeGreaterThan(0);
});

it("shows the kickoff date on already-played (finished) hub matches too", async () => {
  localStorage.setItem(
    "finalwhistle:selected-country:v1",
    JSON.stringify({ team_id: 1, team: "Brazil", selected_at: "2026-06-01T00:00:00Z", prediction_revealed: true }),
  );

  // A finished fixture (FT) — the card carries a result, but the kickoff date
  // must still be shown since the hub isn't grouped under day headers.
  const finished: MatchSummary = {
    match_id: 202, stage: "group", group: "C", kickoff_utc: "2026-06-14T18:00:00Z",
    venue: "Estadio Test", venue_city: "Test City", venue_country: "Testland", is_neutral: true,
    status: "finished", score_home: 4, score_away: 1, minute: null,
    period: null, injury_time: null, penalty_home: null, penalty_away: null,
    teams: { home: "Brazil", away: "Paraguay" },
    predicted_winner: "Brazil",
    probabilities: { home_win: 0.62, draw: 0.24, away_win: 0.14 },
    predicted_score: { home: 1, away: 0, probability: 0.1 },
    confidence: "Medium",
  };
  (api.getUpcomingMatches as jest.Mock).mockResolvedValue([finished]);

  const { container } = render(
    <HomeExperience initialTeams={teams} initialGroups={[]} initialMatches={[finished]} initialOdds={[]} />,
  );

  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Brazil's upcoming matches" })).toBeInTheDocument(),
  );

  const card = container.querySelector('a[href^="/match/"]');
  expect(card).not.toBeNull();
  // Even with an FT result, the kickoff DATE (a month name) is present.
  expect(card?.textContent).toMatch(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/);
});

it("survives a corrupted stored timezone without crashing the hub", async () => {
  // A stale/garbage zone (e.g. left by an older build) must NOT reach
  // Intl.DateTimeFormat and throw — useTimezone should reject it and fall back.
  localStorage.setItem("pp:timezone", JSON.stringify({ tz: "Not/AReal_Zone", confirmed: true }));
  localStorage.setItem(
    "finalwhistle:selected-country:v1",
    JSON.stringify({ team_id: 1, team: "Brazil", selected_at: "2026-06-01T00:00:00Z", prediction_revealed: true }),
  );

  const fixture: MatchSummary = {
    match_id: 303, stage: "group", group: "C", kickoff_utc: "2026-06-20T18:00:00Z",
    venue: "Estadio Test", venue_city: "Test City", venue_country: "Testland", is_neutral: true,
    status: "scheduled", score_home: null, score_away: null, minute: null,
    period: null, injury_time: null, penalty_home: null, penalty_away: null,
    teams: { home: "Brazil", away: "Scotland" },
    predicted_winner: "Brazil",
    probabilities: { home_win: 0.62, draw: 0.24, away_win: 0.14 },
    predicted_score: { home: 2, away: 0, probability: 0.1 },
    confidence: "High",
  };
  (api.getUpcomingMatches as jest.Mock).mockResolvedValue([fixture]);

  const { container } = render(
    <HomeExperience initialTeams={teams} initialGroups={[]} initialMatches={[fixture]} initialOdds={[]} />,
  );

  // The hub renders the fixture card without the bad zone crashing the tree.
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Brazil's upcoming matches" })).toBeInTheDocument(),
  );
  expect(container.querySelector('a[href^="/match/"]')).not.toBeNull();
});
