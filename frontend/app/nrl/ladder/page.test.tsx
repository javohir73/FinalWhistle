/** /nrl/ladder -- server component (SSR) output. */
import { render, screen } from "@testing-library/react";
import NrlLadderPage from "./page";
import { getNrlLadderServer, getNrlProjectionsServer } from "@/lib/api";
import type { LadderResponse } from "@/lib/types";

jest.mock("@/lib/api");
const mockLadder = getNrlLadderServer as jest.MockedFunction<typeof getNrlLadderServer>;
const mockProjections = getNrlProjectionsServer as jest.MockedFunction<typeof getNrlProjectionsServer>;

afterEach(() => jest.resetAllMocks());

const ladder: LadderResponse = {
  season: 2026,
  rows: [{ rank: 1, team_id: 1, name: "Storm", played: 20, wins: 16, draws: 0, losses: 4, points: 32, diff: 120 }],
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

it("renders the ladder and links through to the run-home predictor (Slice 3)", async () => {
  mockLadder.mockResolvedValue(ladder);
  mockProjections.mockResolvedValue(null);

  render(await NrlLadderPage());

  expect(screen.getByRole("heading", { name: /NRL ladder/i })).toBeInTheDocument();
  expect(screen.getByText("Storm")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Predict your run home →" })).toHaveAttribute(
    "href",
    "/nrl/run-home",
  );
});

it("calls notFound() when the ladder can't load", async () => {
  mockLadder.mockResolvedValue(null);
  mockProjections.mockResolvedValue(null);
  await expect(NrlLadderPage()).rejects.toThrow();
});
