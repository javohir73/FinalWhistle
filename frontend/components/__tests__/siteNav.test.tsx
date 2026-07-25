/** Top bar nav link row — mirrors BottomNav. Floodlight P5 folded the old
 *  Bracket/Tips slot into one always-on Play link, so the link row no longer
 *  flips with has_brackets (C6/D6, docs/LEAGUE-PIVOT-PLAN.md); Play is present
 *  in either format. */
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

it("shows platform-level destinations on the general home", () => {
  renderNav();
  expect(screen.getByRole("link", { name: "Football" })).toHaveAttribute(
    "href",
    "/football/epl",
  );
  expect(screen.getByRole("link", { name: "NRL" })).toHaveAttribute("href", "/nrl");
  expect(screen.getByRole("link", { name: "Play" })).toHaveAttribute("href", "/play");
  expect(screen.queryByRole("button", { name: "WC26" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Bracket" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Tips" })).not.toBeInTheDocument();
});

it("keeps shared Play navigation platform-level instead of implying WC26", () => {
  mockPath = "/play";
  renderNav();
  expect(screen.getByRole("link", { name: "Football" })).toHaveAttribute(
    "href",
    "/football/epl",
  );
  expect(screen.getByRole("link", { name: "Play" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(screen.queryByRole("button", { name: "WC26" })).not.toBeInTheDocument();
});

it("keeps the Play link (never Bracket/Tips) when the active tournament has no bracket", () => {
  mockPath = "/football/epl";
  renderNav(LEAGUE);
  expect(screen.getByRole("link", { name: "Play" })).toHaveAttribute("href", "/play");
  expect(screen.queryByRole("link", { name: "Bracket" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Tips" })).not.toBeInTheDocument();
  // Every other football link stays.
  expect(screen.getByRole("link", { name: "Home" })).toBeInTheDocument();
  // League navigation keeps its competition-specific terminology.
  expect(screen.getByRole("link", { name: "Fixtures" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Standings" })).toBeInTheDocument();
});

it("swaps the NRL fifth link for the shared Play hub -> /play (leaderboard alias dropped from nav, not the route)", () => {
  mockPath = "/nrl";
  renderNav();
  expect(screen.getByRole("link", { name: "Play" })).toHaveAttribute("href", "/play");
  expect(screen.queryByRole("link", { name: "You" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Tips" })).not.toBeInTheDocument();
});
