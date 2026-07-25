"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NavIcon } from "@/components/NavIcon";
import { COMPETITIONS, competitionFromPathname, isCompetitionHomeHref } from "@/lib/sports";
import { useTournament } from "@/components/TournamentProvider";
import { cn } from "@/lib/utils";

function matches(pathname: string, prefixes: string[], href: string): boolean {
  // Competition home links ("/football/wc26", "/nrl") need exact-match
  // semantics — otherwise they prefix-match every sub-page of that
  // competition (e.g. "/nrl" would stay lit on "/nrl/matches") and two tabs
  // end up active at once.
  if (isCompetitionHomeHref(href)) return pathname === href || prefixes.some((p) => hit(pathname, p));
  return hit(pathname, href) || prefixes.some((p) => hit(pathname, p));
}

const hit = (pathname: string, prefix: string) =>
  pathname === prefix || pathname.startsWith(prefix + "/");

/** Mobile-only sticky bottom tab bar. Exactly five destinations — Home,
 *  Matches, Groups, Play and You — each one tap away, no overflow sheet. */
export function BottomNav() {
  const pathname = usePathname();
  const { has_brackets } = useTournament();
  // /embed/[matchId] is a standalone, partner-iframeable widget — it must not
  // carry the full site chrome.
  if (pathname === "/embed" || pathname.startsWith("/embed/")) return null;
  // Floodlight P5 folded the old mutually-exclusive Bracket/Tips slot into one
  // always-on Play tab, so this filter no longer removes anything (no navLink
  // sets requiresBrackets/requiresLeagueFormat now) -- it's kept intact so the
  // gating still works if any future tab reintroduces those flags.
  const tabs = COMPETITIONS[competitionFromPathname(pathname)].navLinks.filter(
    (tab) => (!tab.requiresBrackets || has_brackets) && (!tab.requiresLeagueFormat || !has_brackets),
  );

  return (
    <nav
      aria-label="Primary"
      className="safe-x safe-bottom fixed inset-x-0 bottom-0 z-50 border-t border-border bg-surface/90 backdrop-blur-xl sm:hidden"
    >
      <div className="mx-auto flex max-w-md items-stretch justify-around">
        {tabs.map((tab) => {
          const active = matches(pathname, tab.activePrefixes, tab.href);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex min-h-[44px] flex-1 flex-col items-center gap-1 py-2.5 text-[11px] font-medium transition",
                active ? "text-lime-deep" : "text-muted hover:text-foreground",
              )}
            >
              <NavIcon name={tab.label} active={active} className="h-[23px] w-[23px]" />
              {tab.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
