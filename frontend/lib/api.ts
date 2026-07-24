/** Typed client for the FastAPI backend.
 *  Base URL comes from NEXT_PUBLIC_API_URL so dev/prod point at the right host. */
import type {
  ActiveTournament,
  Goalscorers,
  Group,
  IntelResponse,
  KnockoutBracket,
  LadderResponse,
  LeaderboardRow,
  LeagueTipsShareResponse,
  MarketBenchmark,
  MatchLineups,
  MatchSummary,
  ModelRecord,
  MoversResponse,
  NrlConditionalProjectionsResponse,
  NrlLive,
  NrlMatchDetail,
  NrlMatchesResponse,
  NrlMatchStatsResponse,
  NrlProbHistory,
  NrlProjectionsResponse,
  NrlRecord,
  NrlScorer,
  NrlStatsProfile,
  NrlTeamProfile,
  NrlTipsheet,
  NrlTipsShareResponse,
  OriginRecord,
  OriginSeriesResponse,
  Prediction,
  ProbHistory,
  RetentionStats,
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

/** The tournament currently live on the site (league pivot, see lib/types.ts
 *  ActiveTournament). Resolves to null on a 404 — the endpoint ships with a
 *  parallel backend workstream — so callers should go through
 *  lib/tournament.ts's getTournament() for the WC26 fallback rather than
 *  calling this directly. */
export const getActiveTournamentServer = () =>
  getServer<ActiveTournament>("/api/tournaments/active", 300);

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
/** Round tipsheet (design doc: NRL Round Tips, Slice 1): model pick per game,
 *  season record, and last round's worst miss, in one payload. No args
 *  resolves the current round server-side; pass season+round for a specific
 *  round permalink (see /nrl/round/[n]). */
export const getNrlTipsheetServer = (season?: number, round?: number) =>
  getServer<NrlTipsheet>(
    season != null && round != null
      ? `/api/nrl/tips?season=${season}&round=${round}`
      : "/api/nrl/tips",
    300,
  );
export const getNrlMatchDetailServer = (id: number | string) =>
  getServer<NrlMatchDetail>(`/api/nrl/matches/${id}`, 300);
/** Public share-card data for /nrl/tips/share/[season]/[round]/[handle] and
 *  its opengraph-image (Slice 2.5) -- season/round/handle come only from the
 *  route params, never a client-supplied score. A graded result never changes
 *  once it exists, so a longer revalidate would otherwise be fine (unlike the
 *  rest of this file's live-ish 300s default) -- but kept short (60s) because
 *  the not-found->found transition right after grading is NOT idempotent: a
 *  crawler hitting the share link between full-time and grading would
 *  otherwise pin the pre-grading 404 in the Data Cache for up to an hour. */
export const getNrlTipsShareServer = (season: number, round: number, handle: string) =>
  getServer<NrlTipsShareResponse>(
    `/api/nrl/tips/share/${season}/${round}/${encodeURIComponent(handle)}`,
    60,
  );
export const getNrlProjectionsServer = () =>
  getServer<NrlProjectionsResponse>("/api/nrl/projections", 300);
/** The conditional/what-if variant (design doc: NRL Round Tips, Slice 3), with
 *  no picks -- the unconditioned baseline used to seed /nrl/run-home's SSR
 *  shell and to diff against once the client starts forcing picks. The RNG is
 *  seeded from (season, picks, n_sims) (see backend/app/api/nrl_intel.py), so
 *  this is deterministic and safe to ISR-cache same as every other fetcher here. */
export const getNrlConditionalProjectionsServer = (season: number) =>
  getServer<NrlConditionalProjectionsResponse>(`/api/nrl/projections/conditional?season=${season}`, 300);
export const getNrlProbHistoryServer = (id: number | string) =>
  getServer<NrlProbHistory>(`/api/nrl/matches/${id}/prob-history`, 300);
/** Wave 3 live layer: polled every 60s by the match page's Live section
 *  (a client island — browser calls go through the /backend-api rewrite,
 *  and nothing server-renders this section, so there is no SSR variant). */
export async function getNrlLiveClient(matchId: number): Promise<NrlLive> {
  return getJson<NrlLive>(`/api/nrl/matches/${matchId}/live`);
}
/** Wave 3 scorers layer: per-player anytime-try-scorer chances for both
 *  clubs. Fetched once, no polling -- team lists are static once named,
 *  unlike the live score feed above. Same reasoning as getNrlLiveClient:
 *  a client island going through the /backend-api rewrite, no SSR variant. */
export async function getNrlScorersClient(matchId: number): Promise<NrlScorer[]> {
  return getJson<NrlScorer[]>(`/api/nrl/matches/${matchId}/scorers`);
}

/** State of Origin (design 2026-07-11): series view + two-segment record. */
export const getOriginSeriesServer = (season?: number) =>
  getServer<OriginSeriesResponse>(
    `/api/nrl/origin/series${season ? `?season=${season}` : ""}`, 300);
export const getOriginRecordServer = () =>
  getServer<OriginRecord>("/api/nrl/origin/record", 300);

/** Public device-level retention stats (D7/D14 cohorts since the WC26 final,
 *  see backend/app/api/retention.py). The backend already caches this for
 *  ~10 minutes, so a short ISR revalidate here just avoids hammering it. */
export const getRetentionServer = () =>
  getServer<RetentionStats>("/api/retention", 300);

/** Public share-card data for /tips/share/[league]/[matchweek]/[handle] and
 *  its opengraph-image (design doc: League Score Predictions, 2026-07-24) --
 *  league/matchweek/handle come only from the route params, never a
 *  client-supplied score. Same short 60s revalidate as getNrlTipsShareServer,
 *  for the identical pre-grading-404 reason (a crawler hitting the link
 *  between full-time and grading must not pin the 404 for the full hour a
 *  graded result's own longer-lived data would otherwise tolerate). */
export const getLeagueTipsShareServer = (league: string, matchweek: number, handle: string) =>
  getServer<LeagueTipsShareResponse>(
    `/api/leagues/${league}/tips/share/${matchweek}/${encodeURIComponent(handle)}`,
    60,
  );

/** Client-side NRL fixtures fetch — backs the /nrl/matches island's 60s
 *  refresh while a game is in its live window. */
export const getNrlMatches = () => getJson<NrlMatchesResponse>("/api/nrl/matches");
