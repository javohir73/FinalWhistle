/** WC26 retention bridge banner: shown only once the final has finished (per
 *  the matches feed the home dashboard already polls — never a hardcoded
 *  date/clock check), dismissible permanently, and the NRL CTA must survive
 *  a failed email-capture POST (the backend may deploy after the frontend).
 *  The "Premier League tips are live" claim is gated on a real read of the
 *  public season leaderboard (league_score_predictions design doc review
 *  finding: the frontend deploys ahead of the migration + pipeline_target
 *  flip that actually populate it) -- it must never show before that read
 *  confirms the league is live. */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RetentionBridge } from "@/components/RetentionBridge";
import * as session from "@/lib/session";
import * as leagueTips from "@/lib/leagueTips";
import type { MatchSummary } from "@/lib/types";

// Real ApiError class preserved (mockRejectedValue below constructs one) --
// only notifyBridge itself is stubbed, mirroring LeagueTipsPicker.test.tsx's
// factory-mock idiom for the same module.
jest.mock("@/lib/session", () => {
  const actual = jest.requireActual("@/lib/session");
  return { ...actual, notifyBridge: jest.fn() };
});
jest.mock("@/lib/leagueTips");
const mockNotifyBridge = session.notifyBridge as jest.MockedFunction<typeof session.notifyBridge>;
const mockGetLeagueSeasonLeaderboard = leagueTips.getLeagueSeasonLeaderboard as jest.MockedFunction<
  typeof leagueTips.getLeagueSeasonLeaderboard
>;

function makeMatch(overrides: Partial<MatchSummary> = {}): MatchSummary {
  return {
    match_id: 104, stage: "final", group: null, kickoff_utc: "2026-07-19T19:00:00Z",
    venue: null, venue_city: null, venue_country: null, is_neutral: true,
    status: "finished", score_home: 2, score_away: 1, minute: null, period: null,
    injury_time: null, penalty_home: null, penalty_away: null,
    teams: { home: "France", away: "Argentina" },
    predicted_winner: "France", probabilities: null, predicted_score: null, confidence: null,
    goal_events: [], card_events: [],
    ...overrides,
  };
}

beforeEach(() => {
  localStorage.clear();
  // Default: league NOT live yet -- matches prod's actual state today, and
  // means every test that doesn't care about the live-tips copy still gets
  // the (equally real) email-capture fallback without configuring anything.
  mockGetLeagueSeasonLeaderboard.mockRejectedValue(
    new session.ApiError(404, "league_inactive", "League has no data loaded yet"),
  );
});
afterEach(() => jest.resetAllMocks());

it("is hidden when the final has not finished", async () => {
  render(<RetentionBridge matches={[makeMatch({ status: "in_play" })]} />);
  await waitFor(() => {
    expect(screen.queryByText("The World Cup is over. The AI is still playing.")).not.toBeInTheDocument();
  });
});

it("is hidden with no final match at all (group stage still in progress)", async () => {
  render(<RetentionBridge matches={[makeMatch({ stage: "group", status: "scheduled" })]} />);
  await waitFor(() => {
    expect(screen.queryByText("The World Cup is over. The AI is still playing.")).not.toBeInTheDocument();
  });
});

it("is visible once the final is finished", async () => {
  render(<RetentionBridge matches={[makeMatch()]} />);
  expect(await screen.findByText("The World Cup is over. The AI is still playing.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "See NRL predictions" })).toHaveAttribute("href", "/nrl/matches");
});

it("shows the email-capture fallback, not a live claim, before the league is confirmed live", async () => {
  render(<RetentionBridge matches={[makeMatch()]} />);
  await screen.findByText("The World Cup is over. The AI is still playing.");
  await waitFor(() => expect(mockGetLeagueSeasonLeaderboard).toHaveBeenCalled());

  expect(screen.queryByText(/Premier League tips are live/)).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Play Premier League tips" })).not.toBeInTheDocument();
  expect(screen.getByText("Get one email when your league kicks off.")).toBeInTheDocument();
});

it("points the Premier League CTA at the live tips page once the league is confirmed live", async () => {
  mockGetLeagueSeasonLeaderboard.mockResolvedValue({ league: "epl", participant_count: 12, entries: [] });
  render(<RetentionBridge matches={[makeMatch()]} />);
  await screen.findByText("The World Cup is over. The AI is still playing.");

  expect(await screen.findByText(/Premier League tips are live/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Play Premier League tips" })).toHaveAttribute("href", "/tips");
  // The live claim replaces the email-capture fallback -- it isn't shown
  // alongside a claim that the loop is already running.
  expect(screen.queryByLabelText("Email address")).not.toBeInTheDocument();
});

it("dismiss hides the banner and persists across remounts", async () => {
  const { unmount } = render(<RetentionBridge matches={[makeMatch()]} />);
  await screen.findByText("The World Cup is over. The AI is still playing.");

  fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(screen.queryByText("The World Cup is over. The AI is still playing.")).not.toBeInTheDocument();

  unmount();
  render(<RetentionBridge matches={[makeMatch()]} />);
  await waitFor(() => {
    expect(screen.queryByText("The World Cup is over. The AI is still playing.")).not.toBeInTheDocument();
  });
});

it("submits the email and shows the success state", async () => {
  mockNotifyBridge.mockResolvedValue({ ok: true });
  render(<RetentionBridge matches={[makeMatch()]} />);
  await screen.findByText("The World Cup is over. The AI is still playing.");

  fireEvent.change(await screen.findByLabelText("Email address"), { target: { value: "fan@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: "Notify me" }));

  expect(await screen.findByText("Done — one email, mid-August, no spam.")).toBeInTheDocument();
  expect(mockNotifyBridge).toHaveBeenCalledWith("fan@example.com", "wc26_final_bridge");
});

it("shows an inline error on failure but keeps the NRL CTA working", async () => {
  mockNotifyBridge.mockRejectedValue(new Error("network down"));
  render(<RetentionBridge matches={[makeMatch()]} />);
  await screen.findByText("The World Cup is over. The AI is still playing.");

  fireEvent.change(await screen.findByLabelText("Email address"), { target: { value: "fan@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: "Notify me" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
  // The NRL CTA is unaffected by the failed email POST.
  expect(screen.getByRole("link", { name: "See NRL predictions" })).toHaveAttribute("href", "/nrl/matches");
});
