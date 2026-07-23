/** Bottom nav (Daylight IA): exactly five first-class tabs — Home, Matches,
 *  Groups, Bracket, You — no overflow sheet. Every key route lights its tab,
 *  including detail pages like /match/[id] that don't share the tab's prefix. */
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
  for (const label of ["Home", "Matches", "Groups", "Bracket", "You"]) {
    expect(screen.getByRole("link", { name: new RegExp(label) })).toBeInTheDocument();
  }
  expect(screen.getAllByRole("link")).toHaveLength(5);
  // The old "More" overflow control is gone.
  expect(screen.queryByRole("button", { name: /More/ })).not.toBeInTheDocument();
});

it.each([
  ["/", "Home"],
  ["/team/3", "Home"], // team profiles open from the home hub
  ["/matches", "Matches"],
  ["/match/12", "Matches"], // singular detail route still lights Matches
  ["/groups", "Groups"],
  ["/groups/2", "Groups"], // group detail still lights Groups
  ["/brackets", "Bracket"],
  ["/leaderboard", "You"],
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
  ["/nrl/leaderboard", "You"],
])("marks exactly one NRL tab active on %s", (path, label) => {
  renderAt(path);
  // Regression: "/nrl" used to prefix-match every /nrl/* sub-page, so Home
  // stayed lit alongside the true tab — exactly one tab must be active.
  expect(current()).toEqual([label]);
});

it("uses the deep lime for the active tab on the light canvas", () => {
  renderAt("/");
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

it("hides the Bracket tab when the active tournament has no bracket", () => {
  mockPath = "/";
  render(
    <TournamentProvider tournament={LEAGUE}>
      <BottomNav />
    </TournamentProvider>,
  );
  expect(screen.queryByRole("link", { name: /Bracket/ })).not.toBeInTheDocument();
  expect(screen.getAllByRole("link")).toHaveLength(4);
});

it("still shows the Bracket tab with no provider (WC26 fallback)", () => {
  renderAt("/");
  expect(screen.getByRole("link", { name: /Bracket/ })).toBeInTheDocument();
});
