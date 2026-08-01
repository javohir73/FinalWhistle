/** The Play hub's unified, competition-filtered leaderboard (Floodlight P5,
 *  p5-s4). Renders the REAL shipped boards (LeagueTipsLeaderboard /
 *  NrlTipsLeaderboard) and mocks only their fetch layer -- so the tests prove
 *  the right board mounts per filter AND that a dormant competition is never
 *  fetched (the whole point of the honest-degrade). Distinct handles per
 *  endpoint let us assert which competition's data actually rendered. */
import { fireEvent, render, screen } from "@testing-library/react";
import { PlayLeaderboard } from "./PlayLeaderboard";
import { getLeagueTipsLeaderboard } from "@/lib/leagueTips";
import { getNrlTipsLeaderboard } from "@/lib/nrlTips";

jest.mock("@/lib/leagueTips");
jest.mock("@/lib/nrlTips");

const mockLeague = getLeagueTipsLeaderboard as jest.MockedFunction<typeof getLeagueTipsLeaderboard>;
const mockNrl = getNrlTipsLeaderboard as jest.MockedFunction<typeof getNrlTipsLeaderboard>;

beforeEach(() => {
  mockLeague.mockResolvedValue({
    league: "epl",
    matchweek: 4,
    participant_count: 10,
    entries: [{ handle: "EplTipster", points: 7, exact_count: 2 }],
  });
  mockNrl.mockResolvedValue({
    season: 2026,
    round: 2,
    participant_count: 10,
    entries: [{ handle: "NrlTipster", points: 5, round_margin: 3 }],
  });
});
afterEach(() => jest.resetAllMocks());

function renderBoard(overrides: Partial<React.ComponentProps<typeof PlayLeaderboard>> = {}) {
  return render(
    <PlayLeaderboard
      nrlSeason={2026}
      nrlRound={2}
      footballLeagues={["epl"]}
      footballMatchweeks={{ epl: 4 }}
      {...overrides}
    />,
  );
}

it("defaults to the EPL board, mounting LeagueTipsLeaderboard on the resolved matchweek", async () => {
  renderBoard();

  expect(await screen.findByText("EplTipster")).toBeInTheDocument();
  expect(mockLeague).toHaveBeenCalledWith("epl", 4);
  // NRL isn't the selected filter, so its board never mounts / fetches.
  expect(mockNrl).not.toHaveBeenCalled();
});

it("marks the active chip with lime state and toggle semantics", () => {
  // Matchweek unresolved -> the EPL board stays in its loading state and never
  // fetches, so the chip attributes can be asserted synchronously.
  renderBoard({ footballMatchweeks: {} });

  const epl = screen.getByRole("button", { name: "Premier League" });
  expect(epl).toHaveAttribute("aria-pressed", "true");
  expect(epl).toHaveClass("bg-win");
});

it("switching to the NRL filter mounts NrlTipsLeaderboard seeded from the current round", async () => {
  renderBoard();
  await screen.findByText("EplTipster");

  fireEvent.click(screen.getByRole("button", { name: "NRL" }));

  expect(await screen.findByText("NrlTipster")).toBeInTheDocument();
  expect(mockNrl).toHaveBeenCalledWith(2026, 2);
  // The EPL board unmounts on switch -- one competition's board at a time.
  expect(screen.queryByText("EplTipster")).not.toBeInTheDocument();
});

it("mounts active score-tip leagues on their own resolved matchweek", async () => {
  renderBoard({
    footballLeagues: ["epl", "laliga", "bundesliga"],
    footballMatchweeks: { epl: 4, laliga: 7, bundesliga: 3 },
  });
  await screen.findByText("EplTipster");

  const laliga = screen.getByRole("button", { name: /La Liga/i });
  fireEvent.click(laliga);
  expect(mockLeague).toHaveBeenCalledWith("laliga", 7);

  expect(screen.queryByRole("button", { name: /UEFA Champions League/i })).not.toBeInTheDocument();
});

it("holds the football board back until the matchweek is known (its own loading state)", () => {
  renderBoard({ footballMatchweeks: {} });

  // EPL is selected but the matchweek is unresolved -> the board doesn't mount,
  // so nothing is fetched; the loading state stands in.
  expect(screen.getByRole("status", { name: "Loading leaderboard…" })).toBeInTheDocument();
  expect(mockLeague).not.toHaveBeenCalled();
});

it("degrades the NRL filter to an honest empty state off-season (no round seeded)", () => {
  // footballMatchweek null too, so the default EPL board stays in loading and
  // fires no fetch -- this test is only about NRL's off-season degrade.
  renderBoard({ nrlSeason: null, nrlRound: null, footballMatchweeks: {} });

  fireEvent.click(screen.getByRole("button", { name: "NRL" }));
  expect(screen.getByText("NRL tips aren't available right now.")).toBeInTheDocument();
  expect(mockNrl).not.toHaveBeenCalled();
});
