/** Play hub page -- server component (SSR) output. PlayHub is a static client
 *  shell (no providers needed in this slice), so this file checks the server
 *  wiring: it renders both sport group headings, seeds the NRL group from
 *  getNrlTipsheetServer, and degrades (no crash) when that fetch returns null
 *  or rejects. The per-sport pick sections arrive in p5-s2/p5-s3. */
import { render, screen } from "@testing-library/react";
import PlayPage from "./page";
import { getNrlTipsheetServer } from "@/lib/api";
import type { NrlTipsheet } from "@/lib/types";

jest.mock("@/lib/api");
const mockTipsheet = getNrlTipsheetServer as jest.MockedFunction<typeof getNrlTipsheetServer>;

const tipsheet: NrlTipsheet = {
  season: 2026,
  round: 2,
  matches: [],
  record: {
    evaluated_matches: 0, winner_accuracy: null, winner_accuracy_ci95: null,
    avg_log_loss: null, avg_brier: null, best_streak: 0, last_updated: null,
  },
  worst_miss: null,
  disclaimer: "For analytics and entertainment only. Not betting advice.",
};

afterEach(() => jest.resetAllMocks());

it("renders the Play title and both sport group headings", async () => {
  mockTipsheet.mockResolvedValue(tipsheet);
  render(await PlayPage());

  expect(screen.getByRole("heading", { level: 1, name: "Play" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Football" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "NRL" })).toBeInTheDocument();
});

it("seeds the NRL group with the current round when the tipsheet loads", async () => {
  mockTipsheet.mockResolvedValue(tipsheet);
  render(await PlayPage());

  expect(mockTipsheet).toHaveBeenCalledWith();
  expect(screen.getByText("Round 2 · 2026")).toBeInTheDocument();
});

it("degrades (both groups render, no round line, no crash) when the tipsheet is null", async () => {
  mockTipsheet.mockResolvedValue(null);
  render(await PlayPage());

  expect(screen.getByRole("heading", { name: "Football" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "NRL" })).toBeInTheDocument();
  expect(screen.queryByText(/^Round /)).not.toBeInTheDocument();
});

it("degrades (no crash) when the NRL tipsheet fetch rejects", async () => {
  mockTipsheet.mockRejectedValue(new Error("upstream down"));
  render(await PlayPage());

  expect(screen.getByRole("heading", { name: "Football" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "NRL" })).toBeInTheDocument();
});
