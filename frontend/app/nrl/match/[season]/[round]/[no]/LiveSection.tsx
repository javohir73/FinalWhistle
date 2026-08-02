"use client";

/** Presentation-only live intel section backed by the match page's shared feed. */
import type { IntelSectionProps } from "./sections";
import { LiveSectionClient } from "./LiveSectionClient";
import { useLiveMatch } from "./LiveMatchProvider";

export default function LiveSection({ detail }: IntelSectionProps) {
  const state = useLiveMatch();
  if (state.status === "error") {
    return (
      <div className="glass rounded-2xl p-6 text-sm text-muted">
        Live updates are unavailable right now.
      </div>
    );
  }
  if (state.status !== "success" || state.data.status === "pre") return null;
  return (
    <LiveSectionClient
      home={detail.match.home ?? "Home"}
      away={detail.match.away ?? "Away"}
      live={state.data}
    />
  );
}
