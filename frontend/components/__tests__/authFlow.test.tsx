/** Regression: the nav/account UI must reflect signed-in state immediately after
 *  login, using the user returned by login() — NOT a second /auth/me call, which
 *  can race the just-set cookie's visibility (Safari/PWA) and leave the UI showing
 *  "Sign in" even though the session is valid. */
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { AuthProvider } from "@/components/AuthProvider";
import { AuthButton } from "@/components/AuthButton";
import * as session from "@/lib/session";

jest.mock("@/lib/session");
const mockGetMe = session.getMe as jest.MockedFunction<typeof session.getMe>;
const mockLogin = session.login as jest.MockedFunction<typeof session.login>;

beforeEach(() => {
  mockGetMe.mockResolvedValue(null); // start signed out (mount-time /me)
});
afterEach(() => jest.resetAllMocks());

it("shows signed-in state right after login without a second /me call", async () => {
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

  // After login resolves, the nav reflects the signed-in user immediately.
  await waitFor(() => expect(screen.getByText("Sign out")).toBeInTheDocument());
  expect(screen.getByText("Pat")).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); // modal closed

  // The fix: no post-login /auth/me — only the single mount-time call ran.
  expect(mockGetMe).toHaveBeenCalledTimes(1);
});
