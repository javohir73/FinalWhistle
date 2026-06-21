/** "Restore from cloud" must never silently overwrite in-progress local picks: when the
 *  local bracket differs from the saved copy the restore is gated behind an
 *  explicit confirm, while an empty or identical local bracket restores straight
 *  away (no needless prompt). */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AuthProvider } from "@/components/AuthProvider";
import { AccountPanel } from "@/components/AccountPanel";
import * as session from "@/lib/session";
import type { BracketPayload } from "@/lib/session";
import type { SavedBracket } from "@/lib/types";

jest.mock("@/lib/session");
const mockGetMe = session.getMe as jest.Mock;
const mockLoadUserHint = session.loadUserHint as jest.Mock;
const mockGetMyBracket = session.getMyBracket as jest.Mock;

const alice = { id: 1, email: "a@b.com", display_name: "Alice", avatar_url: null };

type Pick = { match_id: number; pick: "home" | "draw" | "away" };

const savedBracket = (picks: Pick[]): SavedBracket => ({
  id: 1, visibility: "private", display_name: null, champion_team_id: null,
  completion_pct: 0, group_picks: picks, knockout_picks: [],
  score: null, submitted_at: null, updated_at: null,
});

const payload = (picks: Pick[]): BracketPayload => ({
  group_picks: picks, knockout_picks: [], champion_team_id: null, encoded_state: null,
});

beforeEach(() => {
  localStorage.clear();
  mockLoadUserHint.mockReturnValue(alice); // render the signed-in panel immediately
  mockGetMe.mockResolvedValue(alice);
});
afterEach(() => jest.resetAllMocks());

function renderPanel(local: BracketPayload) {
  const onRestore = jest.fn();
  render(
    <AuthProvider>
      <AccountPanel getPayload={() => local} onRestore={onRestore} />
    </AuthProvider>,
  );
  return onRestore;
}

it("asks before a restore would discard different in-progress picks", async () => {
  mockGetMyBracket.mockResolvedValue(savedBracket([{ match_id: 1, pick: "away" }]));
  const onRestore = renderPanel(payload([{ match_id: 1, pick: "home" }]));

  fireEvent.click(await screen.findByText("Restore from cloud"));

  // The confirm appears and the restore is held back.
  await waitFor(() =>
    expect(screen.getByText(/Replace your current picks/i)).toBeInTheDocument(),
  );
  expect(onRestore).not.toHaveBeenCalled();

  // Confirming runs the restore with the fetched bracket.
  fireEvent.click(screen.getByRole("button", { name: "Replace my picks" }));
  expect(onRestore).toHaveBeenCalledTimes(1);
  expect(onRestore.mock.calls[0][0].group_picks).toEqual([{ match_id: 1, pick: "away" }]);
});

it("keeps current picks when the confirm is declined", async () => {
  mockGetMyBracket.mockResolvedValue(savedBracket([{ match_id: 1, pick: "away" }]));
  const onRestore = renderPanel(payload([{ match_id: 1, pick: "home" }]));

  fireEvent.click(await screen.findByText("Restore from cloud"));
  fireEvent.click(await screen.findByRole("button", { name: "Keep current" }));

  expect(onRestore).not.toHaveBeenCalled();
  expect(screen.queryByText(/Replace your current picks/i)).not.toBeInTheDocument();
});

it("restores immediately when there are no local picks to lose", async () => {
  mockGetMyBracket.mockResolvedValue(savedBracket([{ match_id: 1, pick: "away" }]));
  const onRestore = renderPanel(payload([]));

  fireEvent.click(await screen.findByText("Restore from cloud"));

  await waitFor(() => expect(onRestore).toHaveBeenCalledTimes(1));
  expect(screen.queryByText(/Replace your current picks/i)).not.toBeInTheDocument();
});

it("restores without a prompt when local picks already match the saved copy", async () => {
  mockGetMyBracket.mockResolvedValue(savedBracket([{ match_id: 1, pick: "home" }]));
  const onRestore = renderPanel(payload([{ match_id: 1, pick: "home" }]));

  fireEvent.click(await screen.findByText("Restore from cloud"));

  await waitFor(() => expect(onRestore).toHaveBeenCalledTimes(1));
  expect(screen.queryByText(/Replace your current picks/i)).not.toBeInTheDocument();
});
