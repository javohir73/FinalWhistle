/** WC26 retention bridge banner: shown only once the final has finished (per
 *  the matches feed the home dashboard already polls — never a hardcoded
 *  date/clock check), dismissible permanently, and the NRL CTA must survive
 *  a failed email-capture POST (the backend may deploy after the frontend). */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RetentionBridge } from "@/components/RetentionBridge";
import * as session from "@/lib/session";
import type { MatchSummary } from "@/lib/types";

jest.mock("@/lib/session");
const mockNotifyBridge = session.notifyBridge as jest.MockedFunction<typeof session.notifyBridge>;

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

it("points the Premier League CTA at the live tips page", async () => {
  render(<RetentionBridge matches={[makeMatch()]} />);
  await screen.findByText("The World Cup is over. The AI is still playing.");
  expect(screen.getByText(/Premier League tips are live/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Play Premier League tips" })).toHaveAttribute("href", "/tips");
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

  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "fan@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: "Notify me" }));

  expect(await screen.findByText("Done — one email, mid-August, no spam.")).toBeInTheDocument();
  expect(mockNotifyBridge).toHaveBeenCalledWith("fan@example.com", "wc26_final_bridge");
});

it("shows an inline error on failure but keeps the NRL CTA working", async () => {
  mockNotifyBridge.mockRejectedValue(new Error("network down"));
  render(<RetentionBridge matches={[makeMatch()]} />);
  await screen.findByText("The World Cup is over. The AI is still playing.");

  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "fan@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: "Notify me" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
  // The NRL CTA is unaffected by the failed email POST.
  expect(screen.getByRole("link", { name: "See NRL predictions" })).toHaveAttribute("href", "/nrl/matches");
});
