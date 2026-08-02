import { act, render, screen } from "@testing-library/react";
import { getNrlLiveClient } from "@/lib/api";
import type { NrlLive, NrlMatch } from "@/lib/types";
import { LiveMatchProvider, useLiveMatch } from "./LiveMatchProvider";

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
  id: 42, match_no: 3, kickoff_utc: "2026-08-02T04:00:00Z",
  venue: "Ocean Protect Stadium", home: "Sharks", away: "Rabbitohs",
  home_team_id: 1, away_team_id: 2, score_home: null, score_away: null,
  status: "scheduled", prediction: null,
};
const finishedMatch: NrlMatch = {
  ...scheduledMatch, status: "finished", score_home: 12, score_away: 26,
};

function Probe() {
  const state = useLiveMatch();
  if (state.status !== "success") return <span>{state.status}</span>;
  return <span>{state.data.status}:{state.data.minute}:{state.data.score_home}–{state.data.score_away}</span>;
}

afterEach(() => {
  jest.useRealTimers();
  jest.resetAllMocks();
});

it("publishes live data and keeps it when a later poll fails", async () => {
  jest.useFakeTimers();
  mockLive
    .mockResolvedValueOnce(livePayload({ minute: 18, score_home: 6, score_away: 0 }))
    .mockRejectedValueOnce(new Error("temporary outage"));

  render(<LiveMatchProvider match={scheduledMatch}><Probe /></LiveMatchProvider>);
  expect(await screen.findByText("live:18:6–0")).toBeInTheDocument();

  await act(async () => { jest.advanceTimersByTime(30_000); });
  expect(screen.getByText("live:18:6–0")).toBeInTheDocument();
});

it("seeds a finished match without waiting for the endpoint", () => {
  mockLive.mockReturnValue(new Promise(() => {}));

  render(<LiveMatchProvider match={finishedMatch}><Probe /></LiveMatchProvider>);
  expect(screen.getByText("final:80:12–26")).toBeInTheDocument();
});
