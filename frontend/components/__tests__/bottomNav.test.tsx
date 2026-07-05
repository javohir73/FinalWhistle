/** Bottom nav (Daylight IA): exactly five first-class tabs — Home, Matches,
 *  Groups, Bracket, You — no overflow sheet. Every key route lights its tab,
 *  including detail pages like /match/[id] that don't share the tab's prefix. */
import { render, screen } from "@testing-library/react";
import { BottomNav } from "@/components/BottomNav";

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
