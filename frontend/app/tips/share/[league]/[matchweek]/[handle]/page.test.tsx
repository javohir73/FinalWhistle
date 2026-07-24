/** League tips share-card page tests — server component (SSR) output. Every
 *  case is 404-or-render: an unknown handle, an ungraded matchweek, and a
 *  non-numeric route segment all resolve to notFound() (see the backend's
 *  predictions_share, which 404s identically in every one of those cases). */
import { render, screen } from "@testing-library/react";
import LeagueTipsShareCardPage from "./page";
import { getLeagueTipsShareServer } from "@/lib/api";
import type { LeagueTipsShareResponse } from "@/lib/types";

jest.mock("@/lib/api");
const mockShare = getLeagueTipsShareServer as jest.MockedFunction<typeof getLeagueTipsShareServer>;

const share: LeagueTipsShareResponse = {
  handle_display: "SwiftStriker123",
  league: "epl",
  matchweek: 7,
  player_points: 7,
  player_of: 8,
  model_points: 6,
  model_of: 8,
  matchweek_complete: true,
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

const params = (league = "epl", matchweek = "7", handle = "SwiftStriker123") =>
  Promise.resolve({ league, matchweek, handle });

afterEach(() => jest.resetAllMocks());

it("renders the graded result, the CTA and the disclaimer", async () => {
  mockShare.mockResolvedValue(share);
  render(await LeagueTipsShareCardPage({ params: params() }));

  expect(mockShare).toHaveBeenCalledWith("epl", 7, "SwiftStriker123");
  expect(
    screen.getByText(/SwiftStriker123 went 7\/8 — the AI went\s*6\/8/),
  ).toBeInTheDocument();
  expect(screen.getByText("SwiftStriker123 beat the AI this matchweek")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Play against the AI/i })).toHaveAttribute("href", "/tips");
  expect(screen.getByText(share.disclaimer)).toBeInTheDocument();
});

it("frames the AI winning honestly when the model out-scored the player", async () => {
  mockShare.mockResolvedValue({ ...share, player_points: 4, model_points: 6 });
  render(await LeagueTipsShareCardPage({ params: params() }));

  expect(screen.getByText("The AI came out on top this matchweek")).toBeInTheDocument();
});

it("frames a draw honestly when the two scores tie", async () => {
  mockShare.mockResolvedValue({ ...share, player_points: 6, model_points: 6 });
  render(await LeagueTipsShareCardPage({ params: params() }));

  expect(screen.getByText("SwiftStriker123 drew with the AI this matchweek")).toBeInTheDocument();
});

it("softens the verdict to 'so far' and flags progress when the matchweek isn't fully graded", async () => {
  mockShare.mockResolvedValue({ ...share, matchweek_complete: false });
  render(await LeagueTipsShareCardPage({ params: params() }));

  expect(screen.getByText("SwiftStriker123 is ahead of the AI so far this matchweek")).toBeInTheDocument();
  expect(screen.getByText(/Matchweek still in progress/)).toBeInTheDocument();
  expect(screen.queryByText("SwiftStriker123 beat the AI this matchweek")).not.toBeInTheDocument();
});

it("does not show the in-progress note once the matchweek is fully graded", async () => {
  mockShare.mockResolvedValue(share);
  render(await LeagueTipsShareCardPage({ params: params() }));

  expect(screen.queryByText(/Matchweek still in progress/)).not.toBeInTheDocument();
});

it("calls notFound() when there's no graded result for that handle/matchweek", async () => {
  mockShare.mockResolvedValue(null);
  await expect(LeagueTipsShareCardPage({ params: params() })).rejects.toThrow();
});

it("calls notFound() for a non-numeric matchweek without hitting the API", async () => {
  await expect(
    LeagueTipsShareCardPage({ params: params("epl", "abc") }),
  ).rejects.toThrow();
  expect(mockShare).not.toHaveBeenCalled();
});
