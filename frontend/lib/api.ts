/** Typed client for the FastAPI backend.
 *  Base URL comes from NEXT_PUBLIC_API_URL so dev/prod point at the right host. */
import type {
  Group,
  LeaderboardRow,
  MatchSummary,
  Prediction,
  PredictionWithHistory,
  Team,
  TeamProfile,
  TournamentOdds,
} from "./types";

/** Base URL for the backend. Required in production: a missing value used to
 *  silently fall back to localhost, which builds fine but points deployed pages
 *  at a host that doesn't exist. Fail the build instead so the misconfig is
 *  caught before it ships. The localhost default stays for local dev/test. */
function resolveApiUrl(): string {
  const url = process.env.NEXT_PUBLIC_API_URL;
  if (url) return url;
  if (process.env.NODE_ENV === "production") {
    throw new Error(
      "NEXT_PUBLIC_API_URL is not set. Configure it in the deployment environment " +
        "before building — refusing to fall back to http://localhost:8000 in production.",
    );
  }
  return "http://localhost:8000";
}

const API_URL = resolveApiUrl();
/** Resolved backend base URL (for authed clients in lib/auth.ts). */
export const API_BASE = API_URL;

export interface HealthResponse {
  status: string;
  app: string;
  model_version: string;
  live_updates?: "ready" | "inactive";
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`API ${path} failed: ${res.status}`);
  }
  return (await res.json()) as T;
}

export const getHealth = () => getJson<HealthResponse>("/api/health");
export const getUpcomingMatches = () =>
  getJson<MatchSummary[]>("/api/matches/upcoming");
export const getMatch = (id: number | string) =>
  getJson<Prediction>(`/api/matches/${id}`);
export const getPrediction = (matchId: number | string) =>
  getJson<PredictionWithHistory>(`/api/predictions/${matchId}`);
export const getTeams = () => getJson<Team[]>("/api/teams");
export const getTeam = (id: number | string) =>
  getJson<TeamProfile>(`/api/teams/${id}`);
export const getGroups = () => getJson<Group[]>("/api/groups");
export const getGroup = (id: number | string) =>
  getJson<Group>(`/api/groups/${id}`);
export const getKnockoutOdds = () =>
  getJson<TournamentOdds[]>("/api/knockout/odds");
export const getLeaderboard = () =>
  getJson<LeaderboardRow[]>("/api/leaderboard");

/** Server-side fetchers for SSR (App Router). ISR-cached so pages render fast
 *  HTML and stay resilient to backend cold starts; returns null on 404. */
async function getServer<T>(path: string, revalidate: number): Promise<T | null> {
  const res = await fetch(`${API_URL}${path}`, { next: { revalidate } });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`);
  return (await res.json()) as T;
}

export const getMatchServer = (id: number | string) =>
  getServer<Prediction>(`/api/matches/${id}`, 300);
export const getTeamServer = (id: number | string) =>
  getServer<TeamProfile>(`/api/teams/${id}`, 600);
export const getGroupServer = (id: number | string) =>
  getServer<Group>(`/api/groups/${id}`, 300);
export const getUpcomingMatchesServer = () =>
  getServer<MatchSummary[]>("/api/matches/upcoming", 300);
export const getKnockoutOddsServer = () =>
  getServer<TournamentOdds[]>("/api/knockout/odds", 600);
