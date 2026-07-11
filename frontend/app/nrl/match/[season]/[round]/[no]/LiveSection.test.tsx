/** LiveSection: the client island wiring the fixed pinned live strip +
 *  scoreboard card to GET /api/nrl/matches/{id}/live (60s poll via
 *  useFetch). Adapted from the Task 9 brief's async-server-component design
 *  to this codebase's actual `IntelSectionProps` contract
 *  (`{detail, probHistory}`, rendered synchronously from the "use client"
 *  MatchIntelClient) — see task-9-report.md for the full drift note. The
 *  pinned strip is portalled to document.body, so it is asserted through
 *  `screen` (which searches the whole body), never through `container`. */
import { render, screen, waitFor } from "@testing-library/react";
import LiveSection from "./LiveSection";
import { getNrlLiveClient } from "@/lib/api";
import type { NrlLive, NrlMatchDetail } from "@/lib/types";

jest.mock("@/lib/api");
const mockLiveClient = getNrlLiveClient as jest.MockedFunction<typeof getNrlLiveClient>;

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
  mockLiveClient.mockResolvedValue(pre);

  const { container } = render(<LiveSection detail={detail("scheduled")} probHistory={null} />);
  await waitFor(() => expect(mockLiveClient).toHaveBeenCalledTimes(1));
  expect(container).toBeEmptyDOMElement();
  // No pinned strip either (it portals to document.body, outside `container`).
  expect(screen.queryByRole("status", { name: /live score/i })).not.toBeInTheDocument();
});

it("renders the pinned fixed strip and score while in progress", async () => {
  const live: NrlLive = {
    status: "live", minute: 42, score_home: 12, score_away: 6, live_home_prob: 0.71,
    events: [{ minute: 10, type: "score", team: "home", player: null, prob_after: 0.55 }],
  };
  mockLiveClient.mockResolvedValue(live);

  render(<LiveSection detail={detail("in_play")} probHistory={null} />);

  // The pinned strip is fixed-positioned and portalled to document.body so a
  // live match is visible on initial load regardless of section DOM order.
  const strip = await screen.findByRole("status", { name: /live score/i });
  expect(strip).toBeInTheDocument();
  expect(screen.getByText("71%")).toBeInTheDocument();
  expect(screen.getByText(/12–6/)).toBeInTheDocument();
});

it("renders a Final card with no live badge and no pinned strip once the match ends", async () => {
  const final: NrlLive = {
    status: "final", minute: 80, score_home: 24, score_away: 10,
    live_home_prob: 1.0, events: [],
  };
  mockLiveClient.mockResolvedValue(final);

  render(<LiveSection detail={detail("finished", { home: 24, away: 10 })} probHistory={null} />);

  expect(await screen.findByText("Final")).toBeInTheDocument();
  expect(screen.queryByText(/Live ·/)).not.toBeInTheDocument();
  expect(screen.queryByRole("status", { name: /live score/i })).not.toBeInTheDocument();
});

it("paints a finished match's Final card from detail.match before any fetch resolves", () => {
  // A fetch that never resolves: the first paint must come from the seed
  // built off detail.match (status/scores already on the page).
  mockLiveClient.mockReturnValue(new Promise(() => {}));

  render(<LiveSection detail={detail("finished", { home: 24, away: 10 })} probHistory={null} />);

  expect(screen.getByText("Final")).toBeInTheDocument();
  expect(screen.getByText("24")).toBeInTheDocument();
  expect(screen.getByText("10")).toBeInTheDocument();
  expect(screen.queryByRole("status", { name: /live score/i })).not.toBeInTheDocument();
});

it("shows the quiet unavailable message when the live fetch fails", async () => {
  mockLiveClient.mockRejectedValue(new Error("offline"));

  render(<LiveSection detail={detail("in_play")} probHistory={null} />);

  expect(await screen.findByText(/live updates are unavailable/i)).toBeInTheDocument();
});

it("never renders odds or value badges", async () => {
  const live: NrlLive = {
    status: "live", minute: 5, score_home: 0, score_away: 0, live_home_prob: 0.5, events: [],
  };
  mockLiveClient.mockResolvedValue(live);

  render(<LiveSection detail={detail("in_play")} probHistory={null} />);

  expect(await screen.findByText("Live")).toBeInTheDocument();
  expect(screen.queryByText(/odds/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/value/i)).not.toBeInTheDocument();
});
