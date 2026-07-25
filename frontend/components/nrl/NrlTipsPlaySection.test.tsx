/** The NRL beat-the-AI loop's composition. Its leaf components each fetch on
 *  mount (device id, auth context, network), so they're stubbed the same way
 *  components/nrl/*.test.tsx do -- this test is about the section wiring, not
 *  their client fetch paths. Covers the Play-hub opt-out (Floodlight P5,
 *  p5-s4): showLeaderboard defaults true so /nrl/tips keeps its own weekly
 *  leaderboard, and false suppresses it so the hub's unified board can own it. */
import { render, screen } from "@testing-library/react";
import { NrlTipsPlaySection } from "./NrlTipsPlaySection";

jest.mock("@/components/nrl/ClaimDeviceTips", () => ({
  ClaimDeviceTips: () => <div data-testid="claim" />,
}));
jest.mock("@/components/nrl/PlayRound", () => ({
  PlayRound: ({ season, round }: { season: number; round: number }) => (
    <div data-testid="play-round">{`${season}-${round}`}</div>
  ),
}));
jest.mock("@/components/nrl/YouVsAi", () => ({
  YouVsAi: () => <div data-testid="you-vs-ai" />,
}));
jest.mock("@/components/nrl/NrlTipsLeaderboard", () => ({
  NrlTipsLeaderboard: ({ season, round }: { season: number; round: number }) => (
    <div data-testid="leaderboard">{`${season}-${round}`}</div>
  ),
}));

it("mounts the weekly leaderboard by default (showLeaderboard defaults true, /nrl/tips)", () => {
  render(<NrlTipsPlaySection season={2026} round={2} />);
  expect(screen.getByTestId("play-round")).toHaveTextContent("2026-2");
  expect(screen.getByTestId("leaderboard")).toHaveTextContent("2026-2");
});

it("keeps the weekly leaderboard out when showLeaderboard is false (hub hoists it)", () => {
  render(<NrlTipsPlaySection season={2026} round={2} showLeaderboard={false} />);
  // The rest of the loop still mounts -- only the board is suppressed.
  expect(screen.getByTestId("play-round")).toHaveTextContent("2026-2");
  expect(screen.queryByTestId("leaderboard")).not.toBeInTheDocument();
});
