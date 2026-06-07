"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { APP_NAME } from "@/lib/constants";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/matches", label: "Matches" },
  { href: "/groups", label: "Groups" },
  { href: "/brackets", label: "Brackets" },
  { href: "/about", label: "How it works" },
];

export function SiteNav() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(href + "/");

  return (
    <header className="sticky top-0 z-50 border-b border-border/60 bg-background/70 backdrop-blur-xl">
      <nav className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3.5">
        <Link
          href="/"
          onClick={() => setOpen(false)}
          className="group flex shrink-0 items-center gap-2.5"
        >
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-win/15 text-win ring-1 ring-win/30 transition group-hover:bg-win/25">
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.2">
              <path d="M12 2l3 6 6 .8-4.5 4.2 1.2 6L12 17l-5.9 2 1.2-6L3 8.8 9 8z" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="font-display text-lg font-extrabold tracking-tight">
            {APP_NAME}
          </span>
        </Link>

        {/* Desktop links */}
        <div className="hidden items-center gap-1 text-sm sm:flex">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
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

        {/* Mobile hamburger */}
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          className="grid h-9 w-9 place-items-center rounded-lg text-foreground transition hover:bg-surface-2/60 sm:hidden"
        >
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            {open ? (
              <path d="M6 6l12 12M18 6L6 18" />
            ) : (
              <path d="M4 7h16M4 12h16M4 17h16" />
            )}
          </svg>
        </button>
      </nav>

      {/* Mobile dropdown panel */}
      {open && (
        <div className="border-t border-border/60 bg-background/95 backdrop-blur-xl sm:hidden">
          <div className="mx-auto flex max-w-6xl flex-col px-3 py-2">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                onClick={() => setOpen(false)}
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
