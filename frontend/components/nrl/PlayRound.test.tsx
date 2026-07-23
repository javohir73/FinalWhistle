import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { PlayRound } from "./PlayRound";
import { getMyNrlTips, submitNrlTip } from "@/lib/nrlTips";
import { ApiError, getOrCreateDeviceId, pingDailyActivity } from "@/lib/session";
import type { NrlMyTipsResponse } from "@/lib/types";

jest.mock("@/lib/nrlTips");
jest.mock("@/lib/session", () => {
  const actual = jest.requireActual("@/lib/session");
  return { ...actual, getOrCreateDeviceId: jest.fn(), pingDailyActivity: jest.fn() };
});

const mockMine = getMyNrlTips as jest.MockedFunction<typeof getMyNrlTips>;
const mockSubmit = submitNrlTip as jest.MockedFunction<typeof submitNrlTip>;
const mockDeviceId = getOrCreateDeviceId as jest.MockedFunction<typeof getOrCreateDeviceId>;
const mockPing = pingDailyActivity as jest.MockedFunction<typeof pingDailyActivity>;

// resetAllMocks (below) wipes any implementation set inside the jest.mock
// factory too, so the device id / ping stubs are (re)installed per test here
// rather than baked in above. localStorage also isn't reset between tests by
// default -- a confirmed submit's cache write (see PlayRound's writeCache)
// must not leak a stale pick into a later test's initial render.
beforeEach(() => {
  localStorage.clear();
  mockDeviceId.mockReturnValue("device-1");
  mockPing.mockResolvedValue(undefined);
});

const future = (mins: number) => new Date(Date.now() + mins * 60_000).toISOString();
const past = (mins: number) => new Date(Date.now() - mins * 60_000).toISOString();

function mine(overrides: Partial<NrlMyTipsResponse> = {}): NrlMyTipsResponse {
  return {
    season: 2026,
    round: 3,
    handle: "SwiftHalfback482",
    matches: [
      {
        id: 1, home: "Storm", away: "Eels", kickoff_utc: future(60), status: "scheduled",
        score_home: null, score_away: null, is_featured: true,
        model: { pick: "home", pick_confidence: 0.62, expected_margin: 4.5 },
        your_tip: null,
      },
      {
        id: 2, home: "Broncos", away: "Titans", kickoff_utc: future(120), status: "scheduled",
        score_home: null, score_away: null, is_featured: false,
        model: { pick: "away", pick_confidence: 0.55, expected_margin: -2 },
        your_tip: null,
      },
    ],
    disclaimer: "For analytics and entertainment only. Not betting advice.",
    ...overrides,
  };
}

afterEach(() => jest.resetAllMocks());

it("submits the device id, match and pick payload for a tapped pick", async () => {
  mockMine.mockResolvedValue(mine());
  mockSubmit.mockResolvedValue({
    ok: true, handle: "SwiftHalfback482",
    tip: { match_id: 1, pick: "home", margin: null, updated_at: "2026-07-24T09:00:00+00:00" },
  });

  render(<PlayRound season={2026} round={3} />);
  const group = await screen.findByRole("group", { name: /Storm vs Eels/i });
  fireEvent.click(within(group).getByRole("button", { name: "Storm" }));

  await waitFor(() =>
    expect(mockSubmit).toHaveBeenCalledWith({ device_id: "device-1", match_id: 1, pick: "home", margin: null }),
  );
  expect(within(group).getByRole("button", { name: "Storm" })).toHaveAttribute("aria-pressed", "true");
});

it("renders a kickoff-locked row frozen, with no pick controls", async () => {
  mockMine.mockResolvedValue(
    mine({
      matches: [
        {
          id: 3, home: "Panthers", away: "Sharks", kickoff_utc: past(10), status: "scheduled",
          score_home: null, score_away: null, is_featured: false,
          model: { pick: "home", pick_confidence: 0.7, expected_margin: 6 },
          your_tip: {
            pick: "home", margin: null, points: null, round_margin: null,
            graded_at: null, updated_at: "2026-07-20T00:00:00Z",
          },
        },
      ],
    }),
  );

  render(<PlayRound season={2026} round={3} />);
  expect(await screen.findByText("Locked")).toBeInTheDocument();
  expect(screen.getByText(/You picked/)).toBeInTheDocument();
  expect(screen.getByText(/awaiting full time/)).toBeInTheDocument();
  expect(screen.queryByRole("group")).not.toBeInTheDocument();
});

it("shows the no-tip-submitted state for a locked match the device never tipped", async () => {
  mockMine.mockResolvedValue(
    mine({
      matches: [
        {
          id: 4, home: "Dragons", away: "Roosters", kickoff_utc: past(5), status: "scheduled",
          score_home: null, score_away: null, is_featured: false,
          model: { pick: "away", pick_confidence: 0.58, expected_margin: -3 },
          your_tip: null,
        },
      ],
    }),
  );

  render(<PlayRound season={2026} round={3} />);
  expect(await screen.findByText("No tip submitted")).toBeInTheDocument();
});

it("shows the margin input only on the featured match", async () => {
  mockMine.mockResolvedValue(mine());
  render(<PlayRound season={2026} round={3} />);
  await screen.findByRole("group", { name: /Storm vs Eels/i });

  expect(screen.getByText("Featured match — margin for tiebreaks")).toBeInTheDocument();
  expect(screen.getAllByRole("spinbutton")).toHaveLength(1);
});

it("surfaces a rejected submit honestly and reverts the optimistic pick", async () => {
  mockMine.mockResolvedValue(mine());
  mockSubmit.mockRejectedValue(new ApiError(422, "match_locked", "Match 1 has kicked off and is locked."));

  render(<PlayRound season={2026} round={3} />);
  const group = await screen.findByRole("group", { name: /Storm vs Eels/i });
  fireEvent.click(within(group).getByRole("button", { name: "Storm" }));

  expect(await screen.findByText("Match 1 has kicked off and is locked.")).toBeInTheDocument();
  expect(within(group).getByRole("button", { name: "Storm" })).toHaveAttribute("aria-pressed", "false");
});
