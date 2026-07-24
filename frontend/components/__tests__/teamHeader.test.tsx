/** TeamHeader (Floodlight P2 slice p2-s6): the full-bleed crest banner atop a
 *  team page -- a back link into the standings, crest + Bricolage name +
 *  FavoriteStar, a group/rank/Elo meta line, the host badge, and the raw
 *  Elo / FIFA-rank stat tiles. The tournament-odds breakdown is the ML-outlook
 *  card's job, not the header's, so the header never reprints those odds. */
import { render, screen } from "@testing-library/react";
import { TeamHeader } from "@/components/TeamHeader";
import { COMPETITIONS } from "@/lib/sports";
import type { Team } from "@/lib/types";

function makeTeam(overrides: Partial<Team> = {}): Team {
  return {
    id: 10,
    name: "Brazil",
    country_code: "BR",
    confederation: "CONMEBOL",
    fifa_rank: 5,
    elo_rating: 1985,
    is_host: false,
    ...overrides,
  };
}

describe("TeamHeader", () => {
  it("renders the name, meta line, Elo / FIFA-rank tiles, the favorite star, and the standings back link", () => {
    render(
      <TeamHeader
        team={makeTeam()}
        groupName="Group C"
        comp="wc26"
        backHref="/groups"
        backLabel={COMPETITIONS.wc26.terms.standings}
      />,
    );

    // Team name.
    expect(screen.getByRole("heading", { name: "Brazil" })).toBeInTheDocument();

    // Meta line: group · FIFA #rank · Elo.
    expect(screen.getByText("Group C · FIFA #5 · Elo 1985")).toBeInTheDocument();

    // Raw-rating stat tiles -- distinct from the ML-outlook odds card below, so
    // no tournament odds are reprinted here.
    expect(screen.getByText("Elo")).toBeInTheDocument();
    expect(screen.getByText("1985")).toBeInTheDocument();
    expect(screen.getByText("FIFA rank")).toBeInTheDocument();
    expect(screen.getByText("#5")).toBeInTheDocument();
    expect(screen.queryByText("Reach KO")).toBeNull();
    expect(screen.queryByText("Win title")).toBeNull();

    // FavoriteStar toggle.
    expect(
      screen.getByRole("button", { name: /add brazil to favorites/i }),
    ).toBeInTheDocument();

    // Back link carries the competition's standings term and points at backHref.
    const back = screen.getByRole("link", { name: COMPETITIONS.wc26.terms.standings });
    expect(back).toHaveAttribute("href", "/groups");
  });

  it("drops a missing rating rather than faking it", () => {
    render(
      <TeamHeader
        team={makeTeam({ elo_rating: null })}
        groupName="Group C"
        comp="wc26"
        backHref="/groups"
        backLabel={COMPETITIONS.wc26.terms.standings}
      />,
    );

    // Only the FIFA-rank tile survives; the Elo tile drops out honestly.
    expect(screen.getByText("FIFA rank")).toBeInTheDocument();
    expect(screen.getByText("#5")).toBeInTheDocument();
    expect(screen.queryByText("Elo")).toBeNull();
  });

  it("renders the host badge for a tournament host", () => {
    render(
      <TeamHeader
        team={makeTeam({ is_host: true })}
        groupName="Group A"
        comp="wc26"
        backHref="/groups"
        backLabel={COMPETITIONS.wc26.terms.standings}
      />,
    );

    expect(screen.getByText("Tournament host")).toBeInTheDocument();
  });
});
