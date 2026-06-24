/** /verify-email: POSTs the ?token= on mount, shows success/error/no-token. */
import { render, screen, waitFor } from "@testing-library/react";
import { VerifyEmailClient } from "./VerifyEmailClient";
import * as session from "@/lib/session";
import { ApiError } from "@/lib/session";

let mockToken: string | null = "vtok";
jest.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: () => mockToken }),
}));
jest.mock("@/components/AuthProvider", () => ({
  useAuth: () => ({ refresh: jest.fn() }),
}));
jest.mock("@/lib/session", () => {
  const actual = jest.requireActual("@/lib/session");
  return { ...actual, verifyEmail: jest.fn() };
});
const mockVerify = session.verifyEmail as jest.Mock;

afterEach(() => {
  jest.resetAllMocks();
  mockToken = "vtok";
});

it("verifies the token on mount and shows success", async () => {
  mockVerify.mockResolvedValue({ ok: true, already_verified: false });
  render(<VerifyEmailClient />);
  await waitFor(() => expect(mockVerify).toHaveBeenCalledWith("vtok"));
  expect(await screen.findByText(/email verified/i)).toBeInTheDocument();
});

it("shows an error for an invalid/expired token", async () => {
  mockVerify.mockRejectedValue(
    new ApiError(400, "invalid_token", "This verification link is invalid or has expired."),
  );
  render(<VerifyEmailClient />);
  expect(await screen.findByText(/couldn.t verify/i)).toBeInTheDocument();
});

it("shows the invalid state and skips the API when there's no token", () => {
  mockToken = null;
  render(<VerifyEmailClient />);
  expect(screen.getByText(/verification link invalid/i)).toBeInTheDocument();
  expect(mockVerify).not.toHaveBeenCalled();
});
