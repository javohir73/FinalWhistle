import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { LeagueTipsPicker } from "./LeagueTipsPicker";
import { getMyLeagueTips, submitLeagueTip } from "@/lib/leagueTips";
import { ApiError, getOrCreateDeviceId, pingDailyActivity } from "@/lib/session";
import type { LeagueTipsMineResponse } from "@/lib/types";

jest.mock("@/lib/leagueTips");
jest.mock("@/lib/session", () => {
  const actual = jest.requireActual("@/lib/session");
  return { ...actual, getOrCreateDeviceId: jest.fn(), pingDailyActivity: jest.fn() };
});

const mockMine = getMyLeagueTips as jest.MockedFunction<typeof getMyLeagueTips>;
const mockSubmit = submitLeagueTip as jest.MockedFunction<typeof submitLeagueTip>;
const mockDeviceId = getOrCreateDeviceId as jest.MockedFunction<typeof getOrCreateDeviceId>;
const mockPing = pingDailyActivity as jest.MockedFunction<typeof pingDailyActivity>;

// resetAllMocks (below) wipes any implementation set inside the jest.mock
// factory too, so the device id / ping stubs are (re)installed per test here
// rather than baked in above. localStorage also isn't reset between tests by
// default -- a confirmed submit's cache write must not leak a stale
// prediction into a later test's initial render (mirrors PlayRound.test.tsx).
beforeEach(() => {
  localStorage.clear();
  mockDeviceId.mockReturnValue("device-1");
  mockPing.mockResolvedValue(undefined);
});
afterEach(() => jest.resetAllMocks());

const future = (mins: number) => new Date(Date.now() + mins * 60_000).toISOString();
const past = (mins: number) => new Date(Date.now() - mins * 60_000).toISOString();

function mine(overrides: Partial<LeagueTipsMineResponse> = {}): LeagueTipsMineResponse {
  return {
    league: "epl",
    matchweek: 3,
    handle: "SwiftStriker42",
    matches: [
      {
        id: 501, home: "Arsenal", away: "Chelsea", kickoff_utc: future(60), status: "scheduled",
        score_home: null, score_away: null,
        model: { predicted_home: 2, predicted_away: 1, model_version: "poisson-elo-club-v0.1" },
        your_prediction: null,
      },
    ],
    disclaimer: "For analytics and entertainment only. Not betting advice.",
    ...overrides,
  };
}

it("submits the device id, match and full scoreline payload when a stepper is tapped", async () => {
  mockMine.mockResolvedValue(mine());
  mockSubmit.mockResolvedValue({
    ok: true, handle: "SwiftStriker42",
    prediction: { match_id: 501, predicted_home: 1, predicted_away: 0, updated_at: "2026-08-22T10:00:00+00:00" },
  });

  render(<LeagueTipsPicker league="epl" />);
  const group = await screen.findByRole("group", { name: /Arsenal vs Chelsea/i });
  fireEvent.click(within(group).getByRole("button", { name: "Increase Arsenal goals" }));

  await waitFor(() =>
    expect(mockSubmit).toHaveBeenCalledWith("epl", {
      device_id: "device-1", match_id: 501, predicted_home: 1, predicted_away: 0,
    }),
  );
  expect(mockPing).toHaveBeenCalled();
});

it("shows both a home and away goals input for an unlocked fixture", async () => {
  mockMine.mockResolvedValue(mine());
  render(<LeagueTipsPicker league="epl" />);
  await screen.findByRole("group", { name: /Arsenal vs Chelsea/i });
  expect(screen.getAllByRole("spinbutton")).toHaveLength(2);
});

it("disables the decrement button at 0 goals and the increment button at 15", async () => {
  mockMine.mockResolvedValue(
    mine({
      matches: [
        {
          id: 501, home: "Arsenal", away: "Chelsea", kickoff_utc: future(60), status: "scheduled",
          score_home: null, score_away: null, model: null,
          your_prediction: {
            predicted_home: 0, predicted_away: 15, points: null, exact: null,
            graded_at: null, updated_at: "2026-08-01T00:00:00Z",
          },
        },
      ],
    }),
  );

  render(<LeagueTipsPicker league="epl" />);
  await screen.findByRole("group", { name: /Arsenal vs Chelsea/i });
  expect(screen.getByRole("button", { name: "Decrease Arsenal goals" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Increase Chelsea goals" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Increase Arsenal goals" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Decrease Chelsea goals" })).toBeEnabled();
});

it("renders a kickoff-locked row frozen, with no picker controls", async () => {
  mockMine.mockResolvedValue(
    mine({
      matches: [
        {
          id: 502, home: "Arsenal", away: "Chelsea", kickoff_utc: past(10), status: "scheduled",
          score_home: null, score_away: null, model: null,
          your_prediction: {
            predicted_home: 2, predicted_away: 1, points: null, exact: null,
            graded_at: null, updated_at: "2026-08-01T00:00:00Z",
          },
        },
      ],
    }),
  );

  render(<LeagueTipsPicker league="epl" />);
  expect(await screen.findByText("Locked")).toBeInTheDocument();
  expect(screen.getByText(/You predicted/)).toBeInTheDocument();
  expect(screen.getByText(/awaiting full time/)).toBeInTheDocument();
  expect(screen.queryByRole("group")).not.toBeInTheDocument();
});

it("shows the no-prediction-submitted state for a locked match the device never predicted", async () => {
  mockMine.mockResolvedValue(
    mine({
      matches: [
        {
          id: 503, home: "Arsenal", away: "Chelsea", kickoff_utc: past(5), status: "scheduled",
          score_home: null, score_away: null, model: null, your_prediction: null,
        },
      ],
    }),
  );

  render(<LeagueTipsPicker league="epl" />);
  expect(await screen.findByText("No prediction submitted")).toBeInTheDocument();
});

it("shows the graded verdict once a locked prediction has been scored", async () => {
  mockMine.mockResolvedValue(
    mine({
      matches: [
        {
          id: 504, home: "Arsenal", away: "Chelsea", kickoff_utc: past(200), status: "finished",
          score_home: 2, score_away: 1, model: null,
          your_prediction: {
            predicted_home: 2, predicted_away: 1, points: 5, exact: true,
            graded_at: "2026-08-01T12:00:00Z", updated_at: "2026-08-01T00:00:00Z",
          },
        },
      ],
    }),
  );

  render(<LeagueTipsPicker league="epl" />);
  expect(await screen.findByText(/exact score!/)).toBeInTheDocument();
  expect(screen.getByText(/Final 2–1/)).toBeInTheDocument();
});

it("navigates to the next matchweek and re-fetches with the new number", async () => {
  mockMine.mockResolvedValueOnce(mine({ matchweek: 3 }));
  mockMine.mockResolvedValueOnce(
    mine({
      matchweek: 4,
      matches: [
        {
          id: 601, home: "Liverpool", away: "Everton", kickoff_utc: future(120), status: "scheduled",
          score_home: null, score_away: null, model: null, your_prediction: null,
        },
      ],
    }),
  );

  render(<LeagueTipsPicker league="epl" />);
  await screen.findByText("Matchweek 3");

  fireEvent.click(screen.getByRole("button", { name: /Matchweek 4/ }));
  await waitFor(() => expect(mockMine).toHaveBeenLastCalledWith("epl", "device-1", 4));
  expect(await screen.findByText("Matchweek 4")).toBeInTheDocument();
  expect(await screen.findByRole("group", { name: /Liverpool vs Everton/i })).toBeInTheDocument();
});

it("shows a friendly message and keeps the current matchweek when nav runs off the end", async () => {
  mockMine.mockResolvedValueOnce(mine({ matchweek: 3 }));
  mockMine.mockRejectedValueOnce(new ApiError(404, "matchweek_not_found", "No matches for matchweek 4"));

  render(<LeagueTipsPicker league="epl" />);
  await screen.findByText("Matchweek 3");

  fireEvent.click(screen.getByRole("button", { name: /Matchweek 4/ }));
  expect(await screen.findByText(/No epl matches loaded for that matchweek yet\./)).toBeInTheDocument();
  expect(screen.getByText("Matchweek 3")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Matchweek 4/ })).not.toBeInTheDocument();
});

it("hides the Prev control on matchweek 1", async () => {
  mockMine.mockResolvedValue(mine({ matchweek: 1 }));
  render(<LeagueTipsPicker league="epl" />);
  await screen.findByText("Matchweek 1");
  expect(screen.queryByRole("button", { name: /Matchweek 0/ })).not.toBeInTheDocument();
});

it("shows a season-not-started state when the league has no data loaded yet", async () => {
  mockMine.mockRejectedValue(new ApiError(404, "league_inactive", "League 'epl' has no data loaded yet"));
  render(<LeagueTipsPicker league="epl" />);
  expect(await screen.findByText(/hasn't kicked off yet/)).toBeInTheDocument();
});

it("shows the same season-not-started state for any other league passed in, not just epl", async () => {
  mockMine.mockRejectedValue(new ApiError(404, "league_inactive", "League 'laliga' has no data loaded yet"));
  render(<LeagueTipsPicker league="laliga" />);
  expect(await screen.findByText(/hasn't kicked off yet/)).toBeInTheDocument();
  expect(mockMine).toHaveBeenCalledWith("laliga", "device-1", undefined);
});

it("treats league_not_found for an unregistered league the same as league_inactive", async () => {
  mockMine.mockRejectedValue(new ApiError(404, "league_not_found", "Unknown league 'bundesliga'"));
  render(<LeagueTipsPicker league="bundesliga" />);
  expect(await screen.findByText(/hasn't kicked off yet/)).toBeInTheDocument();
});

it("surfaces a rejected submit honestly and reverts the optimistic prediction", async () => {
  mockMine.mockResolvedValue(mine());
  mockSubmit.mockRejectedValue(new ApiError(422, "match_locked", "Match 501 has kicked off and is locked."));

  render(<LeagueTipsPicker league="epl" />);
  const group = await screen.findByRole("group", { name: /Arsenal vs Chelsea/i });
  fireEvent.click(within(group).getByRole("button", { name: "Increase Arsenal goals" }));

  expect(await screen.findByText("Match 501 has kicked off and is locked.")).toBeInTheDocument();
  expect(within(group).getByRole("spinbutton", { name: "Arsenal goals" })).toHaveValue(0);
});
