import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RunHomePredictor } from "./RunHomePredictor";
import { getNrlConditionalProjections } from "@/lib/nrlRunHome";
import type { NrlConditionalProjectionsResponse, NrlMatch } from "@/lib/types";

jest.mock("@/lib/nrlRunHome");
const mockConditional = getNrlConditionalProjections as jest.MockedFunction<typeof getNrlConditionalProjections>;

const replace = jest.fn();
let mockPicksParam: string | null = null;
jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => ({ get: (key: string) => (key === "picks" ? mockPicksParam : null) }),
}));

afterEach(() => {
  jest.resetAllMocks();
  mockPicksParam = null;
});

const future = (mins: number) => new Date(Date.now() + mins * 60_000).toISOString();
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function match(overrides: Partial<NrlMatch>): NrlMatch {
  return {
    id: 1, match_no: 1, kickoff_utc: future(60), venue: "AAMI Park",
    home: "Storm", away: "Eels", home_team_id: 1, away_team_id: 2,
    score_home: null, score_away: null, status: "scheduled",
    prediction: {
      p_home: 0.62, p_draw: 0.02, p_away: 0.36, expected_margin: 4,
      model_version: "nrl-elo-v0.1", created_at: null, is_shadow: true,
    },
    ...overrides,
  };
}

const rounds = [
  {
    round: 20,
    matches: [
      match({ id: 1 }),
      match({
        id: 2, home: "Broncos", away: "Titans", home_team_id: 3, away_team_id: 4,
        prediction: { p_home: 0.4, p_draw: 0.02, p_away: 0.58, expected_margin: -3, model_version: "nrl-elo-v0.1", created_at: null, is_shadow: true },
      }),
    ],
  },
];

const baseline: NrlConditionalProjectionsResponse = {
  season: 2026, n_sims: 2000, picks_applied: 0,
  teams: [
    { team: "Storm", top8: 0.9, top4: 0.5, minor_premiership: 0.2, expected_points: 40, expected_remaining_wins: 18 },
    { team: "Broncos", top8: 0.6, top4: 0.3, minor_premiership: 0.05, expected_points: 30, expected_remaining_wins: 13 },
  ],
};

/** The odds panel row for `team` -- disambiguates from the same team name
 *  appearing in the fixture card and its pick buttons by requiring a <tr>
 *  ancestor (only the odds table has one). */
function oddsRowFor(team: string): HTMLElement {
  const row = screen.getAllByText(team).map((el) => el.closest("tr")).find((el): el is HTMLTableRowElement => el !== null);
  if (!row) throw new Error(`no odds row found for ${team}`);
  return row;
}

it("encodes a tapped pick into the URL via router.replace (no history push)", async () => {
  render(<RunHomePredictor season={2026} rounds={rounds} baseline={baseline} />);
  const group = screen.getByRole("group", { name: /Storm vs Eels/i });
  fireEvent.click(within(group).getByRole("button", { name: "Storm" }));

  await waitFor(() => expect(replace).toHaveBeenCalledWith("/nrl/run-home?picks=1h", { scroll: false }));
  expect(within(group).getByRole("button", { name: "Storm" })).toHaveAttribute("aria-pressed", "true");
});

it("shows baseline odds by default and swaps to the conditional response once the debounced fetch resolves", async () => {
  mockConditional.mockResolvedValue({
    ...baseline, picks_applied: 1,
    teams: [{ ...baseline.teams[0], top8: 0.97 }, baseline.teams[1]],
  });

  render(<RunHomePredictor season={2026} rounds={rounds} baseline={baseline} />);
  expect(oddsRowFor("Storm").textContent).toContain("90%");

  const group = screen.getByRole("group", { name: /Storm vs Eels/i });
  fireEvent.click(within(group).getByRole("button", { name: "Storm" }));
  await act(() => wait(450)); // clears the ~400ms debounce

  await waitFor(() => expect(mockConditional).toHaveBeenCalledWith(2026, "1h"));
  await waitFor(() => expect(oddsRowFor("Storm").textContent).toContain("97%"));
  expect(oddsRowFor("Storm").textContent).toContain("+7pts");
});

it("discards a stale response that resolves after a newer pick's response", async () => {
  const first = deferred<NrlConditionalProjectionsResponse>();
  const second = deferred<NrlConditionalProjectionsResponse>();
  mockConditional.mockImplementationOnce(() => first.promise).mockImplementationOnce(() => second.promise);

  render(<RunHomePredictor season={2026} rounds={rounds} baseline={baseline} />);

  fireEvent.click(within(screen.getByRole("group", { name: /Storm vs Eels/i })).getByRole("button", { name: "Storm" }));
  await act(() => wait(450));

  fireEvent.click(within(screen.getByRole("group", { name: /Broncos vs Titans/i })).getByRole("button", { name: "Broncos" }));
  await act(() => wait(450));

  expect(mockConditional).toHaveBeenNthCalledWith(1, 2026, "1h");
  expect(mockConditional).toHaveBeenNthCalledWith(2, 2026, "1h,2h");

  // Resolve the newer (second) request first, then the stale (first) one --
  // the stale, out-of-order resolution must never win.
  await act(async () => {
    second.resolve({ ...baseline, picks_applied: 2, teams: [{ ...baseline.teams[0], top8: 0.99 }, baseline.teams[1]] });
    await second.promise;
  });
  await act(async () => {
    first.resolve({ ...baseline, picks_applied: 1, teams: [{ ...baseline.teams[0], top8: 0.11 }, baseline.teams[1]] });
    await first.promise;
  });

  expect(oddsRowFor("Storm").textContent).toContain("99%");
  expect(oddsRowFor("Storm").textContent).not.toContain("11%");
});

it("degrades gracefully to baseline plus a quiet notice for an invalid ?picks= param", () => {
  mockPicksParam = "999h,not-a-token";
  render(<RunHomePredictor season={2026} rounds={rounds} baseline={baseline} />);

  expect(screen.getByText(/weren't valid/i)).toBeInTheDocument();
  expect(mockConditional).not.toHaveBeenCalled();
  expect(oddsRowFor("Storm").textContent).toContain("90%");
});

it("restores valid picks from ?picks= on load and fetches their conditional odds", async () => {
  mockPicksParam = "1h";
  mockConditional.mockResolvedValue({ ...baseline, picks_applied: 1 });

  render(<RunHomePredictor season={2026} rounds={rounds} baseline={baseline} />);
  const group = screen.getByRole("group", { name: /Storm vs Eels/i });
  expect(within(group).getByRole("button", { name: "Storm" })).toHaveAttribute("aria-pressed", "true");

  await act(() => wait(450));
  await waitFor(() => expect(mockConditional).toHaveBeenCalledWith(2026, "1h"));
});

it("reset clears every pick, strips the URL back to the plain path, and restores baseline odds", async () => {
  mockConditional.mockResolvedValue({
    ...baseline, picks_applied: 1,
    teams: [{ ...baseline.teams[0], top8: 0.5 }, baseline.teams[1]],
  });

  render(<RunHomePredictor season={2026} rounds={rounds} baseline={baseline} />);
  fireEvent.click(within(screen.getByRole("group", { name: /Storm vs Eels/i })).getByRole("button", { name: "Storm" }));
  await act(() => wait(450));
  await waitFor(() => expect(oddsRowFor("Storm").textContent).toContain("50%"));

  fireEvent.click(screen.getByRole("button", { name: "Reset" }));

  expect(replace).toHaveBeenLastCalledWith("/nrl/run-home", { scroll: false });
  expect(oddsRowFor("Storm").textContent).toContain("90%");
  expect(screen.getByText("0 picks applied")).toBeInTheDocument();
});

it("shows the odds panel as loading while a conditional fetch is in flight", async () => {
  const pending = deferred<NrlConditionalProjectionsResponse>();
  mockConditional.mockImplementationOnce(() => pending.promise);

  const { container } = render(<RunHomePredictor season={2026} rounds={rounds} baseline={baseline} />);
  fireEvent.click(within(screen.getByRole("group", { name: /Storm vs Eels/i })).getByRole("button", { name: "Storm" }));
  await act(() => wait(450));

  expect(container.querySelector(".animate-pulse")).not.toBeNull();

  await act(async () => {
    pending.resolve({ ...baseline, picks_applied: 1 });
    await pending.promise;
  });
  expect(container.querySelector(".animate-pulse")).toBeNull();
});
