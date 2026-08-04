import { act, render, screen } from "@testing-library/react";
import { getNrlLiveClient } from "@/lib/api";
import type { NrlLive, NrlMatch } from "@/lib/types";
import { LiveMatchProvider } from "./LiveMatchProvider";
import { NrlMatchHero } from "./NrlMatchHero";

jest.mock("@/lib/api");

const mockLive = getNrlLiveClient as jest.MockedFunction<typeof getNrlLiveClient>;

const scheduledMatch: NrlMatch = {
  id: 42,
  match_no: 3,
  // In the live window: the hero only believes a "live" payload while the
  // match could actually be running (see the stale-state tests below).
  kickoff_utc: new Date(Date.now() - 40 * 60_000).toISOString(),
  venue: "Leichhardt Oval",
  home: "Wests Tigers",
  away: "Warriors",
  home_team_id: 17,
  away_team_id: 16,
  score_home: null,
  score_away: null,
  status: "scheduled",
  prediction: {
    p_home: 0.311,
    p_draw: 0.017,
    p_away: 0.672,
    expected_margin: -5.5,
    model_version: "nrl-elo-v0.1",
    created_at: "2026-07-06T00:00:00Z",
    is_shadow: true,
  },
};
const finishedMatch: NrlMatch = {
  ...scheduledMatch,
  status: "finished",
  score_home: 12,
  score_away: 26,
};

const livePayload = (overrides: Partial<NrlLive> = {}): NrlLive => ({
  status: "live",
  minute: 1,
  score_home: 0,
  score_away: 0,
  live_home_prob: 0.5,
  events: [],
  ...overrides,
});

function renderHero(match: NrlMatch = scheduledMatch) {
  return render(
    <LiveMatchProvider match={match}>
      <NrlMatchHero match={match} home={match.home!} away={match.away!} />
    </LiveMatchProvider>,
  );
}

afterEach(() => jest.resetAllMocks());

it("keeps VS and the normal prediction copy before kickoff", async () => {
  mockLive.mockResolvedValue({
    ...livePayload(),
    status: "pre",
    minute: null,
    score_home: null,
    score_away: null,
  });
  renderHero();
  await act(async () => {});
  expect(screen.getByText("vs")).toBeInTheDocument();
  expect(screen.getByText(/Warriors to win · 67%/)).toBeInTheDocument();
});

it("shows the updating result and labels the prediction as pre-match while live", async () => {
  mockLive.mockResolvedValue(livePayload({ minute: 42, score_home: 12, score_away: 6 }));
  renderHero();
  expect(await screen.findByRole("status", {
    name: "Live match: Wests Tigers 12–6 Warriors, 42′",
  })).toHaveTextContent("LIVE · 42′");
  expect(screen.getByText("12–6")).toBeInTheDocument();
  expect(screen.getByText(/Pre-match model pick · Warriors 67%/)).toBeInTheDocument();
  expect(screen.queryByText(/ML model margin/)).not.toBeInTheDocument();
});

it("formats a partial live score without adding punctuation for a missing minute", async () => {
  mockLive.mockResolvedValue(livePayload({ minute: null, score_home: 12, score_away: null }));
  renderHero();

  expect(await screen.findByRole("status", {
    name: "Live match: Wests Tigers 12–– Warriors",
  })).toHaveTextContent("LIVE");
  expect(screen.getByRole("status")).not.toHaveTextContent("·");
  expect(screen.getByText("12––")).toBeInTheDocument();
});

it("preserves the full-time score and model verdict", () => {
  mockLive.mockReturnValue(new Promise(() => {}));
  renderHero(finishedMatch);
  expect(screen.getByText("Full time")).toBeInTheDocument();
  expect(screen.getByText("12–26")).toBeInTheDocument();
  expect(screen.getByText(/Called it/)).toBeInTheDocument();
});

// --- stale/contradictory live states must not produce a LIVE pill ----------

it("never renders LIVE and Full time together — full time wins", async () => {
  // A stale live-state row can survive grading: the match row says finished
  // while /live still answers "live". Two truths, one pill.
  mockLive.mockResolvedValue(livePayload({ minute: 74, score_home: 12, score_away: 26 }));
  renderHero(finishedMatch);
  await act(async () => {});
  expect(screen.getByText("Full time")).toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("does not pin LIVE on a match far past its window", async () => {
  // Poller died mid-match, ingest lagging: /live keeps answering "live"
  // with a frozen minute. The hero bounds liveness by kickoff, same as
  // every other NRL surface, so it degrades to the pre-match header.
  const staleMatch: NrlMatch = {
    ...scheduledMatch,
    kickoff_utc: new Date(Date.now() - 5 * 60 * 60_000).toISOString(), // 5h ago
  };
  mockLive.mockResolvedValue(livePayload({ minute: 63, score_home: 18, score_away: 12 }));
  renderHero(staleMatch);
  await act(async () => {});
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getByText("vs")).toBeInTheDocument();
});
