/** p5-s5: the shared ConfidenceRing on model-backed play rows. The ring is
 *  additive and gated on `showConfidence` -- the /nrl/tips path (flag off) is
 *  unchanged, and a match with no model prediction degrades to no ring. */
import { render, screen } from "@testing-library/react";
import { PlayRound } from "./PlayRound";
import { getMyNrlTips } from "@/lib/nrlTips";
import { getOrCreateDeviceId, pingDailyActivity } from "@/lib/session";
import type { NrlMyTipModel, NrlMyTipsResponse } from "@/lib/types";

jest.mock("@/lib/nrlTips");
jest.mock("@/lib/session", () => {
  const actual = jest.requireActual("@/lib/session");
  return { ...actual, getOrCreateDeviceId: jest.fn(), pingDailyActivity: jest.fn() };
});

const mockMine = getMyNrlTips as jest.MockedFunction<typeof getMyNrlTips>;
const mockDeviceId = getOrCreateDeviceId as jest.MockedFunction<typeof getOrCreateDeviceId>;
const mockPing = pingDailyActivity as jest.MockedFunction<typeof pingDailyActivity>;

beforeEach(() => {
  localStorage.clear();
  mockDeviceId.mockReturnValue("device-1");
  mockPing.mockResolvedValue(undefined);
});
afterEach(() => jest.resetAllMocks());

const future = (mins: number) => new Date(Date.now() + mins * 60_000).toISOString();

// One scheduled, un-tipped match so exactly one ring is in play. `model` is a
// param so a test can null it out for the degrade case.
function oneMatch(model: NrlMyTipModel | null): NrlMyTipsResponse {
  return {
    season: 2026,
    round: 3,
    handle: "SwiftHalfback482",
    matches: [
      {
        id: 1, home: "Storm", away: "Eels", kickoff_utc: future(60), status: "scheduled",
        score_home: null, score_away: null, is_featured: false,
        model,
        your_tip: null,
      },
    ],
    disclaimer: "For analytics and entertainment only. Not betting advice.",
  };
}

it("rings the model's call with the printed % and tier word when showConfidence is on", async () => {
  // 0.62 -> Medium (>=0.5, <0.65), home pick -> "Storm".
  mockMine.mockResolvedValue(oneMatch({ pick: "home", pick_confidence: 0.62, expected_margin: 4.5 }));

  render(<PlayRound season={2026} round={3} showConfidence />);
  await screen.findByText("Model's call");

  const ring = screen.getByRole("img");
  expect(ring).toHaveAttribute("aria-label", expect.stringContaining("Storm 62%, Medium confidence"));
  expect(screen.getByText("62")).toBeInTheDocument();
  expect(screen.getByText("MEDIUM")).toBeInTheDocument();
  // The team the ring refers to is printed as text, not colour-only.
  expect(screen.getAllByText("Storm").length).toBeGreaterThan(0);
});

it("renders no ring on the /nrl/tips path (flag off, default)", async () => {
  mockMine.mockResolvedValue(oneMatch({ pick: "home", pick_confidence: 0.62, expected_margin: 4.5 }));

  render(<PlayRound season={2026} round={3} />);
  await screen.findByRole("group", { name: /Storm vs Eels/i });

  expect(screen.queryByText("Model's call")).not.toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});

it("degrades to no ring when the match carries no model, even with the flag on", async () => {
  mockMine.mockResolvedValue(oneMatch(null));

  render(<PlayRound season={2026} round={3} showConfidence />);
  await screen.findByRole("group", { name: /Storm vs Eels/i });

  expect(screen.queryByText("Model's call")).not.toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});
