"use client";

import { useEffect, useState } from "react";

export type FetchState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; data: T };

/** Tiny data-fetching hook with loading/error/success states (PRD §12.x, 6.8).
 *  Pass `pollMs` to silently re-fetch on an interval (used for live scores) —
 *  refreshes data in place without flashing the loading state, and keeps the
 *  last good data if a poll fails. */
export function useFetch<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  pollMs?: number,
): FetchState<T> {
  const [state, setState] = useState<FetchState<T>>({ status: "loading" });

  useEffect(() => {
    let active = true;
    setState({ status: "loading" });

    const load = (silent: boolean) =>
      fetcher()
        .then((data) => active && setState({ status: "success", data }))
        .catch((err) => {
          if (!active || silent) return; // keep last good data on a failed poll
          setState({ status: "error", message: String(err) });
        });

    load(false);
    const id = pollMs && pollMs > 0 ? setInterval(() => load(true), pollMs) : undefined;
    return () => {
      active = false;
      if (id) clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
