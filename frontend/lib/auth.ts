/** Clerk integration glue. Auth is entirely client-side (the FastAPI backend
 *  verifies the Clerk JWT via JWKS), so we only need the publishable key — no
 *  secret key, no Next middleware. Everything stays dormant + build-safe when
 *  the key is absent. */
import { API_BASE } from "./api";
import type { SavedBracket } from "./types";

export const CLERK_PUBLISHABLE_KEY = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ?? "";
export const CLERK_ENABLED = CLERK_PUBLISHABLE_KEY.length > 0;

export interface BracketPayload {
  group_picks: { match_id: number; pick: "home" | "draw" | "away" }[];
  knockout_picks: { match_no: number; picked_team_id: number }[];
  champion_team_id: number | null;
  encoded_state: string | null;
}

async function authed<T>(
  path: string,
  token: string | null,
  init: RequestInit = {},
): Promise<T> {
  if (!token) throw new Error("Not signed in");
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      ...(init.headers ?? {}),
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return (await res.json()) as T;
}

export const saveBracket = (token: string | null, body: BracketPayload) =>
  authed<SavedBracket>("/api/brackets", token, { method: "POST", body: JSON.stringify(body) });

/** Restore the signed-in user's saved bracket; null if they have none yet. */
export async function getMyBracket(token: string | null): Promise<SavedBracket | null> {
  if (!token) throw new Error("Not signed in");
  const res = await fetch(`${API_BASE}/api/brackets/me`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`restore failed: ${res.status}`);
  return (await res.json()) as SavedBracket;
}

export const joinLeaderboard = (
  token: string | null,
  body: { display_name: string; visibility: "public" | "private" },
) =>
  authed<SavedBracket>("/api/leaderboard/join", token, {
    method: "POST",
    body: JSON.stringify(body),
  });
