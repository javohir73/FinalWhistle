/** AuthModal: password show/hide, plus STEP 1 hardening — it shows friendly copy
 *  (never the raw "Origin not allowed") and handles offline without a doomed
 *  request. login/register are mocked; friendlyAuthError/ApiError stay real. */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AuthModal } from "@/components/AuthModal";
import { ApiError } from "@/lib/session";
import * as session from "@/lib/session";

jest.mock("@/lib/session", () => {
  const actual = jest.requireActual("@/lib/session");
  return { ...actual, login: jest.fn(), register: jest.fn(), requestPasswordReset: jest.fn() };
});
const mockLogin = session.login as jest.Mock;
const mockRequestReset = session.requestPasswordReset as jest.Mock;

const setOnline = (value: boolean) =>
  Object.defineProperty(navigator, "onLine", { configurable: true, value });

afterEach(() => {
  jest.resetAllMocks();
  setOnline(true);
});

const fillCreds = () => {
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "a@b.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password123" } });
};

it("toggles password visibility and reflects state via aria-pressed", () => {
  render(<AuthModal open onClose={() => {}} onAuthed={() => {}} />);
  const pwd = screen.getByLabelText("Password") as HTMLInputElement;
  expect(pwd.type).toBe("password");
  fireEvent.click(screen.getByRole("button", { name: "Show password" }));
  expect(pwd.type).toBe("text");
  const hide = screen.getByRole("button", { name: "Hide password" });
  expect(hide).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(hide);
  expect(pwd.type).toBe("password");
});

it("shows friendly copy and never the raw origin-guard text on a 403", async () => {
  mockLogin.mockRejectedValue(new ApiError(403, "forbidden_origin", "Origin not allowed"));
  render(<AuthModal open onClose={() => {}} onAuthed={() => {}} />);
  fillCreds();
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

  expect(await screen.findByText(/reload the page/i)).toBeInTheDocument();
  expect(screen.queryByText(/origin not allowed/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/forbidden_origin/i)).not.toBeInTheDocument();
});

it("short-circuits when offline: shows a connection message and never calls the API", async () => {
  setOnline(false);
  render(<AuthModal open onClose={() => {}} onAuthed={() => {}} />);
  fillCreds();
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

  expect(await screen.findByText(/offline|connection/i)).toBeInTheDocument();
  expect(mockLogin).not.toHaveBeenCalled();
});

it("forgot-password: requests a reset and shows a neutral, enumeration-safe confirmation", async () => {
  mockRequestReset.mockResolvedValue({ ok: true });
  render(<AuthModal open onClose={() => {}} onAuthed={() => {}} />);

  fireEvent.click(screen.getByRole("button", { name: /forgot password/i }));
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "x@y.com" } });
  fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));

  await waitFor(() => expect(mockRequestReset).toHaveBeenCalledWith("x@y.com"));
  expect(await screen.findByText(/if an account exists/i)).toBeInTheDocument();
});

it("shows themed inline errors on empty submit instead of native browser validation", () => {
  render(<AuthModal open onClose={() => {}} onAuthed={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

  const emailInput = screen.getByLabelText("Email address");
  const passwordInput = screen.getByLabelText("Password");
  expect(screen.getByText("Email is required.")).toBeInTheDocument();
  expect(screen.getByText("Password is required.")).toBeInTheDocument();
  expect(emailInput).toHaveAttribute("aria-invalid", "true");
  expect(emailInput).toHaveAttribute("aria-describedby", "auth-email-error");
  expect(passwordInput).toHaveAttribute("aria-invalid", "true");
  expect(passwordInput).toHaveAttribute("aria-describedby", "auth-password-error");
  expect(mockLogin).not.toHaveBeenCalled();

  // Fixing a field clears just that field's inline error.
  fireEvent.change(emailInput, { target: { value: "a@b.com" } });
  expect(screen.queryByText("Email is required.")).not.toBeInTheDocument();
  expect(screen.getByText("Password is required.")).toBeInTheDocument();
});

it("clears the offline message once connectivity returns", async () => {
  setOnline(false);
  render(<AuthModal open onClose={() => {}} onAuthed={() => {}} />);
  fillCreds();
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByText(/offline|connection/i)).toBeInTheDocument();

  setOnline(true);
  fireEvent(window, new Event("online"));
  await waitFor(() =>
    expect(screen.queryByText(/offline|connection/i)).not.toBeInTheDocument(),
  );
});
