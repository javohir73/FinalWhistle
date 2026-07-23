/** Top bar nav link row — mirrors BottomNav's Bracket-gating behavior for the
 *  league pivot (C6/D6, docs/LEAGUE-PIVOT-PLAN.md). */
import { render, screen } from "@testing-library/react";
import { SiteNav } from "@/components/SiteNav";
import { TournamentProvider } from "@/components/TournamentProvider";
import { AuthProvider } from "@/components/AuthProvider";
import * as session from "@/lib/session";
import type { ActiveTournament } from "@/lib/types";

// SiteNav renders AuthButton, which requires AuthProvider's context.
jest.mock("@/lib/session");
const mockGetMe = session.getMe as jest.MockedFunction<typeof session.getMe>;

let mockPath = "/";
jest.mock("next/navigation", () => ({
  usePathname: () => mockPath,
}));

beforeEach(() => {
  mockGetMe.mockResolvedValue(null); // signed out — irrelevant to nav gating
});
afterEach(() => {
  mockPath = "/";
  jest.resetAllMocks();
});

const LEAGUE: ActiveTournament = {
  id: 1,
  name: "Premier League 2026-27",
  year: 2026,
  format: "league",
  has_brackets: false,
};

const renderNav = (tournament?: ActiveTournament) => {
  const nav = <AuthProvider><SiteNav /></AuthProvider>;
  return render(tournament ? <TournamentProvider tournament={tournament}>{nav}</TournamentProvider> : nav);
};

it("shows the Bracket link with no provider (WC26 fallback)", () => {
  renderNav();
  expect(screen.getByRole("link", { name: "Bracket" })).toBeInTheDocument();
});

it("hides the Bracket link when the active tournament has no bracket", () => {
  renderNav(LEAGUE);
  expect(screen.queryByRole("link", { name: "Bracket" })).not.toBeInTheDocument();
  // Every other football link stays.
  expect(screen.getByRole("link", { name: "Home" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Matches" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Groups" })).toBeInTheDocument();
});

it("swaps the NRL fifth link for Tips -> /nrl/tips (leaderboard alias dropped from nav, not the route)", () => {
  mockPath = "/nrl";
  renderNav();
  expect(screen.getByRole("link", { name: "Tips" })).toHaveAttribute("href", "/nrl/tips");
  expect(screen.queryByRole("link", { name: "You" })).not.toBeInTheDocument();
});
