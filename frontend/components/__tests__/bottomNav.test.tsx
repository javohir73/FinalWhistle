/** Bottom nav (Daylight IA): exactly five first-class tabs — Home, Fixtures,
 *  Groups, Bracket, You — no overflow sheet. Every key route lights its tab,
 *  including detail pages like /football/wc26/match/[id] that don't share the
 *  tab's prefix. Paths below use the Floodlight P1 /football/wc26/... scheme
 *  (lib/sports.ts's COMPETITIONS.wc26) since BottomNav now derives its tabs
 *  from the registry, not the legacy un-namespaced routes those hrefs used to
 *  point at (still 301-redirected in next.config.mjs, but no longer what the
 *  nav itself renders). */
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

it("exposes exactly the five Daylight tabs", () => {
  renderAt("/");
  for (const label of ["Home", "Fixtures", "Groups", "Bracket", "You"]) {
    expect(screen.getByRole("link", { name: new RegExp(label) })).toBeInTheDocument();
  }
  expect(screen.getAllByRole("link")).toHaveLength(5);
  // The old "More" overflow control is gone.
  expect(screen.queryByRole("button", { name: /More/ })).not.toBeInTheDocument();
});

it.each([
  ["/football/wc26", "Home"],
  ["/football/wc26/team/3", "Home"], // team profiles open from the home hub
  ["/football/wc26/fixtures", "Fixtures"],
  ["/football/wc26/match/12", "Fixtures"], // singular detail route still lights Fixtures
  ["/football/wc26/groups", "Groups"],
  ["/football/wc26/groups/2", "Groups"], // group detail still lights Groups
  ["/football/wc26/bracket", "Bracket"],
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
  ["/nrl/tips", "Tips"],
])("marks exactly one NRL tab active on %s", (path, label) => {
  renderAt(path);
  // Regression: "/nrl" used to prefix-match every /nrl/* sub-page, so Home
  // stayed lit alongside the true tab — exactly one tab must be active.
  expect(current()).toEqual([label]);
});

it("swaps the NRL fifth tab for Tips -> /nrl/tips (leaderboard alias dropped from the tab bar, not the route)", () => {
  renderAt("/nrl");
  expect(screen.getByRole("link", { name: /Tips/ })).toHaveAttribute("href", "/nrl/tips");
  expect(screen.queryByRole("link", { name: "You" })).not.toBeInTheDocument();
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

// League pivot (C6/D6, docs/LEAGUE-PIVOT-PLAN.md): a tournament with no
// knockout stage hides the Bracket tab everywhere it appears.
const LEAGUE: ActiveTournament = {
  id: 1,
  name: "Premier League 2026-27",
  year: 2026,
  format: "league",
  has_brackets: false,
};

it("hides the Bracket tab and shows Tips instead when the active tournament has no bracket", () => {
  mockPath = "/";
  render(
    <TournamentProvider tournament={LEAGUE}>
      <BottomNav />
    </TournamentProvider>,
  );
  expect(screen.queryByRole("link", { name: /Bracket/ })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Tips/ })).toHaveAttribute("href", "/tips");
  // Tips fills the slot Bracket vacates -- still exactly five, never six.
  expect(screen.getAllByRole("link")).toHaveLength(5);
});

it("still shows the Bracket tab (and hides Tips) with no provider (WC26 fallback)", () => {
  renderAt("/");
  expect(screen.getByRole("link", { name: /Bracket/ })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Tips/ })).not.toBeInTheDocument();
  expect(screen.getAllByRole("link")).toHaveLength(5);
});
