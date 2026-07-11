/** StatsSection: the client island wiring ScoringBreakdown + TryTimeline to
 *  GET /api/nrl/matches/{id}/stats. Covers the states the presentational
 *  component tests don't: skip-fetch for a non-finished match, the loading
 *  flash, the success render, and the quiet "not available" placeholder for
 *  both a 404 and an environment where `fetch` itself is unusable (this is
 *  also what protects Wave 1's page.test.tsx, which mounts every registered
 *  section -- this one included -- against a jsdom test env with no global
 *  fetch). */
import { render, screen } from "@testing-library/react";
import StatsSection from "./StatsSection";
import type { NrlMatchDetail, NrlMatchStatsResponse } from "@/lib/types";

const detail = (status: string): NrlMatchDetail => ({
  match: {
    id: 42, season: 2026, round: 19, match_no: 3,
    kickoff_utc: "2026-07-11T09:35:00+00:00", venue: "Leichhardt Oval",
    home: "Wests Tigers", away: "Warriors",
    home_team_id: 17, away_team_id: 16,
    score_home: status === "finished" ? 24 : null,
    score_away: status === "finished" ? 18 : null,
    status,
  },
  prediction: null,
  form: { home: null, away: null },
  h2h: [],
  factors: [],
});

const statsPayload: NrlMatchStatsResponse = {
  home: {
    tries: 4, conversions: 3, penalties_conceded: 5, errors: 9,
    set_restarts: 3, run_metres: 1580, line_breaks: 5, tackles: 300,
    tackle_efficiency: 90.1,
  },
  away: {
    tries: 3, conversions: 2, penalties_conceded: 7, errors: 10,
    set_restarts: 5, run_metres: 1410, line_breaks: 2, tackles: 330,
    tackle_efficiency: 87.4,
  },
  try_timeline: [
    { minute: 12, team: "Wests Tigers", player: "A. Player", score_home: 6, score_away: 0 },
  ],
};

function setFetchMock(fn: jest.Mock): void {
  global.fetch = fn as unknown as typeof fetch;
}

function mockFetchResolved(ok: boolean, status: number, body?: unknown): jest.Mock {
  const fn = jest.fn().mockResolvedValue({
    ok,
    status,
    json: () => Promise.resolve(body),
  });
  setFetchMock(fn);
  return fn;
}

afterEach(() => {
  Reflect.deleteProperty(global, "fetch");
  jest.restoreAllMocks();
});

test("skips the fetch and shows the quiet placeholder for a match that hasn't finished", () => {
  const fetchSpy = jest.fn();
  setFetchMock(fetchSpy);

  render(<StatsSection detail={detail("scheduled")} probHistory={null} />);

  expect(screen.getByText(/published after full time/i)).toBeInTheDocument();
  expect(fetchSpy).not.toHaveBeenCalled();
});

test("shows a loading state while the stats fetch for a finished match is in flight", () => {
  setFetchMock(jest.fn(() => new Promise(() => {})));

  render(<StatsSection detail={detail("finished")} probHistory={null} />);

  expect(screen.getByText(/loading match stats/i)).toBeInTheDocument();
});

test("renders scoring breakdown and try timeline once stats load", async () => {
  mockFetchResolved(true, 200, statsPayload);

  render(<StatsSection detail={detail("finished")} probHistory={null} />);

  expect(
    await screen.findByRole("heading", { name: "Scoring breakdown" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Try timeline" })).toBeInTheDocument();
  expect(screen.getByText("A. Player")).toBeInTheDocument();
  // Team names are threaded through from detail.match, not inferred.
  expect(screen.getByText(/Wests Tigers left, Warriors right/)).toBeInTheDocument();
});

test("shows the quiet placeholder when stats aren't available yet (404)", async () => {
  mockFetchResolved(false, 404);

  render(<StatsSection detail={detail("finished")} probHistory={null} />);

  expect(
    await screen.findByText(/published after full time/i),
  ).toBeInTheDocument();
});

test("shows the quiet placeholder instead of crashing when fetch itself is unusable", () => {
  Reflect.deleteProperty(global, "fetch");

  render(<StatsSection detail={detail("finished")} probHistory={null} />);

  expect(screen.getByText(/published after full time/i)).toBeInTheDocument();
});
