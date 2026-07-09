"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { SPORTS, sportFromPathname, switchSportHref, type SportId } from "@/lib/sports";
import { cn } from "@/lib/utils";

const ICONS: Record<SportId, React.ReactNode> = {
  football: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5l4.1 3-1.6 4.8H9.5L8 10.5z" fill="currentColor" stroke="none" />
    </>
  ),
  nrl: (
    <g transform="rotate(-38 12 12)">
      <ellipse cx="12" cy="12" rx="8.5" ry="5.2" />
      <path d="M8.5 12h7M10.3 10.5v3M12 10.5v3M13.7 10.5v3" />
    </g>
  ),
};

/** Header sport toggle (Template A). `segment` renders the desktop control,
 *  `pills` the mobile row under the header. Persists the choice in fw_sport. */
export function SportSwitcher({ variant }: { variant: "segment" | "pills" }) {
  const pathname = usePathname();
  const active = sportFromPathname(pathname);

  const remember = (id: SportId) => {
    document.cookie = `fw_sport=${id};path=/;max-age=31536000;samesite=lax`;
  };

  return (
    <div
      role="group"
      aria-label="Sport"
      className={cn(
        variant === "segment"
          ? "ml-4 hidden items-center gap-0.5 rounded-full bg-surface-2 p-1 sm:flex"
          : "flex items-center gap-1.5 px-4 pb-2 pt-2 sm:hidden",
      )}
    >
      {(Object.keys(SPORTS) as SportId[]).map((id) => {
        const on = id === active;
        return (
          <Link
            key={id}
            href={switchSportHref(pathname, id)}
            onClick={() => remember(id)}
            aria-current={on ? "true" : undefined}
            className={cn(
              "inline-flex min-h-[32px] items-center gap-1.5 rounded-full px-3 py-1 text-[13px] font-semibold transition",
              on
                ? "bg-surface text-lime-deep shadow-sm ring-1 ring-win/30"
                : "text-muted hover:text-foreground",
            )}
          >
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none"
                 stroke="currentColor" strokeWidth={1.8} aria-hidden="true">
              {ICONS[id]}
            </svg>
            {SPORTS[id].label}
          </Link>
        );
      })}
    </div>
  );
}
