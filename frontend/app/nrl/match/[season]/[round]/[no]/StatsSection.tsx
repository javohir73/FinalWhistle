"use client";

/** Wave 2 "stats" intel section: Scoring Breakdown + Try Timeline.
 *  Self-contained client island -- fetches its own data through the
 *  /backend-api rewrite; renders a quiet placeholder until stats exist
 *  (finished + ingested matches only). The only Wave 1 file this feature
 *  touches is sections.ts (one appended array entry) -- this file and its
 *  components are new, per the extension contract. */
import { useEffect, useState } from "react";
import { CLIENT_BASE } from "@/lib/api";
import type { NrlMatchStatsResponse } from "@/lib/types";
import type { IntelSectionProps } from "./sections";
import { ScoringBreakdown } from "@/components/nrl/ScoringBreakdown";
import { TryTimeline } from "@/components/nrl/TryTimeline";

export default function StatsSection({ detail }: IntelSectionProps) {
  const matchId = detail.match.id;
  // Stats only ever exist for finished, ingested matches -- skip the request
  // entirely otherwise so an in-progress/upcoming fixture goes straight to
  // the placeholder instead of flashing a loading state for a 404 we can
  // already predict.
  const finished = detail.match.status === "finished";
  const [stats, setStats] = useState<NrlMatchStatsResponse | null | undefined>(
    finished ? undefined : null,
  );

  useEffect(() => {
    if (!finished) return;
    let cancelled = false;
    // Belt-and-braces: guard the call itself, not just the promise chain, so
    // an environment without a global `fetch` degrades to the same quiet
    // placeholder rather than throwing out of the effect.
    try {
      fetch(`${CLIENT_BASE}/api/nrl/matches/${matchId}/stats`, { cache: "no-store" })
        .then((res) => (res.ok ? res.json() : null))
        .then((body) => {
          if (!cancelled) setStats(body);
        })
        .catch(() => {
          if (!cancelled) setStats(null);
        });
    } catch {
      setStats(null);
    }
    return () => {
      cancelled = true;
    };
  }, [matchId, finished]);

  if (stats === undefined) {
    return (
      <div className="glass rounded-2xl p-6 text-sm text-muted">Loading match stats…</div>
    );
  }
  if (stats === null) {
    return (
      <div className="glass rounded-2xl p-6 text-sm text-muted">
        Team stats are published after full time.
      </div>
    );
  }
  return (
    <div className="space-y-6">
      <ScoringBreakdown stats={stats} />
      <TryTimeline
        events={stats.try_timeline}
        homeTeam={detail.match.home}
        awayTeam={detail.match.away}
      />
    </div>
  );
}
