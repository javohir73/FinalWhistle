/** Install prompt (PRD FR 4.4): engagement-gated, never on first load, never in
 *  standalone, Android native flow vs iOS manual steps, permanent dismiss. The
 *  prompt is also deferred a grace period after an in-session engagement signal
 *  so it never pops over the action that triggered it (shortened to 0 here). */
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { InstallAppPrompt } from "@/components/InstallAppPrompt";
import { recordEngagement } from "@/lib/engagement";
import { __setInstallPromptSettleMs } from "@/lib/useInstallPrompt";

class FakeBeforeInstallPromptEvent extends Event {
  prompt = jest.fn().mockResolvedValue(undefined);
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
  constructor(outcome: "accepted" | "dismissed" = "accepted") {
    super("beforeinstallprompt", { cancelable: true });
    this.userChoice = Promise.resolve({ outcome });
  }
}

function fireBeforeInstallPrompt(outcome: "accepted" | "dismissed" = "accepted") {
  const e = new FakeBeforeInstallPromptEvent(outcome);
  act(() => {
    window.dispatchEvent(e);
  });
  return e;
}

const setUserAgent = (ua: string) =>
  Object.defineProperty(window.navigator, "userAgent", { value: ua, configurable: true });

const DESKTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0";
const IOS_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Version/18.0 Mobile Safari";

beforeEach(() => {
  localStorage.clear();
  setUserAgent(DESKTOP_UA);
  __setInstallPromptSettleMs(0); // no grace delay in specs; one test overrides it
});

afterEach(() => jest.resetAllMocks());

it("shows nothing on first load — even when the browser offers an install", () => {
  render(<InstallAppPrompt />);
  fireBeforeInstallPrompt();
  expect(screen.queryByText("Install FinalWhistle")).not.toBeInTheDocument();
});

it("appears after an engagement signal when the native prompt is available", async () => {
  render(<InstallAppPrompt />);
  fireBeforeInstallPrompt();
  act(() => {
    recordEngagement("pick");
  });
  expect(await screen.findByText("Install FinalWhistle")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Install app" })).toBeInTheDocument();
});

it("defers the prompt a grace period so it doesn't interrupt the triggering action", async () => {
  __setInstallPromptSettleMs(80);
  render(<InstallAppPrompt />);
  fireBeforeInstallPrompt();
  act(() => {
    recordEngagement("pick");
  });
  // Not shown immediately on the pick that crossed engagement…
  expect(screen.queryByText("Install FinalWhistle")).not.toBeInTheDocument();
  // …but appears once the grace period elapses.
  expect(await screen.findByText("Install FinalWhistle")).toBeInTheDocument();
});

it("two My Bracket visits cross the engagement threshold; one does not", async () => {
  render(<InstallAppPrompt />);
  fireBeforeInstallPrompt();
  act(() => {
    recordEngagement("my-bracket-visit");
  });
  expect(screen.queryByText("Install FinalWhistle")).not.toBeInTheDocument();
  act(() => {
    recordEngagement("my-bracket-visit");
  });
  expect(await screen.findByText("Install FinalWhistle")).toBeInTheDocument();
});

it("fires the captured native prompt when Install app is tapped", async () => {
  render(<InstallAppPrompt />);
  const bip = fireBeforeInstallPrompt("accepted");
  act(() => {
    recordEngagement("pick");
  });
  fireEvent.click(await screen.findByRole("button", { name: "Install app" }));
  await waitFor(() => expect(bip.prompt).toHaveBeenCalled());
});

it("shows manual Add-to-Home-Screen steps on iOS (no install event exists)", async () => {
  setUserAgent(IOS_UA);
  render(<InstallAppPrompt />);
  act(() => {
    recordEngagement("menu-open");
  });
  expect(await screen.findByText("Install FinalWhistle")).toBeInTheDocument();
  expect(screen.getByText(/Add to Home Screen/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Install app" })).not.toBeInTheDocument();
});

it("dismiss is permanent — survives a remount", async () => {
  const { unmount } = render(<InstallAppPrompt />);
  fireBeforeInstallPrompt();
  act(() => {
    recordEngagement("pick");
  });
  fireEvent.click(await screen.findByRole("button", { name: "Dismiss install prompt" }));
  expect(screen.queryByText("Install FinalWhistle")).not.toBeInTheDocument();

  unmount();
  render(<InstallAppPrompt />);
  fireBeforeInstallPrompt();
  act(() => {
    recordEngagement("pick");
  });
  // Even after the grace period the prompt stays hidden (dismiss persisted).
  await waitFor(() => {
    expect(screen.queryByText("Install FinalWhistle")).not.toBeInTheDocument();
  });
});

it("never shows when already running standalone (installed)", async () => {
  const orig = window.matchMedia;
  window.matchMedia = ((q: string) => ({
    matches: q === "(display-mode: standalone)",
    media: q,
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
  try {
    render(<InstallAppPrompt />);
    fireBeforeInstallPrompt();
    act(() => {
      recordEngagement("pick");
    });
    await waitFor(() => {
      expect(screen.queryByText("Install FinalWhistle")).not.toBeInTheDocument();
    });
  } finally {
    window.matchMedia = orig;
  }
});
