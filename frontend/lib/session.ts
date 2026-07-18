/** First-party session auth client (replaces the old Clerk glue).
 *
 *  Every call goes to the same-origin `/backend-api/*` proxy with
 *  `credentials: "include"`, so the HttpOnly session cookie is sent and received
 *  automatically — there is no token in JS and nothing in localStorage. */
import { CLIENT_BASE } from "./api";
import type { SavedBracket } from "./types";

export interface BracketPayload {
  group_picks: { match_id: number; pick: "home" | "draw" | "away" }[];
  knockout_picks: { match_no: number; picked_team_id: number }[];
  champion_team_id: number | null;
  encoded_state: string | null;
}

export interface SessionUser {
  id: number;
  email: string;
  display_name: string | null;
  avatar_url: string | null;
  // Optional: a cached hint from before this field existed won't have it, so
  // `undefined` means "unknown" (don't show the verify banner until /me confirms).
  email_verified?: boolean;
}

/** Error carrying the backend's {code,message} so callers can show friendly copy. */
export class ApiError extends Error {
  code: string;
  status: number;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

// The free-tier backend sleeps when idle; without a cap a cold-start request can
// hang for the browser default (~minutes). Abort at 30s and surface a typed
// timeout so the UI can say "waking up — try again" instead of spinning forever.
const REQUEST_TIMEOUT_MS = 30_000;

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${CLIENT_BASE}${path}`, {
      ...init,
      cache: "no-store",
      credentials: "include",
      signal: controller.signal,
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(init.headers ?? {}),
      },
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new ApiError(
        408,
        "request_timeout",
        "The request timed out — the server may be waking up. Please try again.",
      );
    }
    throw e; // network failure (TypeError) — mapped by friendlyAuthError
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let code = `http_${res.status}`;
    let message = "Something went wrong — please try again.";
    try {
      const body = await res.json();
      if (body?.error) {
        code = body.error.code ?? code;
        message = body.error.message ?? message;
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, code, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---- Auth ----
export const register = (email: string, password: string, display_name?: string) =>
  request<SessionUser>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, display_name }),
  });

export const login = (email: string, password: string) =>
  request<SessionUser>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

export async function logout(): Promise<void> {
  try {
    await request<{ ok: boolean }>("/api/auth/logout", { method: "POST" });
  } catch {
    /* logout is best-effort; the cookie is cleared server-side regardless */
  }
}

/** Permanently delete (anonymize) the signed-in account. Requires the current
 *  password as a re-auth check; the server revokes the session and clears the
 *  cookie. Throws ApiError (e.g. 401 invalid_credentials) on failure. */
export async function deleteAccount(password: string): Promise<void> {
  await request<{ ok: boolean }>("/api/auth/delete-account", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
}

/** Map any thrown auth error to safe, friendly copy. Never surfaces the raw
 *  origin-guard text ("Origin not allowed" / forbidden_origin), and turns
 *  cold-start 5xx/timeouts and connection failures into clear guidance. The
 *  single place the auth UI converts errors to display text. */
export function friendlyAuthError(e: unknown, opts: { offline?: boolean } = {}): string {
  const COLD =
    "The match server is waking up after a quiet spell. Please try again in a few seconds.";
  const OFFLINE = "You appear to be offline. Check your connection and try again.";
  const NETWORK = "We couldn’t reach the server — check your connection and try again.";
  const GENERIC = "Something went wrong — please try again.";

  if (opts.offline) return OFFLINE;

  if (e instanceof ApiError) {
    if (e.code === "forbidden_origin") {
      return "We couldn’t verify this request. Reload the page and try again — if it keeps happening you may be on an old link.";
    }
    if (e.code === "too_many_attempts") {
      return "Too many attempts. Please wait a few minutes and try again.";
    }
    if (e.code === "request_timeout" || e.status >= 500 || e.code.startsWith("http_5")) {
      return COLD;
    }
    // Other backend codes (invalid_credentials, email_taken, invalid_email,
    // weak_password, …) already carry user-friendly messages.
    return e.message || GENERIC;
  }

  if (typeof navigator !== "undefined" && navigator.onLine === false) return OFFLINE;
  if (e instanceof DOMException && e.name === "AbortError") return COLD;
  if (e instanceof TypeError) return NETWORK; // fetch network failure
  return GENERIC;
}

/** Current signed-in user, or null when there's no live session. */
export async function getMe(): Promise<SessionUser | null> {
  try {
    return await request<SessionUser>("/api/auth/me");
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null;
    throw e;
  }
}

// ---- Password reset ----
/** Start a reset. The backend always resolves 200 (no account enumeration), so
 *  the UI shows the same neutral confirmation regardless. */
export const requestPasswordReset = (email: string) =>
  request<{ ok: boolean }>("/api/auth/request-reset", {
    method: "POST",
    body: JSON.stringify({ email }),
  });

/** Consume a reset token from the emailed link and set a new password. Throws
 *  ApiError (invalid_token / weak_password) on failure. */
export const resetPassword = (token: string, new_password: string) =>
  request<{ ok: boolean }>("/api/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, new_password }),
  });

// ---- Email verification ----
/** Confirm an email from the link's token. Works without a session (the token is
 *  the proof). Returns { already_verified } so a re-clicked link reads friendly. */
export const verifyEmail = (token: string) =>
  request<{ ok: boolean; already_verified: boolean }>("/api/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({ token }),
  });

/** Re-send the verification email to the signed-in user (no-op 200 if signed out
 *  or already verified). Throws ApiError (too_many_attempts) when rate-limited. */
export const resendVerification = () =>
  request<{ ok: boolean }>("/api/auth/resend-verification", { method: "POST" });

// ---- Brackets / leaderboard (cookie-authed) ----
export const saveBracket = (body: BracketPayload) =>
  request<SavedBracket>("/api/brackets", {
    method: "POST",
    body: JSON.stringify(body),
    // This call is also the sign-out / leave-page flush; keepalive lets it
    // complete even while the page is being torn down.
    keepalive: true,
  });

export async function getMyBracket(): Promise<SavedBracket | null> {
  try {
    return await request<SavedBracket>("/api/brackets/me");
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

export const joinLeaderboard = (body: { display_name: string; visibility: "public" | "private" }) =>
  request<SavedBracket>("/api/leaderboard/join", { method: "POST", body: JSON.stringify(body) });

// ---- WC26 retention bridge (post-final "what's next" email capture) ----
/** Best-effort: the session cookie (if any) is sent as usual, so the backend
 *  attaches user_id when the caller is signed in — no extra param needed here. */
export const notifyBridge = (email: string, source = "wc26_final_bridge") =>
  request<{ ok: boolean }>("/api/bridge/notify", {
    method: "POST",
    body: JSON.stringify({ email, source }),
  });

// ---- Display-only signed-in hint ----
// A cached copy of the public user fields so the account indicator can render
// instantly on every page/navigation (and survive a reload) without waiting on
// /auth/me. This is NOT auth: it holds no token and cannot authenticate anything
// — the HttpOnly cookie remains the only credential. /auth/me reconciles it, and
// a confirmed 401 or logout clears it.
const USER_HINT_KEY = "fw_user";

export function loadUserHint(): SessionUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(USER_HINT_KEY);
    return raw ? (JSON.parse(raw) as SessionUser) : null;
  } catch {
    return null;
  }
}

export function saveUserHint(user: SessionUser): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(USER_HINT_KEY, JSON.stringify(user));
  } catch {
    /* storage unavailable (private mode / quota) — non-fatal */
  }
}

export function clearUserHint(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(USER_HINT_KEY);
  } catch {
    /* non-fatal */
  }
}
