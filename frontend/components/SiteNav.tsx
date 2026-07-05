"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BrandMark, Wordmark } from "@/components/Logo";
import { AuthButton } from "@/components/AuthButton";
import { cn } from "@/lib/utils";

/** Desktop primary nav links. `activePrefixes` assigns detail routes to their
 *  parent sections (e.g. /match/[id] belongs to Matches, /team to Home). */
interface NavLink {
  href: string;
  label: string;
  activePrefixes: string[];
}

const LINKS: NavLink[] = [
  { href: "/", label: "Home", activePrefixes: ["/team"] },
  { href: "/matches", label: "Matches", activePrefixes: ["/matches", "/match"] },
  { href: "/groups", label: "Groups", activePrefixes: [] },
  { href: "/brackets", label: "Bracket", activePrefixes: [] },
  {
    href: "/leaderboard",
    label: "You",
    activePrefixes: ["/about", "/methodology", "/privacy", "/terms", "/record"],
  },
];

function matches(pathname: string, prefixes: string[], href: string): boolean {
  if (href === "/") return pathname === "/" || prefixes.some((p) => hit(pathname, p));
  return hit(pathname, href) || prefixes.some((p) => hit(pathname, p));
}

const hit = (pathname: string, prefix: string) =>
  pathname === prefix || pathname.startsWith(prefix + "/");

/** Top bar (Daylight): brand lockup on the left, a desktop-only primary link
 *  row in the middle/right, and the account / sign-in control on the right.
 *  The link row is hidden on mobile (`hidden sm:flex`) — there the bottom tab
 *  bar handles navigation. */
export function SiteNav() {
  const pathname = usePathname();

  return (
    <header className="border-b border-border bg-background/80 backdrop-blur-xl">
      <nav className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3.5">
        <Link
          href="/"
          aria-label="FinalWhistle home"
          className="group flex shrink-0 items-center gap-2.5"
        >
          <BrandMark className="h-7 w-auto shrink-0 text-lime-deep transition group-hover:opacity-90" />
          <Wordmark className="text-lg font-extrabold" />
        </Link>

        <div className="ml-auto mr-2 hidden items-center gap-1 sm:flex">
          {LINKS.map((link) => {
            const active = matches(pathname, link.activePrefixes, link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex min-h-[40px] items-center rounded-lg px-3 py-2 text-sm transition",
                  active
                    ? "bg-win/10 font-semibold text-lime-deep"
                    : "text-muted hover:bg-surface-2 hover:text-foreground",
                )}
              >
                {link.label}
              </Link>
            );
          })}
        </div>

        <AuthButton />
      </nav>
    </header>
  );
}
