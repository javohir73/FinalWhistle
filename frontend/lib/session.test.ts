/** STEP 1 auth hardening: friendlyAuthError never leaks the raw origin-guard
 *  text and maps cold-start/offline/timeout to clear copy; request() aborts a
 *  hung request (Render cold start) instead of spinning forever. */
import { friendlyAuthError, ApiError, login, getOrCreateDeviceId, pingDailyActivity } from "./session";

describe("friendlyAuthError", () => {
  it("never surfaces the raw origin-guard text to users", () => {
    const out = friendlyAuthError(new ApiError(403, "forbidden_origin", "Origin not allowed"));
    expect(out).not.toMatch(/origin not allowed/i);
    expect(out).not.toMatch(/forbidden_origin/);
    expect(out.length).toBeGreaterThan(0);
  });

  it("maps 5xx and request timeouts to a 'waking up' message", () => {
    expect(friendlyAuthError(new ApiError(502, "http_502", "Bad Gateway"))).toMatch(/waking up|few seconds/i);
    expect(friendlyAuthError(new ApiError(500, "internal", "boom"))).toMatch(/waking up|few seconds/i);
    expect(friendlyAuthError(new ApiError(408, "request_timeout", "timed out"))).toMatch(/waking up|few seconds/i);
  });

  it("maps too_many_attempts to a wait message", () => {
    expect(
      friendlyAuthError(new ApiError(429, "too_many_attempts", "Too many attempts. Try again later.")),
    ).toMatch(/wait/i);
  });

  it("passes through already-friendly backend messages", () => {
    expect(
      friendlyAuthError(new ApiError(401, "invalid_credentials", "Incorrect email or password.")),
    ).toBe("Incorrect email or password.");
    expect(
      friendlyAuthError(new ApiError(409, "email_taken", "An account with that email already exists.")),
    ).toBe("An account with that email already exists.");
  });

  it("treats explicit offline, and network TypeErrors, as connection problems", () => {
    expect(friendlyAuthError(null, { offline: true })).toMatch(/offline|connection/i);
    expect(friendlyAuthError(new TypeError("Failed to fetch"))).toMatch(/offline|connection/i);
  });

  it("falls back to a generic message for unknown values", () => {
    expect(friendlyAuthError({} as unknown)).toMatch(/something went wrong/i);
  });
});

describe("request() timeout (cold-start safety net)", () => {
  const realFetch = global.fetch;
  afterEach(() => {
    global.fetch = realFetch;
    jest.useRealTimers();
  });

  it("aborts a hung request and rejects with a request_timeout ApiError", async () => {
    jest.useFakeTimers();
    // A fetch that never resolves — until its AbortSignal fires.
    global.fetch = jest.fn(
      (_url: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    ) as unknown as typeof fetch;

    const p = login("a@b.com", "password123");
    const assertion = expect(p).rejects.toMatchObject({ code: "request_timeout", status: 408 });
    await jest.advanceTimersByTimeAsync(30_000);
    await assertion;
  });
});

describe("getOrCreateDeviceId", () => {
  beforeEach(() => localStorage.clear());

  it("mints a UUID once and reuses the same id on later calls", () => {
    const first = getOrCreateDeviceId();
    const second = getOrCreateDeviceId();
    expect(first).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);
    expect(second).toBe(first);
    expect(localStorage.getItem("fw_device_id")).toBe(first);
  });
});

describe("pingDailyActivity", () => {
  const realFetch = global.fetch;
  const todayUtc = () => new Date().toISOString().slice(0, 10);

  beforeEach(() => localStorage.clear());
  afterEach(() => {
    global.fetch = realFetch;
    jest.resetAllMocks();
  });

  it("fires the ping when the marker is stale/absent and sets it only on success", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    }) as unknown as typeof fetch;

    await pingDailyActivity();

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toBe("/backend-api/api/activity/ping");
    expect(JSON.parse(init.body as string)).toMatchObject({ device_id: expect.any(String) });
    expect(localStorage.getItem("fw_last_ping")).toBe(todayUtc());
  });

  it("skips the ping entirely when the marker already matches today", async () => {
    localStorage.setItem("fw_last_ping", todayUtc());
    global.fetch = jest.fn() as unknown as typeof fetch;

    await pingDailyActivity();

    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("does not set the marker, and does not throw, when the ping fails", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ error: { code: "http_500", message: "boom" } }),
    }) as unknown as typeof fetch;

    await expect(pingDailyActivity()).resolves.toBeUndefined();
    expect(localStorage.getItem("fw_last_ping")).toBeNull();
  });

  it("is silent (never throws, no retry within the call) on a network failure", async () => {
    global.fetch = jest.fn().mockRejectedValue(new TypeError("Failed to fetch")) as unknown as typeof fetch;

    await expect(pingDailyActivity()).resolves.toBeUndefined();
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem("fw_last_ping")).toBeNull();
  });
});
