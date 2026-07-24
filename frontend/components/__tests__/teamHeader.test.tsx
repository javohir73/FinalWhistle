/** TeamHeader (Floodlight P2 slice p2-s6): the full-bleed crest banner atop a
 *  team page -- a back link into the standings, crest + Bricolage name +
 *  FavoriteStar, a group/rank/Elo meta line, the host badge, and the ML-outlook
 *  stat tiles (Reach KO / Reach final / Win title). */
import { render, screen } from "@testing-library/react";
import { TeamHeader } from "@/components/TeamHeader";
import { COMPETITIONS } from "@/lib/sports";
import type { Team, TournamentOdds } from "@/lib/types";

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

function makeOdds(overrides: Partial<TournamentOdds> = {}): TournamentOdds {
  return {
    team_id: 10,
    team: "Brazil",
    make_knockout: 0.9,
    reach_r16: 0.7,
    reach_qf: 0.5,
    reach_sf: 0.3,
    reach_final: 0.2,
    win_title: 0.12,
    ...overrides,
  };
}

describe("TeamHeader", () => {
  it("renders the name, meta line, three ML-outlook tiles, the favorite star, and the standings back link", () => {
    render(
      <TeamHeader
        team={makeTeam()}
        groupName="Group C"
        comp="wc26"
        backHref="/groups"
        backLabel={COMPETITIONS.wc26.terms.standings}
        teamOdds={makeOdds()}
      />,
    );

    // Team name.
    expect(screen.getByRole("heading", { name: "Brazil" })).toBeInTheDocument();

    // Meta line: group · FIFA #rank · Elo.
    expect(screen.getByText("Group C · FIFA #5 · Elo 1985")).toBeInTheDocument();

    // Three stat tiles, each a label + percentage read from the odds.
    expect(screen.getByText("Reach KO")).toBeInTheDocument();
    expect(screen.getByText("Reach final")).toBeInTheDocument();
    expect(screen.getByText("Win title")).toBeInTheDocument();
    expect(screen.getByText("90%")).toBeInTheDocument();
    expect(screen.getByText("20%")).toBeInTheDocument();
    expect(screen.getByText("12%")).toBeInTheDocument();

    // FavoriteStar toggle.
    expect(
      screen.getByRole("button", { name: /add brazil to favorites/i }),
    ).toBeInTheDocument();

    // Back link carries the competition's standings term and points at backHref.
    const back = screen.getByRole("link", { name: COMPETITIONS.wc26.terms.standings });
    expect(back).toHaveAttribute("href", "/groups");
  });

  it("falls back to Elo / FIFA-rank tiles when there are no tournament odds", () => {
    render(
      <TeamHeader
        team={makeTeam()}
        groupName="Group C"
        comp="wc26"
        backHref="/groups"
        backLabel={COMPETITIONS.wc26.terms.standings}
        teamOdds={null}
      />,
    );

    expect(screen.getByText("Elo")).toBeInTheDocument();
    expect(screen.getByText("1985")).toBeInTheDocument();
    expect(screen.getByText("FIFA rank")).toBeInTheDocument();
    expect(screen.getByText("#5")).toBeInTheDocument();
    // No ML-outlook tiles without odds.
    expect(screen.queryByText("Reach KO")).toBeNull();
  });

  it("renders the host badge for a tournament host", () => {
    render(
      <TeamHeader
        team={makeTeam({ is_host: true })}
        groupName="Group A"
        comp="wc26"
        backHref="/groups"
        backLabel={COMPETITIONS.wc26.terms.standings}
        teamOdds={makeOdds()}
      />,
    );

    expect(screen.getByText("Tournament host")).toBeInTheDocument();
  });
});
