"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

export type FetchState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; data: T };

/** Tiny data-fetching hook with loading/error/success states (PRD §12.x, 6.8).
 *  Pass `pollMs` to silently re-fetch on an interval (used for live scores) —
 *  refreshes data in place without flashing the loading state, and keeps the
 *  last good data if a poll fails. Pass `initial` (from a server component) to
 *  paint real content immediately with no loading flash; the hook still refreshes
 *  in the background so the data stays live.
 *
 *  The returned object also carries `retry()` — it re-runs the fetcher from a
 *  clean loading state, so `ErrorState` can offer a "Try again" when the
 *  free-tier backend cold-starts (a full page reload was the only recovery). */
export function useFetch<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  pollMs?: number,
  initial?: T,
): FetchState<T> & { retry: () => void } {
  const [state, setState] = useState<FetchState<T>>(
    initial !== undefined ? { status: "success", data: initial } : { status: "loading" },
  );
  // Bumped by retry() to force the fetch effect to run again.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    // Don't flash a skeleton over server-rendered content; refresh in place.
    setState((prev) => (prev.status === "success" ? prev : { status: "loading" }));

    const load = (silent: boolean) =>
      fetcher()
        .then((data) => active && setState({ status: "success", data }))
        .catch((err) => {
          if (!active || silent) return; // keep last good data on a failed poll
          setState({ status: "error", message: String(err) });
        });

    // Seed-silence only applies to the very first load (keep SSR content if the
    // first refresh fails). A manual retry must be able to surface a fresh error.
    const seeded = initial !== undefined && attempt === 0;
    load(seeded);
    const id = pollMs && pollMs > 0 ? setInterval(() => load(true), pollMs) : undefined;
    return () => {
      active = false;
      if (id) clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, attempt]);

  const retry = useCallback(() => {
    setState({ status: "loading" });
    setAttempt((n) => n + 1);
  }, []);

  return useMemo(() => ({ ...state, retry }), [state, retry]);
}
