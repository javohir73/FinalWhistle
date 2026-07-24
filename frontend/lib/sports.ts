/** Per-sport navigation config (spec 2026-07-09, Template A).
 *  Adding a sport = adding an entry here; SiteNav/BottomNav derive from it. */
export type SportId = "football" | "nrl";

export interface SportNavLink {
  href: string;
  label: string;
  activePrefixes: string[];
  /** Hidden when the active tournament has no knockout bracket (C6 — see
   *  components/TournamentProvider.tsx). Only football's Bracket tab sets this. */
  requiresBrackets?: boolean;
  /** Inverse of requiresBrackets -- hidden until the active tournament HAS no
   *  bracket (league format). Only football's Tips tab sets this: it takes
   *  the slot Bracket vacates once the season flips from WC26's knockout
   *  format to a league (design doc: League Score Predictions, 2026-07-24),
   *  so the five-destination cap (see BottomNav.tsx) is never exceeded
   *  regardless of ship order between this nav entry and that prod flip. */
  requiresLeagueFormat?: boolean;
}

export const SPORTS: Record<
  SportId,
  { id: SportId; label: string; basePath: string; navLinks: SportNavLink[] }
> = {
  football: {
    id: "football",
    label: "Football",
    basePath: "",
    navLinks: [
      { href: "/", label: "Home", activePrefixes: ["/team"] },
      { href: "/matches", label: "Matches", activePrefixes: ["/matches", "/match"] },
      { href: "/groups", label: "Groups", activePrefixes: [] },
      { href: "/brackets", label: "Bracket", activePrefixes: [], requiresBrackets: true },
      {
        href: "/leaderboard",
        label: "You",
        activePrefixes: ["/about", "/methodology", "/privacy", "/terms", "/record"],
      },
      // Fills the slot Bracket vacates once the season is league-format (see
      // requiresLeagueFormat above) -- the five-destination cap is hard, see
      // BottomNav.tsx. Mirrors NRL's own Tips slot below.
      { href: "/tips", label: "Tips", activePrefixes: [], requiresLeagueFormat: true },
    ],
  },
  nrl: {
    id: "nrl",
    label: "NRL",
    basePath: "/nrl",
    navLinks: [
      { href: "/nrl", label: "Home", activePrefixes: [] },
      { href: "/nrl/matches", label: "Matches", activePrefixes: [] },
      { href: "/nrl/ladder", label: "Ladder", activePrefixes: [] },
      { href: "/nrl/record", label: "Record", activePrefixes: [] },
      // Tips replaces the aliased-away "You"/leaderboard slot (design doc: NRL
      // Round Tips) -- the five-destination cap is hard, see BottomNav.tsx.
      // /nrl/leaderboard stays a live route (alias of /leaderboard); it's just
      // no longer one tap away from the NRL tab bar.
      { href: "/nrl/tips", label: "Tips", activePrefixes: [] },
    ],
  },
};

export function sportFromPathname(pathname: string): SportId {
  return pathname === "/nrl" || pathname.startsWith("/nrl/") ? "nrl" : "football";
}

/** Every sport's home href ("/", "/nrl", ...), derived from `basePath` so a
 *  new sport's home link never has to be special-cased in nav components.
 *  Home links need exact-match active state — unlike other nav links, they
 *  must not light up for every sub-page under the sport (see isSportHomeHref). */
const SPORT_HOME_HREFS = new Set(
  Object.values(SPORTS).map((sport) => sport.basePath || "/"),
);

export function isSportHomeHref(href: string): boolean {
  return SPORT_HOME_HREFS.has(href);
}

/** Equivalent-page mapping between sports; falls back to the sport's home. */
const EQUIVALENTS: Array<[string, string]> = [
  ["/matches", "/nrl/matches"],
  ["/leaderboard", "/nrl/leaderboard"],
  ["/tips", "/nrl/tips"],
];

export function switchSportHref(pathname: string, target: SportId): string {
  const home = target === "nrl" ? "/nrl" : "/";
  for (const [foot, nrl] of EQUIVALENTS) {
    const [from, to] = target === "nrl" ? [foot, nrl] : [nrl, foot];
    if (pathname === from || pathname.startsWith(from + "/")) return to;
  }
  return home;
}

/* ============================================================================
 * Competition registry (Floodlight P1 slice p1-s2) -- grows this file from a
 * per-SPORT nav config into a per-COMPETITION config registry: nav links,
 * terminology, standings zones, tab gating (Bracket vs Tips), and a per-comp
 * accent color all live on one Competition record. Everything above this line
 * (SportId, SPORTS, sportFromPathname, isSportHomeHref, switchSportHref) is
 * untouched -- SiteNav/BottomNav/SportSwitcher keep compiling against it
 * unchanged until slice 4 repoints them at COMPETITIONS. This slice is pure
 * plumbing: no consumer sees a behavior change.
 * ========================================================================= */

/** One entry per football league/tournament, plus NRL as its own "competition"
 *  so nav/gating code can treat all five uniformly. WC26 is the only
 *  knockout-format entry (hasBracket/hasGroups); the four league-format
 *  entries (epl/laliga/bundesliga/nrl) share the Tips slot instead. */
export type CompetitionId = "epl" | "laliga" | "bundesliga" | "wc26" | "nrl";

/** A contiguous rank band on a standings/ladder table, e.g. "positions 1-4
 *  qualify for the Champions League." Consumed by the P2 StandingsTable to
 *  paint zone stripes/labels; data only in this slice -- zones don't render
 *  anywhere yet. `tone` is a closed palette key, not a raw color, so the
 *  component owns the actual hues. */
export interface StandingsZone {
  from: number; // 1-indexed inclusive rank
  to: number; // inclusive
  label: string; // 'Champions League', 'Relegation', 'Top 8'...
  tone: "cl" | "europa" | "releg" | "promo" | "finals" | "none";
}

/** Full per-competition config. A Competition is a display+gating record, not
 *  a live data source -- fixtures/standings still come from their existing
 *  APIs, keyed by `id`/`basePath`. */
export interface Competition {
  id: CompetitionId;
  sport: SportId;
  label: string; // 'Premier League', 'World Cup 2026', 'NRL'
  shortLabel: string; // 'EPL', 'LaLiga', 'BUN', 'WC26', 'NRL' (eyebrow chip)
  basePath: string; // '/football/epl', '/football/wc26', '/nrl'
  accentVar: string; // '--accent-epl' etc. (globals.css, Floodlight P1 tokens)
  format: "league" | "knockout";
  hasBracket: boolean; // wc26 only
  hasGroups: boolean; // wc26 only
  hasTips: boolean; // league comps + wc26's Tips slot + nrl
  /** Gates the CompetitionOverlay (slice 5) and the route wrappers (slice 3)
   *  so users never land on a not-yet-built page. Mirrors ACTIVE_LEAGUES in
   *  lib/leagueConfig.ts -- epl/laliga/bundesliga are registered here (so
   *  labels/accents/zones are all correct ahead of time, same idiom as
   *  LEAGUE_LABELS there) but stay disabled until P2 actually ships their
   *  pages, exactly like ACTIVE_LEAGUES gates the /tips switcher today. */
  enabled: boolean;
  terms: { fixtures: string; standings: string }; // football vs NRL vocabulary
  zones: StandingsZone[]; // P2 StandingsTable input; [] where N/A (wc26 uses Groups instead)
  navLinks: SportNavLink[]; // per-competition tabs; reuses SportNavLink (slice 4 repoints nav consumers to read these instead of SPORTS[sport].navLinks)
}

/** Reasonable default zone banding for a 20-team European league table:
 *  1-4 Champions League, 5 Europa League, 18-20 relegation. Real qualification
 *  spots (Europa Conference, a league's exact CL count) vary by season and
 *  competition; P1 ships one shared default across epl/laliga/bundesliga and
 *  P2 can special-case it per competition once the StandingsTable consumer
 *  exists to notice the difference. */
const EUROPEAN_LEAGUE_ZONES: StandingsZone[] = [
  { from: 1, to: 4, label: "Champions League", tone: "cl" },
  { from: 5, to: 5, label: "Europa League", tone: "europa" },
  { from: 18, to: 20, label: "Relegation", tone: "releg" },
];

export const COMPETITIONS: Record<CompetitionId, Competition> = {
  epl: {
    id: "epl",
    sport: "football",
    label: "Premier League",
    shortLabel: "EPL",
    basePath: "/football/epl",
    accentVar: "--accent-epl",
    format: "league",
    hasBracket: false,
    hasGroups: false,
    hasTips: true,
    enabled: false, // P2 flips this on once its pages ship
    terms: { fixtures: "Fixtures", standings: "Standings" },
    zones: EUROPEAN_LEAGUE_ZONES,
    navLinks: [
      { href: "/football/epl", label: "Home", activePrefixes: ["/football/epl/team"] },
      {
        href: "/football/epl/fixtures",
        label: "Fixtures",
        activePrefixes: ["/football/epl/fixtures", "/football/epl/match"],
      },
      { href: "/football/epl/standings", label: "Standings", activePrefixes: ["/football/epl/standings"] },
      { href: "/tips", label: "Tips", activePrefixes: [] },
    ],
  },
  laliga: {
    id: "laliga",
    sport: "football",
    label: "La Liga",
    shortLabel: "LaLiga",
    basePath: "/football/laliga",
    accentVar: "--accent-laliga",
    format: "league",
    hasBracket: false,
    hasGroups: false,
    hasTips: true,
    enabled: false,
    terms: { fixtures: "Fixtures", standings: "Standings" },
    zones: EUROPEAN_LEAGUE_ZONES,
    navLinks: [
      { href: "/football/laliga", label: "Home", activePrefixes: ["/football/laliga/team"] },
      {
        href: "/football/laliga/fixtures",
        label: "Fixtures",
        activePrefixes: ["/football/laliga/fixtures", "/football/laliga/match"],
      },
      { href: "/football/laliga/standings", label: "Standings", activePrefixes: ["/football/laliga/standings"] },
      { href: "/tips", label: "Tips", activePrefixes: [] },
    ],
  },
  bundesliga: {
    id: "bundesliga",
    sport: "football",
    label: "Bundesliga",
    shortLabel: "BUN",
    basePath: "/football/bundesliga",
    accentVar: "--accent-bundesliga",
    format: "league",
    hasBracket: false,
    hasGroups: false,
    hasTips: true,
    enabled: false,
    terms: { fixtures: "Fixtures", standings: "Standings" },
    zones: EUROPEAN_LEAGUE_ZONES,
    navLinks: [
      { href: "/football/bundesliga", label: "Home", activePrefixes: ["/football/bundesliga/team"] },
      {
        href: "/football/bundesliga/fixtures",
        label: "Fixtures",
        activePrefixes: ["/football/bundesliga/fixtures", "/football/bundesliga/match"],
      },
      {
        href: "/football/bundesliga/standings",
        label: "Standings",
        activePrefixes: ["/football/bundesliga/standings"],
      },
      { href: "/tips", label: "Tips", activePrefixes: [] },
    ],
  },
  wc26: {
    id: "wc26",
    sport: "football",
    label: "World Cup 2026",
    shortLabel: "WC26",
    basePath: "/football/wc26",
    accentVar: "--accent-wc26",
    format: "knockout",
    hasBracket: true,
    hasGroups: true,
    hasTips: true, // its Tips slot -- see requiresLeagueFormat below
    enabled: true,
    terms: { fixtures: "Fixtures", standings: "Standings" },
    zones: [], // knockout format uses Groups, not a standings table
    navLinks: [
      { href: "/football/wc26", label: "Home", activePrefixes: ["/football/wc26/team"] },
      {
        href: "/football/wc26/fixtures",
        label: "Fixtures",
        activePrefixes: ["/football/wc26/fixtures", "/football/wc26/match"],
      },
      { href: "/football/wc26/groups", label: "Groups", activePrefixes: ["/football/wc26/groups"] },
      { href: "/football/wc26/bracket", label: "Bracket", activePrefixes: [], requiresBrackets: true },
      // Cross-competition, NOT namespaced in P1: /leaderboard stays the
      // global "You" destination (see SPORTS.football above -- same href).
      {
        href: "/leaderboard",
        label: "You",
        activePrefixes: ["/about", "/methodology", "/privacy", "/terms", "/record"],
      },
      // Cross-competition Tips stays at /tips in P1 (Play-hub merge is P5).
      // Keeps the requiresLeagueFormat gate so it and Bracket never both
      // show, driven by has_brackets at runtime exactly as today's
      // SPORTS.football.navLinks Tips entry.
      { href: "/tips", label: "Tips", activePrefixes: [], requiresLeagueFormat: true },
    ],
  },
  nrl: {
    id: "nrl",
    sport: "nrl",
    label: "NRL",
    shortLabel: "NRL",
    basePath: "/nrl",
    accentVar: "--accent-nrl",
    format: "league",
    hasBracket: false,
    hasGroups: false,
    hasTips: true,
    enabled: true,
    terms: { fixtures: "Matches", standings: "Ladder" },
    zones: [{ from: 1, to: 8, label: "Finals", tone: "finals" }],
    // Mirrors SPORTS.nrl.navLinks above unchanged (NRL keeps its own space).
    navLinks: [
      { href: "/nrl", label: "Home", activePrefixes: [] },
      { href: "/nrl/matches", label: "Matches", activePrefixes: [] },
      { href: "/nrl/ladder", label: "Ladder", activePrefixes: [] },
      { href: "/nrl/record", label: "Record", activePrefixes: [] },
      { href: "/nrl/tips", label: "Tips", activePrefixes: [] },
    ],
  },
};

/** Every competition's home href ("/football/epl", "/football/wc26", "/nrl",
 *  ...), derived from `basePath` -- mirrors SPORT_HOME_HREFS/isSportHomeHref
 *  above, but keyed off the competition registry. Home links need exact-match
 *  active state (see isSportHomeHref's doc comment); SiteNav/BottomNav use
 *  this version once their gating derives from COMPETITIONS instead of SPORTS
 *  (Floodlight P1 slice p1-s4). Missed in slice p1-s2 -- added here since this
 *  is the first slice that needs it. */
const COMPETITION_HOME_HREFS = new Set(Object.values(COMPETITIONS).map((c) => c.basePath));

export function isCompetitionHomeHref(href: string): boolean {
  return COMPETITION_HOME_HREFS.has(href);
}

/** The football default for non-namespaced/global routes ("/", "/leaderboard",
 *  "/tips", "/about", ...) that haven't been moved under a per-competition
 *  basePath yet -- today that's everything, since the route split lands in
 *  slice 3. WC26 is the obvious default: it's the only enabled knockout
 *  competition and today's un-namespaced football pages already serve it. */
export const DEFAULT_COMPETITION: CompetitionId = "wc26";

/** Resolves the active competition from a pathname. NRL is checked first
 *  (its own space, never nested under /football/); then football
 *  competitions by their /football/<comp> basePath, picking the longest
 *  matching basePath so a future prefix collision resolves to the more
 *  specific competition; anything else (including today's un-namespaced
 *  football routes) falls back to DEFAULT_COMPETITION. Kept pure -- no
 *  localStorage -- so it's safe to call during render/SSR. */
export function competitionFromPathname(pathname: string): CompetitionId {
  if (pathname === "/nrl" || pathname.startsWith("/nrl/")) return "nrl";

  const footballIds: CompetitionId[] = ["epl", "laliga", "bundesliga", "wc26"];
  let best: CompetitionId | null = null;
  for (const id of footballIds) {
    const base = COMPETITIONS[id].basePath;
    if (pathname === base || pathname.startsWith(base + "/")) {
      if (!best || base.length > COMPETITIONS[best].basePath.length) best = id;
    }
  }
  return best ?? DEFAULT_COMPETITION;
}

/** True iff `comp` is both a known CompetitionId and enabled. Used by the P1
 *  slice-3 route wrappers to notFound() disabled/unknown competitions (e.g.
 *  visiting /football/epl before P2 ships it) instead of serving a broken
 *  page. */
export function isWiredCompetition(comp: string): comp is CompetitionId {
  return comp in COMPETITIONS && COMPETITIONS[comp as CompetitionId].enabled;
}

/** Competitions for one sport, in stable display order (insertion order of
 *  COMPETITIONS above) -- reused by the CompetitionOverlay (slice 5) and the
 *  sport toggle to list "which competitions does this sport have". */
export function competitionsForSport(sport: SportId): Competition[] {
  return Object.values(COMPETITIONS).filter((c) => c.sport === sport);
}
