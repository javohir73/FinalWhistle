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
  kickoff_utc: "2026-07-11T09:35:00+00:00",
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
  expect(await screen.findByRole("status", { name: /live match/i })).toHaveTextContent(
    "LIVE · 42′",
  );
  expect(screen.getByText("12–6")).toBeInTheDocument();
  expect(screen.getByText(/Pre-match model pick · Warriors 67%/)).toBeInTheDocument();
  expect(screen.queryByText(/ML model margin/)).not.toBeInTheDocument();
});

it("preserves the full-time score and model verdict", () => {
  mockLive.mockReturnValue(new Promise(() => {}));
  renderHero(finishedMatch);
  expect(screen.getByText("Full time")).toBeInTheDocument();
  expect(screen.getByText("12–26")).toBeInTheDocument();
  expect(screen.getByText(/Called it/)).toBeInTheDocument();
});
