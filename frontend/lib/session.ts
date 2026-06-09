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

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${CLIENT_BASE}${path}`, {
    ...init,
    cache: "no-store",
    credentials: "include",
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  });
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

/** Current signed-in user, or null when there's no live session. */
export async function getMe(): Promise<SessionUser | null> {
  try {
    return await request<SessionUser>("/api/auth/me");
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null;
    throw e;
  }
}

// ---- Brackets / leaderboard (cookie-authed) ----
export const saveBracket = (body: BracketPayload) =>
  request<SavedBracket>("/api/brackets", { method: "POST", body: JSON.stringify(body) });

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
