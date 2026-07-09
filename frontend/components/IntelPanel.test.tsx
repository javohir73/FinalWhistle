import { render, screen } from "@testing-library/react";
import { IntelPanel, minutesAgo, storylineLabel } from "@/components/IntelPanel";
import type { IntelResponse } from "@/lib/types";

jest.mock("@/lib/api", () => ({
  getIntel: jest.fn(),
  getMovers: jest.fn(),
}));
const { getIntel, getMovers } = jest.requireMock("@/lib/api");

const INTEL: IntelResponse = {
  sport: "football",
  has_data: true,
  updated_at: new Date(Date.now() - 23 * 60 * 1000).toISOString(),
  matches: [
    {
      match_id: 1,
      kickoff_utc: new Date(Date.now() + 12 * 3600 * 1000).toISOString(),
      home: { id: 1, name: "France" },
      away: { id: 2, name: "Morocco" },
      model: { home: 0.55, draw: 0.27, away: 0.18 },
      market: [
        { source: "polymarket", home: 0.62, draw: 0.24, away: 0.14,
          fetched_at: new Date().toISOString() },
      ],
      disagreement: 0.07,
    },
  ],
  storylines: [
    { market_type: "title_winner", source: "polymarket", outcome: "win",
      match_id: null, team: { id: 3, name: "Argentina" },
      prob_from: 0.24, prob_to: 0.31, window_hours: 24 },
  ],
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

describe("IntelPanel", () => {
  beforeEach(() => jest.resetAllMocks());

  it("renders model vs market and storylines when has_data", async () => {
    getIntel.mockResolvedValue(INTEL);
    render(<IntelPanel sport="football" />);
    expect(await screen.findByText("Market intel")).toBeInTheDocument();
    // "Market intel" is the static heading (present during loading too), so it
    // resolves before the fetch does; wait on real match content instead —
    // "France vs Morocco" only renders once getIntel's promise has settled.
    expect(await screen.findByText(/France vs Morocco/)).toBeInTheDocument();
    expect(screen.getByText(/Market 62%/)).toBeInTheDocument();
    expect(screen.getByText(/Model 55%/)).toBeInTheDocument();
    expect(screen.getByText(/Argentina to win the Cup/)).toBeInTheDocument();
    expect(screen.getByText(/24% → 31%/)).toBeInTheDocument();
    expect(getMovers).not.toHaveBeenCalled();
  });

  it("falls back to MoversPanel when has_data is false", async () => {
    getIntel.mockResolvedValue({ ...INTEL, has_data: false, matches: [], storylines: [] });
    getMovers.mockResolvedValue({ sport: "football", as_of: null, movers: [
      { entity_id: 1, name: "France", market: "win_title", prob: 0.31,
        delta: 0.05, series: [0.26, 0.31] },
    ], disclaimer: "" });
    render(<IntelPanel sport="football" />);
    expect(await screen.findByText("Today's movers")).toBeInTheDocument();
  });

  it("falls back to MoversPanel when the intel fetch fails", async () => {
    getIntel.mockRejectedValue(new Error("boom"));
    getMovers.mockResolvedValue({ sport: "football", as_of: null, movers: [
      { entity_id: 1, name: "France", market: "win_title", prob: 0.31,
        delta: null, series: [0.31] },
    ], disclaimer: "" });
    render(<IntelPanel sport="football" />);
    expect(await screen.findByText("Today's movers")).toBeInTheDocument();
  });
});

describe("helpers", () => {
  it("storylineLabel wording per market and sport", () => {
    expect(storylineLabel(INTEL.storylines[0], "football"))
      .toBe("Argentina to win the Cup");
    expect(storylineLabel({ ...INTEL.storylines[0], market_type: "match_winner",
                            team: { id: 1, name: "France" } }, "football"))
      .toBe("France to win the match");
    expect(storylineLabel(INTEL.storylines[0], "nrl"))
      .toBe("Argentina to win the Premiership");
  });

  it("minutesAgo formats", () => {
    const now = new Date("2026-07-10T15:00:00Z");
    expect(minutesAgo("2026-07-10T14:37:00Z", now)).toBe("23m ago");
    expect(minutesAgo("2026-07-10T12:00:00Z", now)).toBe("3h ago");
  });
});
