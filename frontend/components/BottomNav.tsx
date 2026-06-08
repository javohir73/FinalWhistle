"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const ITEMS = [
  {
    href: "/",
    label: "Home",
    icon: <path d="M3 11l9-8 9 8M5 10v10h14V10" strokeLinejoin="round" strokeLinecap="round" />,
  },
  {
    href: "/matches",
    label: "Matches",
    icon: <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" />,
  },
  {
    href: "/groups",
    label: "Groups",
    icon: <path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z" strokeLinejoin="round" />,
  },
  {
    href: "/brackets",
    label: "Bracket",
    icon: <path d="M4 5h6v6M4 19h6v-6M10 8h5v8h-5M15 12h5" strokeLinejoin="round" strokeLinecap="round" />,
  },
];

/** Mobile-only sticky bottom tab bar for one-tap access to the core sections. */
export function BottomNav() {
  const pathname = usePathname();
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-50 border-t border-border/60 bg-background/90 backdrop-blur-xl sm:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="mx-auto flex max-w-md items-stretch justify-around">
        {ITEMS.map((item) => {
          const active = isActive(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex flex-1 flex-col items-center gap-1 py-2.5 text-[11px] font-medium transition",
                active ? "text-win" : "text-muted hover:text-foreground",
              )}
            >
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                {item.icon}
              </svg>
              {item.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
