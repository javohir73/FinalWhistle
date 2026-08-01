/** Bottom nav (Daylight IA): exactly five first-class tabs — Home, Fixtures,
 *  Play, Standings, You — no overflow sheet. Floodlight P5 folded the old
 *  mutually-exclusive Bracket/Tips slot into the always-on Play tab. Every key
 *  route lights its tab, including detail pages like /football/wc26/match/[id]
 *  that don't share the tab's prefix. Paths below use the Floodlight P1
 *  /football/wc26/... scheme (lib/sports.ts's COMPETITIONS.wc26) since BottomNav
 *  now derives its tabs from the registry, not the legacy un-namespaced routes
 *  those hrefs used to point at (still 301-redirected in next.config.mjs, but no
 *  longer what the nav itself renders). */
import { render, screen } from "@testing-library/react";
import { BottomNav } from "@/components/BottomNav";
import { TournamentProvider } from "@/components/TournamentProvider";
import type { ActiveTournament } from "@/lib/types";

let mockPath = "/";
jest.mock("next/navigation", () => ({
  usePathname: () => mockPath,
}));

const renderAt = (path: string) => {
  mockPath = path;
  return render(<BottomNav />);
};

const current = () =>
  screen
    .getAllByRole("link")
    .filter((a) => a.getAttribute("aria-current") === "page")
    .map((a) => a.textContent);

afterEach(() => {
  mockPath = "/";
});

it("exposes exactly five platform destinations on the general home", () => {
  renderAt("/");
  for (const label of ["Home", "Football", "NRL", "Play", "You"]) {
    expect(screen.getByRole("link", { name: new RegExp(label) })).toBeInTheDocument();
  }
  expect(screen.getAllByRole("link")).toHaveLength(5);
  // Floodlight P5: the old Bracket/Tips tabs folded into Play.
  expect(screen.queryByRole("link", { name: /Bracket/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /^Tips/ })).not.toBeInTheDocument();
  // The old "More" overflow control is gone.
  expect(screen.queryByRole("button", { name: /More/ })).not.toBeInTheDocument();
});

it("keeps shared routes in the platform navigation", () => {
  renderAt("/play");
  expect(screen.getByRole("link", { name: /Football/ })).toHaveAttribute(
    "href",
    "/football/epl",
  );
  expect(current()).toEqual(["Play"]);
});

it.each([
  ["/football/wc26", "Home"],
  ["/football/wc26/team/3", "Home"], // team profiles open from the home hub
  ["/football/wc26/fixtures", "Fixtures"],
  ["/football/wc26/match/12", "Fixtures"], // singular detail route still lights Fixtures
  ["/football/wc26/groups", "Standings"],
  ["/football/wc26/groups/2", "Standings"], // group detail still lights Standings
  ["/play", "Play"], // the hub itself lights Play
  ["/tips", "Play"], // Play subsumes the league-tips route (activePrefix)
  ["/football/wc26/bracket", "Play"], // ...and the projected-bracket route the user actually lands on (legacy /brackets 301s here)
  ["/football/ucl", "Home"],
  ["/football/ucl/fixtures", "Fixtures"],
  ["/football/ucl/match/31", "Fixtures"],
  ["/football/ucl/standings", "League phase"],
  ["/leaderboard", "You"], // cross-cutting, not namespaced in P1
  ["/about", "You"], // relocated info pages light the You hub
  ["/methodology", "You"],
  ["/record", "You"], // the live track record nests under the You hub
])("marks the right tab active on %s", (path, label) => {
  renderAt(path);
  expect(current()).toContain(label);
});

it.each([
  ["/nrl", "Home"],
  ["/nrl/matches", "Matches"],
  ["/nrl/ladder", "Ladder"],
  ["/nrl/record", "Record"],
  ["/nrl/tips", "Play"], // Play subsumes the NRL tips route (activePrefix)
])("marks exactly one NRL tab active on %s", (path, label) => {
  renderAt(path);
  // Regression: "/nrl" used to prefix-match every /nrl/* sub-page, so Home
  // stayed lit alongside the true tab — exactly one tab must be active.
  expect(current()).toEqual([label]);
});

it("swaps the NRL fifth tab for the shared Play hub (leaderboard alias dropped from the tab bar, not the route)", () => {
  renderAt("/nrl");
  expect(screen.getByRole("link", { name: /Play/ })).toHaveAttribute("href", "/play");
  expect(screen.queryByRole("link", { name: "You" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Tips/ })).not.toBeInTheDocument();
  expect(screen.getAllByRole("link")).toHaveLength(5);
});

it("uses the deep lime for the active tab on the light canvas", () => {
  renderAt("/football/wc26");
  const home = screen.getByRole("link", { name: /Home/ });
  expect(home.className).toContain("text-lime-deep");
});

it("keeps the safe-area inset on the fixed bar", () => {
  renderAt("/");
  const nav = screen.getByRole("navigation", { name: "Primary" });
  // env() lives in the .safe-bottom/.safe-x utility classes (jsdom's CSSOM
  // can't represent env() inline styles).
  expect(nav.className).toContain("safe-bottom");
  expect(nav.className).toContain("safe-x");
});

// Floodlight P5: Play is always-on -- unlike the old Bracket/Tips pair it no
// longer flips with has_brackets (C6/D6, docs/LEAGUE-PIVOT-PLAN.md). The tab
// bar stays five wide with Play in the fifth slot, in either format.
const LEAGUE: ActiveTournament = {
  id: 1,
  name: "Premier League 2026-27",
  year: 2026,
  format: "league",
  has_brackets: false,
};

it("keeps the Play tab (never a separate Bracket/Tips) when the tournament has no bracket", () => {
  mockPath = "/football/epl";
  render(
    <TournamentProvider tournament={LEAGUE}>
      <BottomNav />
    </TournamentProvider>,
  );
  expect(screen.getByRole("link", { name: /Play/ })).toHaveAttribute("href", "/play");
  expect(screen.queryByRole("link", { name: /Bracket/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Tips/ })).not.toBeInTheDocument();
  // Still exactly five, never six.
  expect(screen.getAllByRole("link")).toHaveLength(5);
});

it("keeps the Play tab with no provider on a World Cup route", () => {
  renderAt("/football/wc26");
  expect(screen.getByRole("link", { name: /Play/ })).toHaveAttribute("href", "/play");
  expect(screen.queryByRole("link", { name: /Bracket/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Tips/ })).not.toBeInTheDocument();
  expect(screen.getAllByRole("link")).toHaveLength(5);
});
