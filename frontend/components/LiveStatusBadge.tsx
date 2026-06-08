"use client";

import { getHealth } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";

/** Small ops/status indicator: whether live in-game updates are active. Shows
 *  nothing until health loads, so it never flashes a misleading state. */
export function LiveStatusBadge() {
  const state = useFetch(getHealth, []);
  if (state.status !== "success") return null;

  const ready = state.data.live_updates === "ready";
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full chip px-2.5 py-1 text-[11px] font-semibold"
      title={ready ? "Live in-game scores are updating" : "Live updates switch on for the tournament"}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${ready ? "animate-pulse bg-loss" : "bg-muted/50"}`}
        aria-hidden
      />
      <span className={ready ? "text-foreground" : "text-muted"}>
        {ready ? "Live updates on" : "Live updates off"}
      </span>
    </span>
  );
}
