/** Bottom nav (PRD FR 4.5): My Bracket + Groups are first-class tabs, the
 *  leaderboard and the rest live under the More sheet, and every key route
 *  lights its tab — including detail pages like /match/[id] that don't share
 *  the tab's prefix. */
import { render, screen, fireEvent } from "@testing-library/react";
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

it("exposes the core loop as first-class tabs", () => {
  renderAt("/");
  for (const label of ["Home", "Matches", "My Bracket", "Groups"]) {
    expect(screen.getByRole("link", { name: new RegExp(label) })).toBeInTheDocument();
  }
  expect(screen.getByRole("button", { name: /More/ })).toBeInTheDocument();
});

it.each([
  ["/", "Home"],
  ["/team/3", "Home"], // team profiles open from the home hub
  ["/matches", "Matches"],
  ["/match/12", "Matches"], // singular detail route still lights Matches
  ["/my-bracket", "My Bracket"],
  ["/groups", "Groups"],
  ["/groups/2", "Groups"], // group detail still lights Groups
])("marks the right tab active on %s", (path, label) => {
  renderAt(path);
  expect(current()).toContain(label);
});

it("does not false-match prefix collisions (/my-bracket is not Brackets)", () => {
  renderAt("/my-bracket");
  expect(current()).toEqual(["My Bracket"]);
});

it("More opens a sheet with the secondary destinations", () => {
  renderAt("/");
  fireEvent.click(screen.getByRole("button", { name: /More/ }));
  for (const label of ["Leaderboard", "AI Bracket", "How it works", "Methodology"]) {
    expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
  }
});

it("highlights More when on a sheet destination", () => {
  renderAt("/leaderboard");
  const more = screen.getByRole("button", { name: /More/ });
  expect(more.className).toContain("text-win");
});

it("keeps the safe-area inset on the fixed bar", () => {
  renderAt("/");
  const nav = screen.getByRole("navigation", { name: "Primary" });
  // env() lives in the .safe-bottom/.safe-x utility classes (jsdom's CSSOM
  // can't represent env() inline styles).
  expect(nav.className).toContain("safe-bottom");
  expect(nav.className).toContain("safe-x");
});
