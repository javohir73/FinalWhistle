/** NRL tips share-card page tests — server component (SSR) output. Every
 *  case is 404-or-render: an unknown handle, an ungraded round, and a
 *  non-numeric route segment all resolve to notFound() (see the backend's
 *  tips_share, which 404s identically in every one of those cases). */
import { render, screen } from "@testing-library/react";
import NrlTipsShareCardPage from "./page";
import { getNrlTipsShareServer } from "@/lib/api";
import type { NrlTipsShareResponse } from "@/lib/types";

jest.mock("@/lib/api");
const mockShare = getNrlTipsShareServer as jest.MockedFunction<typeof getNrlTipsShareServer>;

const share: NrlTipsShareResponse = {
  handle_display: "SwiftHalfback123",
  season: 2026,
  round: 7,
  player_points: 7,
  player_of: 8,
  model_points: 6,
  model_of: 8,
  margin_note: "Featured-match margin tiebreak score: 3",
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

const params = (season = "2026", round = "7", handle = "SwiftHalfback123") =>
  Promise.resolve({ season, round, handle });

afterEach(() => jest.resetAllMocks());

it("renders the graded result, the CTA and the disclaimer", async () => {
  mockShare.mockResolvedValue(share);
  render(await NrlTipsShareCardPage({ params: params() }));

  expect(mockShare).toHaveBeenCalledWith(2026, 7, "SwiftHalfback123");
  expect(
    screen.getByText(/SwiftHalfback123 went 7\/8 — the AI went\s*6\/8/),
  ).toBeInTheDocument();
  expect(screen.getByText("SwiftHalfback123 beat the AI this round")).toBeInTheDocument();
  expect(screen.getByText("Featured-match margin tiebreak score: 3")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Play against the AI/i })).toHaveAttribute(
    "href",
    "/nrl/tips",
  );
  expect(screen.getByText(share.disclaimer)).toBeInTheDocument();
});

it("frames the AI winning honestly when the model out-scored the player", async () => {
  mockShare.mockResolvedValue({ ...share, player_points: 4, model_points: 6 });
  render(await NrlTipsShareCardPage({ params: params() }));

  expect(screen.getByText("The AI came out on top this round")).toBeInTheDocument();
});

it("frames a draw honestly when the two scores tie", async () => {
  mockShare.mockResolvedValue({ ...share, player_points: 6, model_points: 6 });
  render(await NrlTipsShareCardPage({ params: params() }));

  expect(screen.getByText("SwiftHalfback123 drew with the AI this round")).toBeInTheDocument();
});

it("omits the margin note when the player never entered a featured-match margin guess", async () => {
  mockShare.mockResolvedValue({ ...share, margin_note: null });
  render(await NrlTipsShareCardPage({ params: params() }));

  expect(screen.queryByText(/margin tiebreak/)).not.toBeInTheDocument();
});

it("calls notFound() when there's no graded result for that handle/round", async () => {
  mockShare.mockResolvedValue(null);
  await expect(NrlTipsShareCardPage({ params: params() })).rejects.toThrow();
});

it("calls notFound() for a non-numeric season/round without hitting the API", async () => {
  await expect(
    NrlTipsShareCardPage({ params: params("abc", "7") }),
  ).rejects.toThrow();
  await expect(
    NrlTipsShareCardPage({ params: params("2026", "abc") }),
  ).rejects.toThrow();
  expect(mockShare).not.toHaveBeenCalled();
});
