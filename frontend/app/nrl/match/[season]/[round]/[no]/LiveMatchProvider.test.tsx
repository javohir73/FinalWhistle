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

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, reject, resolve };
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
  expect(mockLive).toHaveBeenCalledTimes(2);
  expect(screen.getByText("live:18:6–0")).toBeInTheDocument();
});

it("publishes a successful 30-second refresh", async () => {
  jest.useFakeTimers();
  mockLive
    .mockResolvedValueOnce(livePayload({ minute: 18, score_home: 6, score_away: 0 }))
    .mockResolvedValueOnce(livePayload({ minute: 49, score_home: 12, score_away: 6 }));

  render(<LiveMatchProvider match={scheduledMatch}><Probe /></LiveMatchProvider>);
  expect(await screen.findByText("live:18:6–0")).toBeInTheDocument();

  await act(async () => { jest.advanceTimersByTime(30_000); });
  expect(mockLive).toHaveBeenCalledTimes(2);
  expect(screen.getByText("live:49:12–6")).toBeInTheDocument();
});

it("stops polling after a refresh reports the final score", async () => {
  jest.useFakeTimers();
  const final = livePayload({
    status: "final", minute: 80, score_home: 18, score_away: 24,
  });
  mockLive
    .mockResolvedValueOnce(livePayload({ minute: 79, score_home: 18, score_away: 18 }))
    .mockResolvedValue(final);

  render(<LiveMatchProvider match={scheduledMatch}><Probe /></LiveMatchProvider>);
  expect(await screen.findByText("live:79:18–18")).toBeInTheDocument();

  await act(async () => { jest.advanceTimersByTime(30_000); });
  expect(screen.getByText("final:80:18–24")).toBeInTheDocument();

  await act(async () => { jest.advanceTimersByTime(60_000); });
  expect(mockLive).toHaveBeenCalledTimes(2);
});

it("does not let an older overlapping response replace a newer score", async () => {
  jest.useFakeTimers();
  const older = deferred<NrlLive>();
  const newer = deferred<NrlLive>();
  mockLive
    .mockReturnValueOnce(older.promise)
    .mockReturnValueOnce(newer.promise);

  render(<LiveMatchProvider match={scheduledMatch}><Probe /></LiveMatchProvider>);
  expect(mockLive).toHaveBeenCalledTimes(1);

  await act(async () => { jest.advanceTimersByTime(30_000); });
  expect(mockLive).toHaveBeenCalledTimes(2);

  await act(async () => {
    newer.resolve(livePayload({ minute: 49, score_home: 12, score_away: 6 }));
  });
  expect(screen.getByText("live:49:12–6")).toBeInTheDocument();

  await act(async () => {
    older.resolve(livePayload({ minute: 18, score_home: 6, score_away: 0 }));
  });
  expect(screen.getByText("live:49:12–6")).toBeInTheDocument();
});

it("does not let an older request failure replace a newer score", async () => {
  jest.useFakeTimers();
  const older = deferred<NrlLive>();
  mockLive
    .mockReturnValueOnce(older.promise)
    .mockResolvedValueOnce(livePayload({ minute: 49, score_home: 12, score_away: 6 }));

  render(<LiveMatchProvider match={scheduledMatch}><Probe /></LiveMatchProvider>);
  await act(async () => { jest.advanceTimersByTime(30_000); });
  expect(await screen.findByText("live:49:12–6")).toBeInTheDocument();

  await act(async () => { older.reject(new Error("stale outage")); });
  expect(screen.getByText("live:49:12–6")).toBeInTheDocument();
});

it("seeds a finished match without waiting for the endpoint", () => {
  render(<LiveMatchProvider match={finishedMatch}><Probe /></LiveMatchProvider>);
  expect(screen.getByText("final:80:12–26")).toBeInTheDocument();
  expect(mockLive).not.toHaveBeenCalled();
});
