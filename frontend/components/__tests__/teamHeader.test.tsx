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

  // NRL adoption (Floodlight P3): the additive badge/showFavorite/meta/tiles
  // seams let the club page render the same banner without a fork.
  it("renders the NRL club variant: crest, no star, meta override, custom tiles", () => {
    const { container } = render(
      <TeamHeader
        team={makeTeam({
          name: "Warriors",
          country_code: null,
          confederation: null,
          fifa_rank: null,
          elo_rating: 1573,
          is_host: false,
        })}
        comp="nrl"
        backHref="/nrl/ladder"
        backLabel="Ladder"
        badge="club"
        showFavorite={false}
        meta="3rd on the ladder · 10–5–0 · 20 pts · Elo 1573"
        tiles={[
          { label: "Ladder", value: "3rd" },
          { label: "Record", value: "10–5–0" },
          { label: "Points", value: "20" },
          { label: "Elo", value: "1573" },
        ]}
      />,
    );

    // Name + the self-hosted Warriors crest stand in for a country flag.
    expect(screen.getByRole("heading", { name: "Warriors" })).toBeInTheDocument();
    expect(container.querySelector('[data-club-logo="Warriors"] img')).toHaveAttribute(
      "src",
      "/clubs/nrl/warriors.svg",
    );

    // showFavorite={false} drops the star (NRL clubs aren't country favorites).
    expect(screen.queryByRole("button", { name: /favorites/i })).toBeNull();

    // The meta override prints instead of the football group/rank/Elo join.
    expect(
      screen.getByText("3rd on the ladder · 10–5–0 · 20 pts · Elo 1573"),
    ).toBeInTheDocument();

    // The custom NRL tile row prints instead of the Elo/FIFA-rank pair. The
    // "Ladder" label collides with the back link's text node, so the tile row
    // is asserted through its unique labels + values.
    expect(screen.getByText("Record")).toBeInTheDocument();
    expect(screen.getByText("Points")).toBeInTheDocument();
    expect(screen.getByText("3rd")).toBeInTheDocument(); // Ladder tile value
    expect(screen.getByText("10–5–0")).toBeInTheDocument(); // Record tile value
    expect(screen.getByText("20")).toBeInTheDocument(); // Points tile value
    expect(screen.queryByText("FIFA rank")).toBeNull();

    // is_host=false -> no host badge; back link points at the ladder.
    expect(screen.queryByText("Tournament host")).toBeNull();
    expect(screen.getByRole("link", { name: "Ladder" })).toHaveAttribute(
      "href",
      "/nrl/ladder",
    );
  });

  it("prints no meta line when meta is null and no tiles when tiles is empty", () => {
    render(
      <TeamHeader
        team={makeTeam({ name: "Storm", elo_rating: 1900, fifa_rank: null })}
        comp="nrl"
        backHref="/nrl/ladder"
        backLabel="Ladder"
        badge="club"
        showFavorite={false}
        meta={null}
        tiles={[]}
      />,
    );

    // meta={null} suppresses the meta line; tiles={[]} suppresses the tile row.
    // The football Elo tile must NOT leak through the caller's empty override.
    expect(screen.getByRole("heading", { name: "Storm" })).toBeInTheDocument();
    expect(screen.queryByText("Elo")).toBeNull();
    expect(screen.queryByText("1900")).toBeNull();
  });
});
