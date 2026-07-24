/** NRL home page tests — server component (SSR) output. The FeatureHero leads
 *  with the round's first still-to-play fixture; the remaining fixtures fall
 *  down the shared timeline spine (the feature is excluded, so it never shows
 *  twice); the State of Origin teaser links out when the series endpoint has
 *  data. IntelPanel does its own client fetch, so it's stubbed here to keep
 *  these assertions on the restyled fixture surfaces. */
import { render, screen } from "@testing-library/react";
import NrlHomePage from "./page";
import { getNrlLadderServer, getNrlMatchesServer, getOriginSeriesServer } from "@/lib/api";
import type { NrlMatchesResponse, NrlPrediction, OriginSeriesResponse } from "@/lib/types";

jest.mock("@/lib/api");
// IntelPanel fetches market intel in a client effect; irrelevant here.
jest.mock("@/components/IntelPanel", () => ({ IntelPanel: () => null }));

const mockMatches = getNrlMatchesServer as jest.MockedFunction<typeof getNrlMatchesServer>;
const mockLadder = getNrlLadderServer as jest.MockedFunction<typeof getNrlLadderServer>;
const mockOrigin = getOriginSeriesServer as jest.MockedFunction<typeof getOriginSeriesServer>;

const pred = (p_home: number, p_away: number, margin: number): NrlPrediction => ({
  p_home,
  p_draw: Number((1 - p_home - p_away).toFixed(2)),
  p_away,
  expected_margin: margin,
  model_version: "nrl-v0.1",
  created_at: null,
  is_shadow: false,
});

const fixtures: NrlMatchesResponse = {
  season: 2026,
  disclaimer: "For analytics and entertainment only. Not betting advice.",
  rounds: [
    {
      round: 20,
      matches: [
        {
          id: 1, match_no: 1, kickoff_utc: "2026-07-18T06:00:00Z", venue: "Suncorp",
          home: "Broncos", away: "Storm", home_team_id: 1, away_team_id: 2,
          score_home: null, score_away: null, status: "scheduled", prediction: pred(0.7, 0.27, 8.5),
        },
        {
          id: 2, match_no: 2, kickoff_utc: "2026-07-19T06:00:00Z", venue: "Accor Stadium",
          home: "Panthers", away: "Eels", home_team_id: 3, away_team_id: 4,
          score_home: null, score_away: null, status: "scheduled", prediction: pred(0.55, 0.41, 3.0),
        },
      ],
    },
  ],
};

const origin: OriginSeriesResponse = {
  season: 2026,
  seasons: [2026],
  games: [],
  series: { blues_wins: 2, maroons_wins: 1, drawn_games: 0, winner: "NSW Blues", odds: null },
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

beforeEach(() => {
  mockLadder.mockResolvedValue(null); // mini ladder migrates in p3-s5; not under test here
  mockOrigin.mockResolvedValue(null);
});
afterEach(() => jest.resetAllMocks());

it("leads with the FeatureHero for the round's first scheduled fixture", async () => {
  mockMatches.mockResolvedValue(fixtures);
  render(await NrlHomePage());

  // Featured = first scheduled match of the current round (Broncos v Storm).
  // getByText throwing on duplicates also proves the feature is NOT repeated in
  // the timeline below.
  expect(screen.getByText("Broncos")).toBeInTheDocument();
  // Its display-hero win % (max of 70/03/27).
  expect(screen.getByText("70")).toBeInTheDocument();
});

it("lists the round's remaining fixtures on the shared spine, feature excluded", async () => {
  mockMatches.mockResolvedValue(fixtures);
  render(await NrlHomePage());

  // The spine carries the round as its heading and the non-featured fixture.
  expect(screen.getByText("Round 20")).toBeInTheDocument();
  expect(screen.getByText(/Panthers/)).toBeInTheDocument();
  // That fixture links to its (season, round, match_no) detail page.
  expect(screen.getByText(/Panthers/).closest("a")).toHaveAttribute(
    "href",
    "/nrl/match/2026/20/2",
  );
});

it("still renders the State of Origin teaser when the series endpoint has data", async () => {
  mockMatches.mockResolvedValue(fixtures);
  mockOrigin.mockResolvedValue(origin);
  render(await NrlHomePage());

  const originLink = screen.getByRole("link", { name: /State of Origin/i });
  expect(originLink).toHaveAttribute("href", "/nrl/origin");
});
