"use client";

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type ReactNode,
} from "react";
import { getNrlLiveClient } from "@/lib/api";
import { NRL_LIVE_WINDOW_MINUTES } from "@/lib/nrlLive";
import type { NrlLive, NrlMatch } from "@/lib/types";
import type { FetchState } from "@/lib/useFetch";

const POLL_MS = 30_000;
// Interval ticks fetch only inside this window. The backend poller writes
// NrlLiveState only during the match, so a request outside the window can
// never observe new data -- a tab parked on a fixture days out was hitting
// the Render free tier every 30s for a payload the UI discards. Lead-in
// covers the pre-kickoff strip appearing on time; the tail adds slack past
// the live window for golden point and the final-whistle write.
const POLL_LEAD_MIN = 10;
const POLL_TAIL_MIN = NRL_LIVE_WINDOW_MINUTES + 30;

function withinPollWindow(kickoffUtc: string | null, now: number = Date.now()): boolean {
  if (!kickoffUtc) return true; // undated: cannot be bounded, keep polling
  const elapsedMin = (now - new Date(kickoffUtc).getTime()) / 60_000;
  return elapsedMin >= -POLL_LEAD_MIN && elapsedMin <= POLL_TAIL_MIN;
}
type LiveMatchState = FetchState<NrlLive> & { retry: () => void };
const LiveMatchContext = createContext<LiveMatchState | null>(null);

export function LiveMatchProvider({ match, children }: { match: NrlMatch; children: ReactNode }) {
  const finished = match.status === "finished";
  // First-paint seed for a finished match: built from the core match row so
  // the hero renders a final score with no loading flash. It is a FABRICATION
  // (empty timeline, 1/0 probability) and must not be the last word -- the
  // single fetch below replaces it with the persisted closing probability and
  // the try-by-try NrlLiveEvent timeline.
  const initial = useMemo(
    () => finished && match.score_home != null && match.score_away != null
      ? {
          status: "final" as const,
          minute: 80,
          score_home: match.score_home,
          score_away: match.score_away,
          live_home_prob: match.score_home > match.score_away ? 1 : 0,
          events: [],
        }
      : undefined,
    [finished, match.score_away, match.score_home],
  );
  const [state, setState] = useState<FetchState<NrlLive>>(
    initial ? { status: "success", data: initial } : { status: "loading" },
  );
  const [attempt, setAttempt] = useState(0);
  const requestSequence = useRef(0);
  const latestApplied = useRef(0);
  const terminal = useRef(false);

  useEffect(() => {
    let active = true;
    let interval: ReturnType<typeof setInterval> | undefined;
    terminal.current = false;

    if (initial) {
      setState({ status: "success", data: initial });
    } else {
      setState((previous) => previous.status === "success" ? previous : { status: "loading" });
    }

    const load = (silent: boolean) => {
      if (terminal.current) return;
      const requestId = ++requestSequence.current;
      Promise.resolve(getNrlLiveClient(match.id))
        .then((data) => {
          if (!active || terminal.current || requestId < latestApplied.current) return;
          latestApplied.current = requestId;
          setState({ status: "success", data });
          if (data.status === "final") {
            terminal.current = true;
            if (interval) clearInterval(interval);
          }
        })
        .catch((error) => {
          if (!active || terminal.current || silent || requestId < latestApplied.current) return;
          setState({ status: "error", message: String(error) });
        });
    };

    // A finished match fetches ONCE, silently: the seed above is already on
    // screen, the persisted payload replaces it when it lands, and a failed
    // fetch keeps the seed rather than surfacing an error. No interval -- a
    // recorded result cannot change. Everything else keeps a POLL_MS interval
    // until a refresh reports final, but each tick fetches only inside the
    // poll window (see withinPollWindow) -- the interval itself keeps ticking
    // so a tab parked before kickoff still comes live on time, at the cost of
    // a clock check instead of an HTTP request.
    load(Boolean(initial));
    if (!initial) {
      interval = setInterval(() => {
        if (withinPollWindow(match.kickoff_utc)) load(true);
      }, POLL_MS);
    }
    return () => {
      active = false;
      if (interval) clearInterval(interval);
    };
  }, [attempt, initial, match.id]);

  const retry = useCallback(() => {
    if (terminal.current) return;
    setState({ status: "loading" });
    setAttempt((value) => value + 1);
  }, []);

  const value = useMemo(() => ({ ...state, retry }), [retry, state]);
  return <LiveMatchContext.Provider value={value}>{children}</LiveMatchContext.Provider>;
}

export function useLiveMatch() {
  const state = useContext(LiveMatchContext);
  if (!state) throw new Error("useLiveMatch must be used inside LiveMatchProvider");
  return state;
}
