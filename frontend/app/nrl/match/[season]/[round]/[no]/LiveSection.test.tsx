/** LiveSection presents the shared live-match state as a scoreboard card and,
 *  while play is in progress, a fixed strip portalled to document.body. */
import { render, screen, waitFor } from "@testing-library/react";
import LiveSection from "./LiveSection";
import { LiveMatchProvider } from "./LiveMatchProvider";
import { getNrlLiveClient } from "@/lib/api";
import type { NrlLive, NrlMatch, NrlMatchDetail } from "@/lib/types";

jest.mock("@/lib/api");
const mockLive = getNrlLiveClient as jest.MockedFunction<typeof getNrlLiveClient>;

const livePayload = (overrides: Partial<NrlLive> = {}): NrlLive => ({
  status: "live",
  minute: 1,
  score_home: 0,
  score_away: 0,
  live_home_prob: 0.5,
  events: [],
  ...overrides,
});

const scheduledMatch: NrlMatch = {
  id: 1, match_no: 3,
  kickoff_utc: "2026-07-11T09:35:00+00:00", venue: "Suncorp Stadium",
  home: "Broncos", away: "Storm", home_team_id: 1, away_team_id: 2,
  score_home: null, score_away: null, status: "scheduled", prediction: null,
};

afterEach(() => jest.resetAllMocks());

function detail(status: string, scores?: { home: number; away: number }): NrlMatchDetail {
  return {
    match: {
      id: 1, season: 2026, round: 19, match_no: 3,
      kickoff_utc: "2026-07-11T09:35:00+00:00", venue: "Suncorp Stadium",
      home: "Broncos", away: "Storm",
      home_team_id: 1, away_team_id: 2,
      score_home: scores?.home ?? null, score_away: scores?.away ?? null,
      status,
    },
    prediction: null,
    form: { home: null, away: null },
    h2h: [],
    factors: [],
  };
}

it("renders nothing before kickoff", async () => {
  const pre: NrlLive = {
    status: "pre", minute: null, score_home: null, score_away: null,
    live_home_prob: 0.6, events: [],
  };
  mockLive.mockResolvedValue(pre);

  const { container } = render(
    <LiveMatchProvider match={scheduledMatch}>
      <LiveSection detail={detail("scheduled")} probHistory={null} />
    </LiveMatchProvider>,
  );
  await waitFor(() => expect(mockLive).toHaveBeenCalledTimes(1));
  expect(container).toBeEmptyDOMElement();
  // No pinned strip either (it portals to document.body, outside `container`).
  expect(screen.queryByRole("status", { name: /live score/i })).not.toBeInTheDocument();
});

it("renders the shared live payload without starting another request", async () => {
  mockLive.mockResolvedValue(livePayload({
    minute: 42,
    score_home: 12,
    score_away: 6,
    live_home_prob: 0.71,
    events: [{ minute: 10, type: "score", team: "home", player: null, prob_after: 0.55 }],
  }));

  render(
    <LiveMatchProvider match={scheduledMatch}>
      <LiveSection detail={detail("in_play")} probHistory={null} />
    </LiveMatchProvider>,
  );

  // The pinned strip is fixed-positioned and portalled to document.body so a
  // live match is visible on initial load regardless of section DOM order.
  const strip = await screen.findByRole("status", { name: /live score/i });
  expect(strip).toBeInTheDocument();
  expect(strip).toHaveTextContent("Broncos 12–6 Storm");
  expect(screen.getByText("71%")).toBeInTheDocument();
  expect(screen.getByText(/12–6/)).toBeInTheDocument();
  expect(mockLive).toHaveBeenCalledTimes(1);
});

it("renders a Final card with no live badge and no pinned strip once the match ends", async () => {
  const final: NrlLive = {
    status: "final", minute: 80, score_home: 24, score_away: 10,
    live_home_prob: 1.0, events: [],
  };
  mockLive.mockResolvedValue(final);

  render(
    <LiveMatchProvider match={{ ...scheduledMatch, status: "finished", score_home: 24, score_away: 10 }}>
      <LiveSection detail={detail("finished", { home: 24, away: 10 })} probHistory={null} />
    </LiveMatchProvider>,
  );

  expect(await screen.findByText("Final")).toBeInTheDocument();
  expect(screen.queryByText(/Live ·/)).not.toBeInTheDocument();
  expect(screen.queryByRole("status", { name: /live score/i })).not.toBeInTheDocument();
});

it("paints a finished match's Final card from detail.match before any fetch resolves", () => {
  // A fetch that never resolves: the first paint must come from the seed
  // built off detail.match (status/scores already on the page).
  mockLive.mockReturnValue(new Promise(() => {}));

  render(
    <LiveMatchProvider match={{ ...scheduledMatch, status: "finished", score_home: 24, score_away: 10 }}>
      <LiveSection detail={detail("finished", { home: 24, away: 10 })} probHistory={null} />
    </LiveMatchProvider>,
  );

  expect(screen.getByText("Final")).toBeInTheDocument();
  expect(screen.getByText("24")).toBeInTheDocument();
  expect(screen.getByText("10")).toBeInTheDocument();
  expect(screen.queryByRole("status", { name: /live score/i })).not.toBeInTheDocument();
});

it("shows the quiet unavailable message when the live fetch fails", async () => {
  mockLive.mockRejectedValue(new Error("offline"));

  render(
    <LiveMatchProvider match={scheduledMatch}>
      <LiveSection detail={detail("in_play")} probHistory={null} />
    </LiveMatchProvider>,
  );

  expect(await screen.findByText(/live updates are unavailable/i)).toBeInTheDocument();
});

it("never renders odds or value badges", async () => {
  const live: NrlLive = {
    status: "live", minute: 5, score_home: 0, score_away: 0, live_home_prob: 0.5, events: [],
  };
  mockLive.mockResolvedValue(live);

  render(
    <LiveMatchProvider match={scheduledMatch}>
      <LiveSection detail={detail("in_play")} probHistory={null} />
    </LiveMatchProvider>,
  );

  expect(await screen.findByText("Live")).toBeInTheDocument();
  expect(screen.queryByText(/odds/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/value/i)).not.toBeInTheDocument();
});
