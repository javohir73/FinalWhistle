"use client";

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type ReactNode,
} from "react";
import { getNrlLiveClient } from "@/lib/api";
import type { NrlLive, NrlMatch } from "@/lib/types";
import type { FetchState } from "@/lib/useFetch";

const POLL_MS = 30_000;
type LiveMatchState = FetchState<NrlLive> & { retry: () => void };
const LiveMatchContext = createContext<LiveMatchState | null>(null);

export function LiveMatchProvider({ match, children }: { match: NrlMatch; children: ReactNode }) {
  const finished = match.status === "finished";
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
  const terminal = useRef(initial?.status === "final");

  useEffect(() => {
    let active = true;
    let interval: ReturnType<typeof setInterval> | undefined;
    terminal.current = initial?.status === "final";

    if (initial) {
      setState({ status: "success", data: initial });
      return () => { active = false; };
    }

    setState((previous) => previous.status === "success" ? previous : { status: "loading" });

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

    load(false);
    interval = setInterval(() => load(true), POLL_MS);
    return () => {
      active = false;
      clearInterval(interval);
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
