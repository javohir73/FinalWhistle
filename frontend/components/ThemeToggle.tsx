"use client";

import { useEffect, useState } from "react";
import { applyTheme, resolveTheme, writeTheme, type Theme } from "@/lib/theme";

/** Header control for the Daylight/Floodlight switch.
 *
 *  Renders the icon for the theme it would switch TO, which is what the label
 *  promises ("Switch to light theme") — a sun while dark, a moon while light.
 *
 *  The document is already in the right theme before React runs (the boot
 *  script in app/layout.tsx), so this only mirrors that into state on mount.
 *  Until then it renders the default so server and client markup agree; the
 *  icon settles on the same tick as hydration, not after a paint.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => {
    setTheme(resolveTheme());
  }, []);

  const next: Theme = theme === "dark" ? "light" : "dark";

  return (
    <button
      type="button"
      onClick={() => {
        setTheme(next);
        writeTheme(next);
        applyTheme(next);
      }}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-muted transition hover:bg-surface-2 hover:text-foreground"
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="h-[18px] w-[18px]"
        aria-hidden="true"
      >
        {next === "light" ? (
          <>
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
          </>
        ) : (
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        )}
      </svg>
    </button>
  );
}
