/** VerifyEmailBanner: prompts only an explicitly-unverified signed-in user
 *  (undefined = unknown from a stale hint => hidden), and resends on demand. */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { VerifyEmailBanner } from "@/components/VerifyEmailBanner";
import * as session from "@/lib/session";
import { ApiError, type SessionUser } from "@/lib/session";

jest.mock("@/lib/session", () => {
  const actual = jest.requireActual("@/lib/session");
  return { ...actual, resendVerification: jest.fn() };
});
const mockResend = session.resendVerification as jest.Mock;

const user = (over: Partial<SessionUser> = {}): SessionUser => ({
  id: 1, email: "a@b.com", display_name: null, avatar_url: null, ...over,
});

afterEach(() => jest.resetAllMocks());

it("shows only when email_verified is explicitly false", () => {
  const { rerender } = render(<VerifyEmailBanner user={user({ email_verified: false })} />);
  expect(screen.getByText(/verify your email/i)).toBeInTheDocument();

  rerender(<VerifyEmailBanner user={user({ email_verified: true })} />);
  expect(screen.queryByText(/verify your email/i)).not.toBeInTheDocument();

  rerender(<VerifyEmailBanner user={user()} />); // undefined → unknown → hidden
  expect(screen.queryByText(/verify your email/i)).not.toBeInTheDocument();

  rerender(<VerifyEmailBanner user={null} />);
  expect(screen.queryByText(/verify your email/i)).not.toBeInTheDocument();
});

it("resends the email and confirms", async () => {
  mockResend.mockResolvedValue({ ok: true });
  render(<VerifyEmailBanner user={user({ email_verified: false })} />);
  fireEvent.click(screen.getByRole("button", { name: /resend email/i }));
  await waitFor(() => expect(mockResend).toHaveBeenCalled());
  expect(await screen.findByText(/sent — check your inbox/i)).toBeInTheDocument();
});

it("shows a friendly message when rate-limited", async () => {
  mockResend.mockRejectedValue(
    new ApiError(429, "too_many_attempts", "Please wait before requesting another email."),
  );
  render(<VerifyEmailBanner user={user({ email_verified: false })} />);
  fireEvent.click(screen.getByRole("button", { name: /resend email/i }));
  expect(await screen.findByText(/wait/i)).toBeInTheDocument();
});
