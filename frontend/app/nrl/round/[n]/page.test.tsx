/** NRL round page tests — server component (SSR) output. */
import { render, screen } from "@testing-library/react";
import NrlRoundPage from "./page";
import { getNrlMatchesServer } from "@/lib/api";
import type { NrlMatchesResponse } from "@/lib/types";

jest.mock("@/lib/api");
const mockMatches = getNrlMatchesServer as jest.MockedFunction<typeof getNrlMatchesServer>;

const fixtures: NrlMatchesResponse = {
  season: 2026,
  rounds: [
    { round: 18, matches: [] },
    {
      round: 19,
      matches: [{
        id: 42, match_no: 3, kickoff_utc: "2026-07-11T09:35:00+00:00",
        venue: "Leichhardt Oval", home: "Wests Tigers", away: "Warriors",
        home_team_id: 17, away_team_id: 16, score_home: null, score_away: null,
        status: "scheduled", prediction: null,
      }],
    },
    { round: 20, matches: [] },
  ],
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

const params = (n = "19") => Promise.resolve({ n });

afterEach(() => jest.resetAllMocks());

it("renders the round heading and its fixtures", async () => {
  mockMatches.mockResolvedValue(fixtures);
  render(await NrlRoundPage({ params: params() }));

  expect(screen.getByRole("heading", { name: "Round 19" })).toBeInTheDocument();
  expect(screen.getByText("Wests Tigers")).toBeInTheDocument();
});

it("links to the previous and next rounds", async () => {
  mockMatches.mockResolvedValue(fixtures);
  render(await NrlRoundPage({ params: params() }));

  const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
  expect(links).toContain("/nrl/round/18");
  expect(links).toContain("/nrl/round/20");
});

it("hides the previous link on the first round", async () => {
  mockMatches.mockResolvedValue(fixtures);
  render(await NrlRoundPage({ params: params("18") }));

  const links = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
  expect(links).not.toContain("/nrl/round/17");
  expect(links).toContain("/nrl/round/19");
});

it("calls notFound() for a round the API doesn't have", async () => {
  mockMatches.mockResolvedValue(fixtures);
  await expect(NrlRoundPage({ params: params("99") })).rejects.toThrow();
});

it("calls notFound() for a non-numeric round without hitting the API", async () => {
  await expect(NrlRoundPage({ params: params("abc") })).rejects.toThrow();
  expect(mockMatches).not.toHaveBeenCalled();
});
