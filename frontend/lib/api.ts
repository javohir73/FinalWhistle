/** Typed client for the FastAPI backend.
 *  Base URL comes from NEXT_PUBLIC_API_URL so dev/prod point at the right host. */
import type {
  Group,
  MatchSummary,
  Prediction,
  PredictionWithHistory,
  Team,
  TeamProfile,
  TournamentOdds,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface HealthResponse {
  status: string;
  app: string;
  model_version: string;
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
