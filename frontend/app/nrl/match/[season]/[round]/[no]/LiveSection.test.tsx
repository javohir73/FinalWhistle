/** LiveSection: the client island wiring the sticky live banner + scoreboard
 *  to GET /api/nrl/matches/{id}/live (60s poll via useFetch). Adapted from
 *  the Task 9 brief's async-server-component design to this codebase's
 *  actual `IntelSectionProps` contract (`{detail, probHistory}`, rendered
 *  synchronously from the "use client" MatchIntelClient) — see
 *  task-9-report.md for the full drift note. */
import { render, screen, waitFor } from "@testing-library/react";
import LiveSection from "./LiveSection";
import { getNrlLiveClient } from "@/lib/api";
import type { NrlLive, NrlMatchDetail } from "@/lib/types";

jest.mock("@/lib/api");
const mockLiveClient = getNrlLiveClient as jest.MockedFunction<typeof getNrlLiveClient>;

afterEach(() => jest.resetAllMocks());

function detail(status: string): NrlMatchDetail {
  return {
    match: {
      id: 1, season: 2026, round: 19, match_no: 3,
      kickoff_utc: "2026-07-11T09:35:00+00:00", venue: "Suncorp Stadium",
      home: "Broncos", away: "Storm",
      home_team_id: 1, away_team_id: 2,
      score_home: null, score_away: null,
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
});

it("renders the live banner and score while in progress", async () => {
  const live: NrlLive = {
    status: "live", minute: 42, score_home: 12, score_away: 6, live_home_prob: 0.71,
    events: [{ minute: 10, type: "score", team: "home", player: null, prob_after: 0.55 }],
  };
  mockLiveClient.mockResolvedValue(live);

  render(<LiveSection detail={detail("in_progress")} probHistory={null} />);

  expect(await screen.findByText("71%")).toBeInTheDocument();
  expect(screen.getByText(/12–6/)).toBeInTheDocument();
});

it("renders a Final card with no live badge once the match ends", async () => {
  const final: NrlLive = {
    status: "final", minute: 80, score_home: 24, score_away: 10,
    live_home_prob: 1.0, events: [],
  };
  mockLiveClient.mockResolvedValue(final);

  render(<LiveSection detail={detail("finished")} probHistory={null} />);

  expect(await screen.findByText("Final")).toBeInTheDocument();
  expect(screen.queryByText(/Live ·/)).not.toBeInTheDocument();
});

it("never renders odds or value badges", async () => {
  const live: NrlLive = {
    status: "live", minute: 5, score_home: 0, score_away: 0, live_home_prob: 0.5, events: [],
  };
  mockLiveClient.mockResolvedValue(live);

  render(<LiveSection detail={detail("in_progress")} probHistory={null} />);

  expect(await screen.findByText("Live")).toBeInTheDocument();
  expect(screen.queryByText(/odds/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/value/i)).not.toBeInTheDocument();
});
