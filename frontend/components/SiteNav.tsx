"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { BrandMark, Wordmark } from "@/components/Logo";
import { cn } from "@/lib/utils";
import { recordEngagement } from "@/lib/engagement";
import { AuthButton } from "@/components/AuthButton";

const NAV = [
  { href: "/matches", label: "Matches" },
  { href: "/groups", label: "Groups" },
  { href: "/brackets", label: "Brackets" },
  { href: "/my-bracket", label: "My Bracket" },
  { href: "/leaderboard", label: "Leaderboard" },
  { href: "/about", label: "How it works" },
];

export function SiteNav() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(href + "/");

  return (
    <header className="border-b border-border/60 bg-background/70 backdrop-blur-xl">
      <nav className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3.5">
        <Link
          href="/"
          onClick={() => setOpen(false)}
          aria-label="FinalWhistle home"
          className="group flex shrink-0 items-center gap-2.5"
        >
          <BrandMark className="h-7 w-auto shrink-0 text-win transition group-hover:opacity-90" />
          <Wordmark className="text-lg font-extrabold" />
        </Link>

        <div className="flex items-center gap-2">
          {/* Desktop links */}
          <div className="hidden items-center gap-1 text-sm sm:flex">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                aria-current={isActive(n.href) ? "page" : undefined}
                className={cn(
                  "rounded-lg px-3 py-1.5 transition",
                  isActive(n.href)
                    ? "bg-surface-2/70 text-foreground"
                    : "text-muted hover:bg-surface-2/60 hover:text-foreground",
                )}
              >
                {n.label}
              </Link>
            ))}
          </div>

          <AuthButton />

          {/* Mobile hamburger */}
          <button
          type="button"
          onClick={() =>
            setOpen((v) => {
              if (!v) recordEngagement("menu-open"); // gates the install prompt
              return !v;
            })
          }
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          aria-controls="mobile-menu"
          className="grid h-9 w-9 place-items-center rounded-lg text-foreground transition hover:bg-surface-2/60 sm:hidden"
        >
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            {open ? (
              <path d="M6 6l12 12M18 6L6 18" />
            ) : (
              <path d="M4 7h16M4 12h16M4 17h16" />
            )}
          </svg>
          </button>
        </div>
      </nav>

      {/* Mobile dropdown panel */}
      {open && (
        <div id="mobile-menu" className="border-t border-border/60 bg-background/95 backdrop-blur-xl sm:hidden">
          <div className="mx-auto flex max-w-6xl flex-col px-3 py-2">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                onClick={() => setOpen(false)}
                aria-current={isActive(n.href) ? "page" : undefined}
                className={cn(
                  "rounded-lg px-3 py-2.5 text-sm transition",
                  isActive(n.href)
                    ? "bg-surface-2/70 text-foreground"
                    : "text-muted hover:bg-surface-2/60 hover:text-foreground",
                )}
              >
                {n.label}
              </Link>
            ))}
          </div>
        </div>
      )}
    </header>
  );
}
