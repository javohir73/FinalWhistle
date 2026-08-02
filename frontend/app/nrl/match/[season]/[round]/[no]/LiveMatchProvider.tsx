"use client";

import { createContext, useContext, type ReactNode } from "react";
import { getNrlLiveClient } from "@/lib/api";
import type { NrlLive, NrlMatch } from "@/lib/types";
import { useFetch, type FetchState } from "@/lib/useFetch";

const POLL_MS = 30_000;
type LiveMatchState = FetchState<NrlLive> & { retry: () => void };
const LiveMatchContext = createContext<LiveMatchState | null>(null);

export function LiveMatchProvider({ match, children }: { match: NrlMatch; children: ReactNode }) {
  const finished = match.status === "finished";
  const initial = finished && match.score_home != null && match.score_away != null
    ? {
        status: "final" as const,
        minute: 80,
        score_home: match.score_home,
        score_away: match.score_away,
        live_home_prob: match.score_home > match.score_away ? 1 : 0,
        events: [],
      }
    : undefined;
  const state = useFetch<NrlLive>(
    () => Promise.resolve(getNrlLiveClient(match.id)),
    [match.id],
    finished ? undefined : POLL_MS,
    initial,
  );
  return <LiveMatchContext.Provider value={state}>{children}</LiveMatchContext.Provider>;
}

export function useLiveMatch() {
  const state = useContext(LiveMatchContext);
  if (!state) throw new Error("useLiveMatch must be used inside LiveMatchProvider");
  return state;
}
