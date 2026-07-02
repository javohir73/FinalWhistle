/** useBracketSync: a signed-in user's saved bracket is restored on return when
 *  there are no local picks, in-progress local picks are never clobbered, and —
 *  critically — session boundaries are safe: pending saves flush on sign-out and
 *  unmount, and one user's local picks never leak into another user's account. */
import { useState } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AuthProvider } from "@/components/AuthProvider";
import { AuthButton } from "@/components/AuthButton";
import { useBracketSync } from "@/lib/useBracketSync";
import * as session from "@/lib/session";
import type { BracketPayload } from "@/lib/session";

jest.mock("@/lib/session");
const mockGetMe = session.getMe as jest.Mock;
const mockGetMyBracket = session.getMyBracket as jest.Mock;
const mockSaveBracket = session.saveBracket as jest.Mock;
const mockLogout = session.logout as jest.Mock;
const mockLoadUserHint = session.loadUserHint as jest.Mock;

/** Pinned public contract: where the device records which account the local
 *  bracket belongs to. */
const OWNER_KEY = "finalwhistle:mybracket:owner:v1";

const alice = { id: 1, email: "a@b.com", display_name: "A", avatar_url: null };
const bob = { id: 2, email: "bob@b.com", display_name: "B", avatar_url: null };

const savedBracket = (matchId: number) => ({
  id: 1, visibility: "private", display_name: null, champion_team_id: null,
  completion_pct: 0, group_picks: [{ match_id: matchId, pick: "home" }], knockout_picks: [],
  score: null, submitted_at: null, updated_at: null,
});

function makeBracket(picks: Record<number, string>, loadFromServer: jest.Mock, reset: jest.Mock = jest.fn()) {
  return {
    groupPicks: picks,
    koPicks: {},
    toBracketPayload: () => ({
      group_picks: [], knockout_picks: [], champion_team_id: null, encoded_state: null,
    }),
    loadFromServer,
    reset,
  };
}

function Probe({ b }: { b: ReturnType<typeof makeBracket> }) {
  useBracketSync(b, true);
  return null;
}

/** Stateful harness: real pick changes + the real sign-out menu. */
function SyncHarness({
  start,
  loadFromServer,
  reset,
}: {
  start: Record<number, "home" | "draw" | "away">;
  loadFromServer: jest.Mock;
  reset: jest.Mock;
}) {
  const [picks, setPicks] = useState(start);
  useBracketSync(
    {
      groupPicks: picks,
      koPicks: {},
      toBracketPayload: (): BracketPayload => ({
        group_picks: Object.entries(picks).map(([id, pick]) => ({
          match_id: Number(id),
          pick: pick as "home" | "draw" | "away",
        })),
        knockout_picks: [],
        champion_team_id: null,
        encoded_state: null,
      }),
      loadFromServer,
      reset,
    },
    true,
  );
  return (
    <>
      <button onClick={() => setPicks((p) => ({ ...p, 99: "home" }))}>add-pick</button>
      <AuthButton />
    </>
  );
}

const signOutViaMenu = () => {
  fireEvent.click(screen.getByLabelText(/^Account:/));
  fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
};

const savedMatchIds = (call: BracketPayload) => call.group_picks.map((p) => p.match_id);

beforeEach(() => {
  localStorage.clear();
  // These scenarios model a RETURNING signed-in user: a cached display hint is
  // present, so the provider reconciles against /auth/me on mount (a guest with
  // no hint would skip the probe entirely).
  mockLoadUserHint.mockReturnValue(alice);
  mockGetMe.mockResolvedValue(alice);
  mockSaveBracket.mockResolvedValue(savedBracket(1));
  mockLogout.mockResolvedValue(undefined);
});
afterEach(() => jest.resetAllMocks());

it("restores the saved bracket on return when local is empty", async () => {
  mockGetMyBracket.mockResolvedValue(savedBracket(1));
  const loadFromServer = jest.fn();

  render(
    <AuthProvider>
      <Probe b={makeBracket({}, loadFromServer)} />
    </AuthProvider>,
  );

  await waitFor(() => expect(mockGetMyBracket).toHaveBeenCalled());
  await waitFor(() => expect(loadFromServer).toHaveBeenCalledTimes(1));
});

it("does not overwrite in-progress anonymous picks (no owner recorded)", async () => {
  mockGetMyBracket.mockResolvedValue(savedBracket(9));
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

it("signing in claims anonymous local picks and pushes them to the account", async () => {
  const loadFromServer = jest.fn();

  render(
    <AuthProvider>
      <SyncHarness start={{ 1: "home" }} loadFromServer={loadFromServer} reset={jest.fn()} />
    </AuthProvider>,
  );

  await waitFor(() => expect(screen.getByLabelText(/^Account:/)).toBeInTheDocument());
  // The debounced auto-save pushes the local picks into the account…
  await waitFor(() => expect(mockSaveBracket).toHaveBeenCalled(), { timeout: 3000 });
  expect(savedMatchIds(mockSaveBracket.mock.calls[0][0])).toContain(1);
  // …and the device now records who those picks belong to.
  expect(localStorage.getItem(OWNER_KEY)).toBe(String(alice.id));
  expect(mockGetMyBracket).not.toHaveBeenCalled();
});

it("flushes an unsaved pick to the account BEFORE the session is revoked on sign-out", async () => {
  localStorage.setItem(OWNER_KEY, String(alice.id));
  render(
    <AuthProvider>
      <SyncHarness start={{ 1: "home" }} loadFromServer={jest.fn()} reset={jest.fn()} />
    </AuthProvider>,
  );
  await waitFor(() => expect(screen.getByLabelText(/^Account:/)).toBeInTheDocument());

  // New pick, then sign out well inside the debounce window.
  fireEvent.click(screen.getByText("add-pick"));
  signOutViaMenu();

  await waitFor(() => expect(mockLogout).toHaveBeenCalled());
  // The pending pick reached the server…
  expect(mockSaveBracket).toHaveBeenCalled();
  const lastSave = mockSaveBracket.mock.calls[mockSaveBracket.mock.calls.length - 1][0];
  expect(savedMatchIds(lastSave)).toEqual(expect.arrayContaining([1, 99]));
  // …and it did so BEFORE the session was revoked.
  const saveOrder = mockSaveBracket.mock.invocationCallOrder;
  const logoutOrder = mockLogout.mock.invocationCallOrder[0];
  expect(Math.min(...saveOrder)).toBeLessThan(logoutOrder);
});

it("flushes an unsaved pick when the page unmounts mid-debounce", async () => {
  localStorage.setItem(OWNER_KEY, String(alice.id));
  const { unmount } = render(
    <AuthProvider>
      <SyncHarness start={{ 1: "home" }} loadFromServer={jest.fn()} reset={jest.fn()} />
    </AuthProvider>,
  );
  await waitFor(() => expect(screen.getByLabelText(/^Account:/)).toBeInTheDocument());

  fireEvent.click(screen.getByText("add-pick"));
  unmount(); // navigation away before the 1.2s debounce fires

  await waitFor(() => expect(mockSaveBracket).toHaveBeenCalled());
  const lastSave = mockSaveBracket.mock.calls[mockSaveBracket.mock.calls.length - 1][0];
  expect(savedMatchIds(lastSave)).toEqual(expect.arrayContaining([1, 99]));
});

it("a different user signing in gets THEIR saved bracket — the previous user's local picks are never pushed", async () => {
  // Device holds Alice's picks…
  localStorage.setItem(OWNER_KEY, String(alice.id));
  // …but BOB signs in.
  mockGetMe.mockResolvedValue(bob);
  mockGetMyBracket.mockResolvedValue(savedBracket(5));
  const loadFromServer = jest.fn();

  render(
    <AuthProvider>
      <SyncHarness start={{ 1: "home" }} loadFromServer={loadFromServer} reset={jest.fn()} />
    </AuthProvider>,
  );

  await waitFor(() => expect(screen.getByLabelText(/^Account:/)).toBeInTheDocument());
  // Bob's saved bracket is restored (server wins over foreign local picks)…
  await waitFor(() => expect(mockGetMyBracket).toHaveBeenCalled());
  await waitFor(() => expect(loadFromServer).toHaveBeenCalledTimes(1));
  expect(loadFromServer.mock.calls[0][0].group_picks).toEqual([{ match_id: 5, pick: "home" }]);
  // …the device re-keys to Bob…
  await waitFor(() => expect(localStorage.getItem(OWNER_KEY)).toBe(String(bob.id)));
  // …and Alice's picks are NOT auto-saved into Bob's account (wait out the debounce).
  await new Promise((r) => setTimeout(r, 1600));
  expect(mockSaveBracket).not.toHaveBeenCalled();
});
