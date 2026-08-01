import { render } from "@testing-library/react";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { TeamBadge } from "@/components/TeamBadge";

const ACTIVE_LEAGUE_CLUBS = [
  ["Barcelona", "laliga"],
  ["Atletico Madrid", "laliga"],
  ["Athletic Club", "laliga"],
  ["Valencia", "laliga"],
  ["Villarreal", "laliga"],
  ["Malaga", "laliga"],
  ["Sevilla", "laliga"],
  ["Celta Vigo", "laliga"],
  ["Levante", "laliga"],
  ["Espanyol", "laliga"],
  ["Real Madrid", "laliga"],
  ["Alaves", "laliga"],
  ["Real Betis", "laliga"],
  ["Deportivo La Coruna", "laliga"],
  ["Getafe", "laliga"],
  ["Real Sociedad", "laliga"],
  ["Osasuna", "laliga"],
  ["Rayo Vallecano", "laliga"],
  ["Elche", "laliga"],
  ["Racing Santander", "laliga"],
  ["Bayern München", "bundesliga"],
  ["SC Freiburg", "bundesliga"],
  ["Werder Bremen", "bundesliga"],
  ["Borussia Mönchengladbach", "bundesliga"],
  ["FSV Mainz 05", "bundesliga"],
  ["Borussia Dortmund", "bundesliga"],
  ["1899 Hoffenheim", "bundesliga"],
  ["Bayer Leverkusen", "bundesliga"],
  ["Eintracht Frankfurt", "bundesliga"],
  ["FC Augsburg", "bundesliga"],
  ["VfB Stuttgart", "bundesliga"],
  ["RB Leipzig", "bundesliga"],
  ["FC Schalke 04", "bundesliga"],
  ["Hamburger SV", "bundesliga"],
  ["Union Berlin", "bundesliga"],
  ["SC Paderborn 07", "bundesliga"],
  ["1. FC Köln", "bundesliga"],
  ["SV Elversberg", "bundesliga"],
] as const;

const VERIFIED_UCL_CLUBS = [
  "Lyon",
  "Heart Of Midlothian",
  "Vikingur Reykjavik",
  "Bodo/Glimt",
  "Gornik Zabrze",
  "Lech Poznan",
  "The New Saints",
  "Aarhus",
  "NEC Nijmegen",
  "Olympiakos Piraeus",
  "Hapoel Beer Sheva",
  "Vardar Skopje",
  "FK Crvena Zvezda",
  "Fenerbahçe",
  "Dinamo Zagreb",
  "Sparta Praha",
  "Universitatea Craiova",
  "Sturm Graz",
  "Levski Sofia",
  "Shamrock Rovers",
  "Slovan Bratislava",
  "Kairat Almaty",
  "Lincoln Red Imps FC",
  "Sutjeska",
  "Flora Tallinn",
  "KI Klaksvik",
  "FC Thun",
  "KuPS",
  "Union St. Gilloise",
  "Mjallby AIF",
  "Tre Fiori",
  "Petrocub",
  "Gyori ETO FC",
  "Egnatia Rrogozhinë",
  "Inter Club d'Escaldes",
  "Borac Banja Luka",
  "Omonia Nicosia",
  "Saburtalo",
  "Ararat-Armenia",
  "Kauno Žalgiris",
  "Celje",
  "Floriana",
  "Larne",
  "ML Vitebsk",
  "Riga",
  "Sabah FA",
  "Drita",
  "Atert Bissen",
  "Club Brugge KV",
  "Como",
  "Feyenoord",
  "Galatasaray",
  "Inter",
  "Lens",
  "Lille",
  "Napoli",
  "Paris Saint Germain",
  "FC Porto",
  "PSV Eindhoven",
  "AS Roma",
  "Shakhtar Donetsk",
  "Slavia Praha",
  "Sporting CP",
] as const;

describe("TeamBadge", () => {
  it("keeps national teams on their self-hosted flags", () => {
    const { container } = render(<TeamBadge team="Brazil" size={32} />);
    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "/flags/br.png"
    );
    expect(container.querySelector("[data-club-logo]")).toBeNull();
  });

  it("uses a self-hosted crest for a known domestic club", () => {
    const { container } = render(<TeamBadge team="Arsenal" size={32} />);
    const shell = container.querySelector('[data-club-logo="Arsenal"]');
    expect(shell).not.toHaveClass("bg-white/95", "ring-1");
    expect(shell?.querySelector("img")).toHaveAttribute(
      "src",
      "/clubs/epl/arsenal.png"
    );
    expect(shell?.querySelector("img")).toHaveClass("object-contain");
    expect(shell?.querySelector("img")).toHaveStyle({
      width: "27.52px",
      height: "27.52px",
    });
  });

  it("resolves common short club names to the same local crest", () => {
    const { container } = render(<TeamBadge team="Man City" size={32} />);
    expect(
      container.querySelector('[data-club-logo="Man City"] img')
    ).toHaveAttribute("src", "/clubs/epl/manchester-city.png");
  });

  it.each(ACTIVE_LEAGUE_CLUBS)(
    "uses a self-hosted crest for %s",
    (team, league) => {
      const { container } = render(<TeamBadge team={team} size={32} />);
      expect(
        container.querySelector(`[data-club-logo="${team}"] img`)
      ).toHaveAttribute(
        "src",
        expect.stringMatching(new RegExp(`^/clubs/${league}/.+\\.png$`))
      );
    }
  );

  it.each(VERIFIED_UCL_CLUBS)(
    "uses an existing self-hosted UCL crest for %s",
    (team) => {
      const { container } = render(<TeamBadge team={team} size={32} />);
      const image = container.querySelector(`[data-club-logo="${team}"] img`);
      expect(image).toHaveAttribute(
        "src",
        expect.stringMatching(/^\/clubs\/ucl\/\d+\.png$/)
      );
      const src = image?.getAttribute("src");
      expect(src && existsSync(join(process.cwd(), "public", src))).toBe(true);
    }
  );

  it.each([
    ["Atlético Madrid", "/clubs/laliga/atletico-madrid.png"],
    ["Bayern Munich", "/clubs/bundesliga/bayern-munchen.png"],
    ["Schalke 04", "/clubs/bundesliga/fc-schalke-04.png"],
  ])("resolves the common alias %s", (team, expectedSrc) => {
    const { container } = render(<TeamBadge team={team} size={32} />);
    expect(
      container.querySelector(`[data-club-logo="${team}"] img`)
    ).toHaveAttribute("src", expectedSrc);
  });
});
