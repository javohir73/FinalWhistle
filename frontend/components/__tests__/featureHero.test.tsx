/** FeatureHero (Floodlight P2 slice p2-s5): the home hub's "tonight's feature"
 *  match -- a giant win % at display-hero scale, a thin W/D/L bar whose
 *  printed-% aria-label is the accessible source of truth for that number, two
 *  CTAs into the match page, and the league accent chip. `match={null}` degrades
 *  to an honest placeholder, never a fabricated number. */
import { render, screen } from "@testing-library/react";
import { FeatureHero } from "@/components/FeatureHero";
import type { MatchSummary } from "@/lib/types";

function makeMatch(overrides: Partial<MatchSummary> = {}): MatchSummary {
  return {
    match_id: 101,
    stage: "group",
    group: "Group C",
    kickoff_utc: new Date(Date.now() + 3 * 3_600_000).toISOString(),
    venue: "Estadio Test",
    venue_city: "Test City",
    venue_country: "Testland",
    is_neutral: true,
    status: "scheduled",
    score_home: null,
    score_away: null,
    minute: null,
    period: null,
    injury_time: null,
    penalty_home: null,
    penalty_away: null,
    teams: { home: "Brazil", away: "Uruguay" },
    predicted_winner: "Brazil",
    probabilities: { home_win: 0.62, draw: 0.24, away_win: 0.14 },
    predicted_score: { home: 2, away: 0, probability: 0.1 },
    confidence: "High",
    goal_events: [],
    ...overrides,
  };
}

describe("FeatureHero", () => {
  it("renders the giant win %, an accessible probability bar, both CTAs, and the comp chip", () => {
    render(<FeatureHero match={makeMatch()} comp="wc26" tz="UTC" />);

    // The decorative-scale giant number (max of home/draw/away = 62).
    expect(screen.getByText("62")).toBeInTheDocument();

    // The bar's printed-% aria-label is the accessible source of truth for it.
    const bar = screen.getByRole("img");
    expect(bar).toHaveAttribute("aria-label", expect.stringContaining("62%"));

    // Two equal CTAs, both into the full match page.
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    links.forEach((link) => expect(link).toHaveAttribute("href", "/match/101"));
    expect(screen.getByText("Make your pick")).toBeInTheDocument();
    expect(screen.getByText("Why 62%?")).toBeInTheDocument();

    // The league accent chip carries the competition's short label.
    expect(screen.getByText("WC26")).toBeInTheDocument();
  });

  it("renders an honest placeholder for a null match -- never a fabricated %", () => {
    render(<FeatureHero match={null} comp="wc26" />);

    expect(screen.getByText("No featured match right now")).toBeInTheDocument();
    // No probability bar, no CTAs, no invented percentage.
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText(/%/)).toBeNull();
  });
});
