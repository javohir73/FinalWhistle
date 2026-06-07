"use client";

import { useCallback, useEffect, useState } from "react";

const KEY = "pp:timezone";
const EVENT = "pp:timezone-changed";

export interface TzState {
  tz: string;
  confirmed: boolean;
}

/** The browser's best guess at the user's IANA timezone (no permission prompt). */
export function detectTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function read(): TzState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.tz === "string") {
      return { tz: parsed.tz, confirmed: !!parsed.confirmed };
    }
  } catch {
    /* ignore */
  }
  return null;
}

/**
 * The timezone used to display kickoff times. Auto-detected on first visit and
 * persisted once the user confirms or changes it. Synced across components/tabs.
 * `confirmed` is false until the user accepts/picks, so the UI can prompt them.
 */
export function useTimezone() {
  // Start from a deterministic default for SSR/first paint, then hydrate.
  const [state, setState] = useState<TzState>({ tz: "UTC", confirmed: true });
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const stored = read();
    setState(stored ?? { tz: detectTimezone(), confirmed: false });
    setHydrated(true);
    const sync = () => {
      const s = read();
      if (s) setState(s);
    };
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const persist = useCallback((next: TzState) => {
    window.localStorage.setItem(KEY, JSON.stringify(next));
    window.dispatchEvent(new Event(EVENT));
    setState(next);
  }, []);

  /** Choose a timezone (marks it confirmed). */
  const setTimezone = useCallback(
    (tz: string) => persist({ tz, confirmed: true }),
    [persist],
  );

  /** Accept the detected/current timezone as-is. */
  const confirm = useCallback(
    () => persist({ tz: state.tz, confirmed: true }),
    [persist, state.tz],
  );

  return { tz: state.tz, confirmed: state.confirmed, hydrated, setTimezone, confirm };
}
