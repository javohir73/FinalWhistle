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
  expect(mockGetMe).toHaveBeenCalledTimes(1); // the fix: no post-login /me

  // Opening the menu reveals the email + Sign out.
  fireEvent.click(screen.getByLabelText("Account: Pat"));
  expect(screen.getByText("pat@example.com")).toBeInTheDocument();
  expect(screen.getByRole("menuitem", { name: "Sign out" })).toBeInTheDocument();
});
