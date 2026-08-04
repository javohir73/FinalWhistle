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
  // In the poll window: interval ticks only fetch while new data can actually
  // arrive (see the "does not poll" tests below).
  id: 42, match_no: 3, kickoff_utc: new Date(Date.now() - 20 * 60_000).toISOString(),
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
  return (
    <span>
      {state.data.status}:{state.data.minute}:{state.data.score_home}–{state.data.score_away}:{state.data.events.length}ev
    </span>
  );
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
  expect(await screen.findByText("live:18:6–0:0ev")).toBeInTheDocument();

  await act(async () => { jest.advanceTimersByTime(30_000); });
  expect(mockLive).toHaveBeenCalledTimes(2);
  expect(screen.getByText("live:18:6–0:0ev")).toBeInTheDocument();
});

it("publishes a successful 30-second refresh", async () => {
  jest.useFakeTimers();
  mockLive
    .mockResolvedValueOnce(livePayload({ minute: 18, score_home: 6, score_away: 0 }))
    .mockResolvedValueOnce(livePayload({ minute: 49, score_home: 12, score_away: 6 }));

  render(<LiveMatchProvider match={scheduledMatch}><Probe /></LiveMatchProvider>);
  expect(await screen.findByText("live:18:6–0:0ev")).toBeInTheDocument();

  await act(async () => { jest.advanceTimersByTime(30_000); });
  expect(mockLive).toHaveBeenCalledTimes(2);
  expect(screen.getByText("live:49:12–6:0ev")).toBeInTheDocument();
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
  expect(await screen.findByText("live:79:18–18:0ev")).toBeInTheDocument();

  await act(async () => { jest.advanceTimersByTime(30_000); });
  expect(screen.getByText("final:80:18–24:0ev")).toBeInTheDocument();

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
  expect(screen.getByText("live:49:12–6:0ev")).toBeInTheDocument();

  await act(async () => {
    older.resolve(livePayload({ minute: 18, score_home: 6, score_away: 0 }));
  });
  expect(screen.getByText("live:49:12–6:0ev")).toBeInTheDocument();
});

it("does not let an older request failure replace a newer score", async () => {
  jest.useFakeTimers();
  const older = deferred<NrlLive>();
  mockLive
    .mockReturnValueOnce(older.promise)
    .mockResolvedValueOnce(livePayload({ minute: 49, score_home: 12, score_away: 6 }));

  render(<LiveMatchProvider match={scheduledMatch}><Probe /></LiveMatchProvider>);
  await act(async () => { jest.advanceTimersByTime(30_000); });
  expect(await screen.findByText("live:49:12–6:0ev")).toBeInTheDocument();

  await act(async () => { older.reject(new Error("stale outage")); });
  expect(screen.getByText("live:49:12–6:0ev")).toBeInTheDocument();
});

// --- finished matches: instant seed, then the persisted record ------------
//
// The seed is a fabrication (empty timeline, 1/0 probability) built from the
// core match row so the hero paints with no loading flash. The persisted
// NrlLiveState/NrlLiveEvent record must still replace it — an earlier version
// returned early on the seed, which permanently hid every finished match's
// try timeline and closing probability.

it("seeds a finished match instantly, then replaces the seed with the persisted timeline", async () => {
  const pending = deferred<NrlLive>();
  mockLive.mockReturnValueOnce(pending.promise);

  render(<LiveMatchProvider match={finishedMatch}><Probe /></LiveMatchProvider>);
  // Synchronous first paint from the seed — the fetch is still in flight.
  expect(screen.getByText("final:80:12–26:0ev")).toBeInTheDocument();

  await act(async () => {
    pending.resolve(livePayload({
      status: "final", minute: 80, score_home: 12, score_away: 26,
      live_home_prob: 0.08,
      events: [{ minute: 44, type: "score", team: "away", player: null, prob_after: 0.2 }],
    }));
  });
  expect(screen.getByText("final:80:12–26:1ev")).toBeInTheDocument();
  expect(mockLive).toHaveBeenCalledTimes(1);
});

it("does not poll a finished match", async () => {
  jest.useFakeTimers();
  mockLive.mockResolvedValue(livePayload({ status: "final", minute: 80, score_home: 12, score_away: 26 }));

  render(<LiveMatchProvider match={finishedMatch}><Probe /></LiveMatchProvider>);
  await act(async () => { jest.advanceTimersByTime(120_000); });
  expect(mockLive).toHaveBeenCalledTimes(1); // the one replacement fetch, no interval
});

// --- polling only runs while new data can actually arrive -------------------
//
// The backend poller writes NrlLiveState only inside the match window, so a
// 30-second client poll outside it can never observe a change. A tab parked
// on a fixture days out (or on a match whose poller died hours ago) was
// hitting the Render free tier every 30s indefinitely, for a payload the UI
// discards. The interval keeps ticking — a parked tab still wakes up at
// kickoff — but each tick is a wall-clock check, not an HTTP request.

it("does not poll a fixture days before kickoff, but wakes up at kickoff", async () => {
  jest.useFakeTimers();
  const farFuture: NrlMatch = {
    ...scheduledMatch,
    kickoff_utc: new Date(Date.now() + 5 * 24 * 60 * 60_000).toISOString(),
  };
  mockLive.mockResolvedValue(livePayload({ status: "pre", minute: null }));

  render(<LiveMatchProvider match={farFuture}><Probe /></LiveMatchProvider>);
  await act(async () => {});
  expect(mockLive).toHaveBeenCalledTimes(1); // the initial load only

  await act(async () => { jest.advanceTimersByTime(60 * 60_000); }); // 1h parked
  expect(mockLive).toHaveBeenCalledTimes(1); // ticks skipped — no HTTP

  // ...five days later the same interval starts fetching again.
  await act(async () => { jest.advanceTimersByTime(5 * 24 * 60 * 60_000); });
  expect(mockLive.mock.calls.length).toBeGreaterThan(1);
});

it("stops fetching for a match far past its window even if the payload never says final", async () => {
  jest.useFakeTimers();
  const stale: NrlMatch = {
    ...scheduledMatch,
    kickoff_utc: new Date(Date.now() - 5 * 60 * 60_000).toISOString(), // 5h ago
  };
  mockLive.mockResolvedValue(livePayload({ minute: 63, score_home: 18, score_away: 12 }));

  render(<LiveMatchProvider match={stale}><Probe /></LiveMatchProvider>);
  await act(async () => {});
  expect(mockLive).toHaveBeenCalledTimes(1); // initial load still surfaces the state

  await act(async () => { jest.advanceTimersByTime(10 * 60_000); });
  expect(mockLive).toHaveBeenCalledTimes(1); // frozen row — nothing new can arrive
});

it("keeps the seed when the finished-match fetch fails", async () => {
  mockLive.mockRejectedValueOnce(new Error("endpoint down"));

  render(<LiveMatchProvider match={finishedMatch}><Probe /></LiveMatchProvider>);
  await act(async () => {}); // flush the rejected fetch
  // Still the seed, and still a success state — never an error screen over a
  // score we already know from the match row.
  expect(screen.getByText("final:80:12–26:0ev")).toBeInTheDocument();
});
