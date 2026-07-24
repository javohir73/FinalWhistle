/** ClaimDeviceTips: merge-on-signup for the beat-the-AI loop (design doc:
 *  NRL Round Tips, Slice 2) -- fires the idempotent /tips/claim call once a
 *  signed-in device is detected, and never for a guest. Renders nothing. */
import { act, render, waitFor } from "@testing-library/react";
import { ClaimDeviceTips } from "./ClaimDeviceTips";
import { AuthProvider } from "@/components/AuthProvider";
import * as session from "@/lib/session";
import { claimNrlTips } from "@/lib/nrlTips";
import type { SessionUser } from "@/lib/session";

jest.mock("@/lib/nrlTips");
jest.mock("@/lib/session", () => {
  const actual = jest.requireActual("@/lib/session");
  return { ...actual, getMe: jest.fn(), getOrCreateDeviceId: jest.fn() };
});

const mockGetMe = session.getMe as jest.MockedFunction<typeof session.getMe>;
const mockClaim = claimNrlTips as jest.MockedFunction<typeof claimNrlTips>;
const mockDeviceId = session.getOrCreateDeviceId as jest.MockedFunction<typeof session.getOrCreateDeviceId>;

const user: SessionUser = { id: 1, email: "a@b.com", display_name: null, avatar_url: null };

beforeEach(() => {
  localStorage.clear();
  // resetAllMocks (below) wipes any implementation set inside the jest.mock
  // factory too, so the device id stub is (re)installed per test here.
  mockDeviceId.mockReturnValue("device-1");
});
afterEach(() => jest.resetAllMocks());

it("fires the claim exactly once for a signed-in device", async () => {
  session.saveUserHint(user); // AuthProvider only reconciles /me when a hint is cached
  mockGetMe.mockResolvedValue(user);
  mockClaim.mockResolvedValue({ ok: true, handle: "SwiftHalfback482", claimed_tips: 3 });

  render(
    <AuthProvider>
      <ClaimDeviceTips />
    </AuthProvider>,
  );

  await waitFor(() => expect(mockClaim).toHaveBeenCalledWith("device-1"));
  expect(mockClaim).toHaveBeenCalledTimes(1);
});

it("never fires for a signed-out device", async () => {
  render(
    <AuthProvider>
      <ClaimDeviceTips />
    </AuthProvider>,
  );

  await act(async () => {}); // flush the mount effect chain
  expect(mockClaim).not.toHaveBeenCalled();
});
