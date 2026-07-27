"use client";

import { leagueLabel } from "@/lib/leagueConfig";
import { cn } from "@/lib/utils";

/** Small pill switcher for the handful of active leagues under /tips -- same
 *  visual idiom as LeagueTipsLeaderboard's Weekly|Season toggle (aria-pressed
 *  pills) rather than a `<select>`. It scrolls horizontally on narrow screens. */
export function LeagueSwitcher({
  leagues,
  value,
  onChange,
}: {
  leagues: string[];
  value: string;
  onChange: (league: string) => void;
}) {
  return (
    <div className="flex max-w-full gap-1 overflow-x-auto rounded-lg bg-surface-2 p-0.5 text-[11px] font-semibold" aria-label="League">
      {leagues.map((code) => (
        <button
          key={code}
          type="button"
          onClick={() => onChange(code)}
          aria-pressed={value === code}
          className={cn("rounded-md px-2 py-1", value === code ? "bg-win text-pitch" : "text-muted")}
        >
          {leagueLabel(code)}
        </button>
      ))}
    </div>
  );
}
