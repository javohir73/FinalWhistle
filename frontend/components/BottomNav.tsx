"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

/** Tab definition. `activePrefixes` is explicit because route names don't all
 *  share their tab's prefix (e.g. /match/[id] belongs to Matches, /team to
 *  Home) — naive startsWith(href) left most detail pages with no active tab. */
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
        <rect x="3" y="5" width="18" height="16" rx="3" />
        <path d="M8 3v4M16 3v4M3 10h18" strokeLinecap="round" />
      </>
    ),
  },
  {
    href: "/groups",
    label: "Groups",
    activePrefixes: [], // href "/groups" already covers /groups and /groups/[id]
    icon: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </>
    ),
  },
  {
    href: "/brackets",
    label: "Bracket",
    activePrefixes: [], // href "/brackets" covers the section (/my-bracket now redirects here)
    icon: <path d="M4 5h6v6M4 19h6v-6M10 8h5v8h-5M15 12h5" strokeLinejoin="round" strokeLinecap="round" />,
  },
  {
    href: "/leaderboard",
    label: "You",
    // The You hub also houses the relocated info/settings pages.
    activePrefixes: ["/about", "/methodology", "/privacy", "/terms"],
    icon: (
      <>
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21c0-4 4-6 8-6s8 2 8 6" strokeLinecap="round" />
      </>
    ),
  },
];

function matches(pathname: string, prefixes: string[], href: string): boolean {
  if (href === "/") return pathname === "/" || prefixes.some((p) => hit(pathname, p));
  return hit(pathname, href) || prefixes.some((p) => hit(pathname, p));
}

const hit = (pathname: string, prefix: string) =>
  pathname === prefix || pathname.startsWith(prefix + "/");

/** Mobile-only sticky bottom tab bar. Exactly five destinations — Home,
 *  Matches, Groups, Bracket and You — each one tap away, no overflow sheet. */
export function BottomNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Primary"
      className="safe-x safe-bottom fixed inset-x-0 bottom-0 z-50 border-t border-border bg-surface/90 backdrop-blur-xl sm:hidden"
    >
      <div className="mx-auto flex max-w-md items-stretch justify-around">
        {TABS.map((tab) => {
          const active = matches(pathname, tab.activePrefixes, tab.href);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex min-h-[44px] flex-1 flex-col items-center gap-1 py-2.5 text-[10px] font-medium transition",
                active ? "text-lime-deep" : "text-muted hover:text-foreground",
              )}
            >
              <svg
                viewBox="0 0 24 24"
                className="h-[23px] w-[23px]"
                fill="none"
                stroke="currentColor"
                strokeWidth={active ? 2.4 : 2}
                aria-hidden="true"
              >
                {tab.icon}
              </svg>
              {tab.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
