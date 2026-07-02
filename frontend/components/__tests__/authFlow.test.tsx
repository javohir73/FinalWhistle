/** Regression: the nav must reflect signed-in state immediately after login,
 *  using the user returned by login() — NOT a second /auth/me call, which can race
 *  the just-set cookie's visibility (Safari/PWA). Signed-in shows an account circle
 *  (initials) with a Sign-out menu. */
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { AuthProvider } from "@/components/AuthProvider";
import { AuthButton } from "@/components/AuthButton";
import * as session from "@/lib/session";

jest.mock("@/lib/session");
const mockGetMe = session.getMe as jest.MockedFunction<typeof session.getMe>;
const mockLogin = session.login as jest.MockedFunction<typeof session.login>;
const mockRegister = session.register as jest.MockedFunction<typeof session.register>;
const mockLogout = session.logout as jest.MockedFunction<typeof session.logout>;

beforeEach(() => {
  localStorage.clear();
  mockGetMe.mockResolvedValue(null); // start signed out (mount-time /me)
});
afterEach(() => jest.resetAllMocks());

it("shows the account circle right after login without a second /me call", async () => {
  mockLogin.mockResolvedValue({
    id: 1, email: "pat@example.com", display_name: "Pat", avatar_url: null,
  });

  render(
    <AuthProvider>
      <AuthButton />
    </AuthProvider>,
  );

  // Signed out → the nav shows "Sign in".
  await waitFor(() => expect(screen.getByText("Sign in")).toBeInTheDocument());
  fireEvent.click(screen.getByText("Sign in"));

  // Fill + submit the modal's sign-in form.
  const dialog = screen.getByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Email address"), {
    target: { value: "pat@example.com" },
  });
  fireEvent.change(within(dialog).getByLabelText("Password"), {
    target: { value: "supersecret" },
  });
  fireEvent.submit(dialog.querySelector("form")!);

  // Account circle (initials) appears immediately; modal closes.
  await waitFor(() => expect(screen.getByLabelText("Account: Pat")).toBeInTheDocument());
  expect(screen.getByText("P")).toBeInTheDocument(); // initials
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  // A guest with no cached hint never probes /auth/me — not on mount (it would
  // only 401) and not after login (login() is the source of truth).
  expect(mockGetMe).not.toHaveBeenCalled();

  // Opening the menu reveals the email + Sign out.
  fireEvent.click(screen.getByLabelText("Account: Pat"));
  expect(screen.getByText("pat@example.com")).toBeInTheDocument();
  expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeInTheDocument();
});

it("does not leak the previous user's details into the next sign-up (shared device)", async () => {
  mockRegister.mockResolvedValue({
    id: 1, email: "alice@example.com", display_name: "Alice Test", avatar_url: null,
  });
  mockLogout.mockResolvedValue(undefined);

  render(
    <AuthProvider>
      <AuthButton />
    </AuthProvider>,
  );

  // Alice signs up (with a display name)…
  await waitFor(() => expect(screen.getByText("Sign in")).toBeInTheDocument());
  fireEvent.click(screen.getByText("Sign in"));
  let dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("tab", { name: "Switch to create account" }));
  fireEvent.change(within(dialog).getByLabelText("Display name"), { target: { value: "Alice Test" } });
  fireEvent.change(within(dialog).getByLabelText("Email address"), { target: { value: "alice@example.com" } });
  fireEvent.change(within(dialog).getByLabelText("Password"), { target: { value: "alice-pass-123" } });
  fireEvent.submit(dialog.querySelector("form")!);
  await waitFor(() => expect(screen.getByLabelText("Account: Alice Test")).toBeInTheDocument());

  // …signs out…
  fireEvent.click(screen.getByLabelText("Account: Alice Test"));
  fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
  await waitFor(() => expect(screen.getByText("Sign in")).toBeInTheDocument());

  // …and when the modal opens again for the NEXT person, it starts back on the
  // Sign-in tab and no field carries over.
  fireEvent.click(screen.getByText("Sign in"));
  dialog = screen.getByRole("dialog");
  expect(within(dialog).getByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
  // The mode switcher is a tablist with distinct accessible names, so the submit
  // button is the only role=button named "Sign in"/"Create account".
  expect(within(dialog).getAllByRole("button", { name: "Sign in" })).toHaveLength(1);
  expect(within(dialog).getByRole("tab", { name: "Switch to sign in" })).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("tab", { name: "Switch to create account" }));
  expect((within(dialog).getByLabelText("Display name") as HTMLInputElement).value).toBe("");
  expect((within(dialog).getByLabelText("Email address") as HTMLInputElement).value).toBe("");
  expect((within(dialog).getByLabelText("Password") as HTMLInputElement).value).toBe("");
});
