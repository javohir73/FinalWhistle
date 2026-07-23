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
];

export function switchSportHref(pathname: string, target: SportId): string {
  const home = target === "nrl" ? "/nrl" : "/";
  for (const [foot, nrl] of EQUIVALENTS) {
    const [from, to] = target === "nrl" ? [foot, nrl] : [nrl, foot];
    if (pathname === from || pathname.startsWith(from + "/")) return to;
  }
  return home;
}
