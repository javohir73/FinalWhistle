"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

/** Tab definition. `activePrefixes` is explicit because route names don't all
 *  share their tab's prefix (e.g. /match/[id] belongs to Matches, /groups to
 *  More) — naive startsWith(href) left most detail pages with no active tab. */
interface Tab {
  href: string;
  label: string;
  activePrefixes: string[];
  icon: React.ReactNode;
}

const TABS: Tab[] = [
  {
    href: "/",
    label: "Home",
    activePrefixes: ["/team"], // team profiles open from the home hub
    icon: <path d="M3 11l9-8 9 8M5 10v10h14V10" strokeLinejoin="round" strokeLinecap="round" />,
  },
  {
    href: "/matches",
    label: "Matches",
    activePrefixes: ["/matches", "/match"],
    icon: (
      <>
        <rect x="3" y="5" width="18" height="16" rx="2" />
        <path d="M8 3v4M16 3v4M3 10h18" strokeLinecap="round" />
      </>
    ),
  },
  {
    href: "/my-bracket",
    label: "My Bracket",
    activePrefixes: ["/my-bracket"],
    icon: <path d="M4 5h6v6M4 19h6v-6M10 8h5v8h-5M15 12h5" strokeLinejoin="round" strokeLinecap="round" />,
  },
  {
    href: "/leaderboard",
    label: "Leaders",
    activePrefixes: ["/leaderboard"],
    icon: <path d="M9 20v-8h6v8M3 20v-4h6v4M15 20v-6h6v6M2 20h20" strokeLinejoin="round" strokeLinecap="round" />,
  },
];

const MORE_LINKS = [
  { href: "/groups", label: "Groups" },
  { href: "/brackets", label: "AI Bracket" },
  { href: "/about", label: "How it works" },
  { href: "/methodology", label: "Methodology" },
];

const MORE_PREFIXES = MORE_LINKS.map((l) => l.href);

function matches(pathname: string, prefixes: string[], href: string): boolean {
  if (href === "/") return pathname === "/" || prefixes.some((p) => hit(pathname, p));
  return hit(pathname, href) || prefixes.some((p) => hit(pathname, p));
}

const hit = (pathname: string, prefix: string) =>
  pathname === prefix || pathname.startsWith(prefix + "/");

/** Mobile-only sticky bottom tab bar: the core loop (Home, Matches, My Bracket,
 *  Leaderboard) one tap away, everything else under More. */
export function BottomNav() {
  const pathname = usePathname();
  const [moreOpen, setMoreOpen] = useState(false);

  // Close the sheet on navigation.
  useEffect(() => {
    setMoreOpen(false);
  }, [pathname]);

  const moreActive = MORE_PREFIXES.some((p) => hit(pathname, p));

  return (
    <>
      {/* Tap-away backdrop for the More sheet */}
      {moreOpen && (
        <button
          type="button"
          aria-label="Close menu"
          onClick={() => setMoreOpen(false)}
          className="fixed inset-0 z-40 cursor-default bg-background/40 backdrop-blur-[2px] sm:hidden"
        />
      )}

      <nav
        aria-label="Primary"
        className="safe-x safe-bottom fixed inset-x-0 bottom-0 z-50 border-t border-border/60 bg-background/90 backdrop-blur-xl sm:hidden"
      >
        {/* More sheet sits on top of the bar, inside the nav for focus flow */}
        {moreOpen && (
          <div
            id="bottom-nav-more"
            className="absolute inset-x-3 bottom-full mb-2 overflow-hidden rounded-2xl border border-border/80 bg-background/95 shadow-xl backdrop-blur-xl"
          >
            {MORE_LINKS.map((l) => {
              const active = hit(pathname, l.href);
              return (
                <Link
                  key={l.href}
                  href={l.href}
                  aria-current={active ? "page" : undefined}
                  onClick={() => setMoreOpen(false)}
                  className={cn(
                    "block border-b border-border/40 px-4 py-3 text-sm font-medium last:border-b-0",
                    active ? "text-win" : "text-foreground hover:bg-surface-2/60",
                  )}
                >
                  {l.label}
                </Link>
              );
            })}
          </div>
        )}

        <div className="mx-auto flex max-w-md items-stretch justify-around">
          {TABS.map((tab) => {
            const active = !moreOpen && matches(pathname, tab.activePrefixes, tab.href);
            return (
              <Link
                key={tab.href}
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex flex-1 flex-col items-center gap-1 py-2.5 text-[10px] font-medium transition",
                  active ? "text-win" : "text-muted hover:text-foreground",
                )}
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  {tab.icon}
                </svg>
                {tab.label}
              </Link>
            );
          })}
          <button
            type="button"
            onClick={() => setMoreOpen((v) => !v)}
            aria-expanded={moreOpen}
            aria-controls="bottom-nav-more"
            className={cn(
              "flex flex-1 flex-col items-center gap-1 py-2.5 text-[10px] font-medium transition",
              moreOpen || moreActive ? "text-win" : "text-muted hover:text-foreground",
            )}
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <circle cx="5" cy="12" r="1.2" />
              <circle cx="12" cy="12" r="1.2" />
              <circle cx="19" cy="12" r="1.2" />
            </svg>
            More
          </button>
        </div>
      </nav>
    </>
  );
}
