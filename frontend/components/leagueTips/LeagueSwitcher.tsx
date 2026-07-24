"use client";

import { leagueLabel } from "@/lib/leagueConfig";
import { cn } from "@/lib/utils";

/** Small pill switcher for the handful of active leagues under /tips -- same
 *  visual idiom as LeagueTipsLeaderboard's Weekly|Season toggle (aria-pressed
 *  pill pair) rather than a `<select>` (reserved elsewhere for long lists,
 *  e.g. LocationPicker's timezone dropdown). LeagueTipsPlaySection only
 *  renders this when lib/leagueConfig.ts's ACTIVE_LEAGUES has more than one
 *  entry, so today's EPL-only /tips never mounts it. */
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
    <div className="flex gap-1 rounded-lg bg-surface-2 p-0.5 text-[11px] font-semibold" aria-label="League">
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
