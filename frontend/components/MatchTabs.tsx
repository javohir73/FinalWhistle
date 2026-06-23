"use client";

import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Match-detail tabs: "Overview" (the AI's reasoning + your pick) and "Lineups".
 *  Only the active panel is mounted, so the lineups island doesn't fetch until
 *  the Lineups tab is opened. The scoreboard lives above this, outside the tabs. */
export function MatchTabs({
  overview,
  lineups,
}: {
  overview: ReactNode;
  lineups: ReactNode;
}) {
  const [tab, setTab] = useState<"overview" | "lineups">("overview");

  const base = "flex-1 rounded-[11px] px-3 py-2 text-center text-sm font-semibold transition";
  const on = "bg-surface text-foreground shadow-[0_1px_3px_rgba(18,40,25,0.1)]";
  const off = "text-muted hover:text-foreground";

  return (
    <div className="space-y-5">
      <div role="tablist" aria-label="Match details" className="flex gap-1 rounded-[14px] bg-surface-2 p-1">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "overview"}
          onClick={() => setTab("overview")}
          className={cn(base, tab === "overview" ? on : off)}
        >
          Overview
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "lineups"}
          onClick={() => setTab("lineups")}
          className={cn(base, tab === "lineups" ? on : off)}
        >
          Lineups
        </button>
      </div>
      <div role="tabpanel">{tab === "overview" ? overview : lineups}</div>
    </div>
  );
}
