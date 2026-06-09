/** useBracketSync: a signed-in user's saved bracket is restored on return when
 *  there are no local picks, and in-progress local picks are never clobbered. */
import { render, waitFor } from "@testing-library/react";
import { AuthProvider } from "@/components/AuthProvider";
import { useBracketSync } from "@/lib/useBracketSync";
import * as session from "@/lib/session";

jest.mock("@/lib/session");
const mockGetMe = session.getMe as jest.Mock;
const mockGetMyBracket = session.getMyBracket as jest.Mock;

function makeBracket(picks: Record<number, string>, loadFromServer: jest.Mock) {
  return {
    groupPicks: picks,
    koPicks: {},
    toBracketPayload: () => ({
      group_picks: [], knockout_picks: [], champion_team_id: null, encoded_state: null,
    }),
    loadFromServer,
  };
}

function Probe({ b }: { b: ReturnType<typeof makeBracket> }) {
  useBracketSync(b, true);
  return null;
}

beforeEach(() => {
  localStorage.clear();
  mockGetMe.mockResolvedValue({ id: 1, email: "a@b.com", display_name: "A", avatar_url: null });
});
afterEach(() => jest.resetAllMocks());

it("restores the saved bracket on return when local is empty", async () => {
  mockGetMyBracket.mockResolvedValue({
    id: 1, visibility: "private", display_name: null, champion_team_id: null,
    completion_pct: 0, group_picks: [{ match_id: 1, pick: "home" }], knockout_picks: [],
    score: null, submitted_at: null, updated_at: null,
  });
  const loadFromServer = jest.fn();

  render(
    <AuthProvider>
      <Probe b={makeBracket({}, loadFromServer)} />
    </AuthProvider>,
  );

  await waitFor(() => expect(mockGetMyBracket).toHaveBeenCalled());
  await waitFor(() => expect(loadFromServer).toHaveBeenCalledTimes(1));
});

it("does not overwrite in-progress local picks", async () => {
  mockGetMyBracket.mockResolvedValue({
    id: 1, visibility: "private", display_name: null, champion_team_id: null,
    completion_pct: 0, group_picks: [{ match_id: 9, pick: "away" }], knockout_picks: [],
    score: null, submitted_at: null, updated_at: null,
  });
  const loadFromServer = jest.fn();

  render(
    <AuthProvider>
      <Probe b={makeBracket({ 1: "home" }, loadFromServer)} />
    </AuthProvider>,
  );

  // Give the (signed-in) effects a chance to run, then assert we did NOT load.
  await waitFor(() => expect(mockGetMe).toHaveBeenCalled());
  expect(mockGetMyBracket).not.toHaveBeenCalled();
  expect(loadFromServer).not.toHaveBeenCalled();
});
