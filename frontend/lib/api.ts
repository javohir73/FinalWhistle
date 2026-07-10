/** Typed client for the FastAPI backend.
 *  Base URL comes from NEXT_PUBLIC_API_URL so dev/prod point at the right host. */
import type {
  Goalscorers,
  Group,
  IntelResponse,
  KnockoutBracket,
  LadderResponse,
  LeaderboardRow,
  MarketBenchmark,
  MatchLineups,
  MatchSummary,
  ModelRecord,
  MoversResponse,
  NrlMatchDetail,
  NrlMatchesResponse,
  NrlMatchStatsResponse,
  NrlProbHistory,
  NrlProjectionsResponse,
  NrlRecord,
  NrlStatsProfile,
  NrlTeamProfile,
  Prediction,
  ProbHistory,
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

/** Client-side base. Browser calls are routed through a same-origin Next rewrite
 *  (`/backend-api/*` → backend, see next.config.mjs) so the session cookie is sent
 *  (SameSite=Lax) and the CSP connect-src can stay `'self'`. Paths keep their
 *  `/api/...` prefix; the rewrite forwards `/backend-api/api/x` → `<backend>/api/x`. */
export const CLIENT_BASE = "/backend-api";

export interface HealthResponse {
  status: string;
  app: string;
  model_version: string;
  live_updates?: "ready" | "inactive";
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${CLIENT_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`API ${path} failed: ${res.status}`);
  }
  return (await res.json()) as T;
}

export const getHealth = () => getJson<HealthResponse>("/api/health");
export const getUpcomingMatches = () =>
  getJson<MatchSummary[]>("/api/matches/upcoming");
export const getTeams = () => getJson<Team[]>("/api/teams");
export const getTeam = (id: number | string) =>
  getJson<TeamProfile>(`/api/teams/${id}`);
export const getGroups = () => getJson<Group[]>("/api/groups");
export const getKnockoutOdds = () =>
  getJson<TournamentOdds[]>("/api/knockout/odds");
export const getOfficialBracket = () =>
  getJson<KnockoutBracket>("/api/knockout/bracket");
export const getLeaderboard = () =>
  getJson<LeaderboardRow[]>("/api/leaderboard");
export const getMatchSummary = (id: number | string) =>
  getJson<MatchSummary>(`/api/matches/${id}/summary`);
/** Display-only official lineups; resolves to `{ available: false }` when none
 *  exist yet (future fixture, no API key, or provider error) — never throws. */
export const getMatchLineups = (id: number | string) =>
  getJson<MatchLineups>(`/api/matches/${id}/lineups`);
export const getModelRecord = () =>
  getJson<ModelRecord>("/api/model/record");
export const getMovers = (sport: "football" | "nrl", limit = 3) =>
  getJson<MoversResponse>(`/api/movers?sport=${sport}&limit=${limit}`);
/** Market intel (Polymarket/Kalshi vs the model). has_data=false means the
 *  caller should render the movers fallback instead. */
export const getIntel = (sport: "football" | "nrl") =>
  getJson<IntelResponse>(`/api/intel?sport=${sport}`);
export const getProbHistory = (matchId: number | string) =>
  getJson<ProbHistory>(`/api/matches/${matchId}/prob-history`);

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
/** Short revalidate: this seeds the live scoreboard on the match page. */
export const getMatchSummaryServer = (id: number | string) =>
  getServer<MatchSummary>(`/api/matches/${id}/summary`, 30);
/** Short revalidate so a fixture flips from the placeholder to its real XI soon
 *  after the lineup is announced (~40 min pre-kickoff). Always returns a payload
 *  (possibly `{ available: false }`); never 404s for a valid match. */
export const getMatchLineupsServer = (id: number | string) =>
  getServer<MatchLineups>(`/api/matches/${id}/lineups`, 60);
/** Likely scorers (top players by chance to score). Short revalidate so the card
 *  flips from the squad estimate to the confirmed XI soon after the lineup is
 *  announced (~40 min pre-kickoff). Returns null when no player data exists. */
export const getMatchGoalscorersServer = (id: number | string) =>
  getServer<Goalscorers>(`/api/matches/${id}/goalscorers`, 60);
export const getTeamsServer = () =>
  getServer<Team[]>("/api/teams", 600);
export const getTeamServer = (id: number | string) =>
  getServer<TeamProfile>(`/api/teams/${id}`, 600);
export const getGroupServer = (id: number | string) =>
  getServer<Group>(`/api/groups/${id}`, 300);
export const getUpcomingMatchesServer = () =>
  getServer<MatchSummary[]>("/api/matches/upcoming", 300);
export const getKnockoutOddsServer = () =>
  getServer<TournamentOdds[]>("/api/knockout/odds", 600);
export const getOfficialBracketServer = () =>
  getServer<KnockoutBracket>("/api/knockout/bracket", 30);
export const getGroupsServer = () =>
  getServer<Group[]>("/api/groups", 300);
export const getLeaderboardServer = () =>
  getServer<LeaderboardRow[]>("/api/leaderboard", 60);
export const getModelRecordServer = () =>
  getServer<ModelRecord>("/api/model/record", 300);
export const getMarketRecordServer = () =>
  getServer<MarketBenchmark>("/api/model/market-record", 300);

/** Server-side NRL fetchers (ISR). Reuse `getServer` above (same 404->null,
 *  ISR-revalidate behavior as the football fetchers) rather than adding a
 *  second serverGet-style helper. */
export const getNrlMatchesServer = (revalidate = 300) =>
  getServer<NrlMatchesResponse>("/api/nrl/matches", revalidate);
/** One round's fixtures, season+round scoped. Backs the match detail page:
 *  NRL matches are keyed by (season, round, match_no) and there is no
 *  per-match endpoint, so the page picks its match out of the round payload. */
export const getNrlRoundServer = (season: number, round: number) =>
  getServer<NrlMatchesResponse>(`/api/nrl/matches?season=${season}&round=${round}`, 300);
export const getNrlLadderServer = () =>
  getServer<LadderResponse>("/api/nrl/ladder", 300);
export const getNrlTeamServer = (id: number | string) =>
  getServer<NrlTeamProfile>(`/api/nrl/teams/${id}`, 300);
/** Wave 2 club stats profile (attack/defence ranks, venue splits). */
export const getNrlStatsProfileServer = (slug: string) =>
  getServer<NrlStatsProfile>(`/api/nrl/teams/${slug}/profile`, 300);
export const getNrlRecordServer = () =>
  getServer<NrlRecord>("/api/nrl/model/record", 300);
export const getNrlMatchDetailServer = (id: number | string) =>
  getServer<NrlMatchDetail>(`/api/nrl/matches/${id}`, 300);
export const getNrlProjectionsServer = () =>
  getServer<NrlProjectionsResponse>("/api/nrl/projections", 300);
export const getNrlProbHistoryServer = (id: number | string) =>
  getServer<NrlProbHistory>(`/api/nrl/matches/${id}/prob-history`, 300);
