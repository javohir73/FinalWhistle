"use client";

import { useCallback, useEffect, useState } from "react";

/** The country a user has chosen to follow/predict. Persisted locally so the
 *  whole flow works anonymously and survives reloads (PRD: no forced signup). */
export interface SelectedCountry {
  team_id: number;
  team: string;
  selected_at: string;
  /** True once the AI-forecast reveal animation has played for this country, so
   *  returning users skip straight to the dashboard. */
  prediction_revealed: boolean;
}

const KEY = "finalwhistle:selected-country:v1";
const EVENT = "finalwhistle:selected-country-changed";

function read(): SelectedCountry | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const p = JSON.parse(raw);
    if (p && typeof p.team_id === "number" && typeof p.team === "string") {
      return {
        team_id: p.team_id,
        team: p.team,
        selected_at: typeof p.selected_at === "string" ? p.selected_at : "",
        prediction_revealed: !!p.prediction_revealed,
      };
    }
  } catch {
    /* corrupt value — treat as no selection */
  }
  return null;
}

/**
 * Reads/writes the locally-stored country selection and keeps every mounted
 * instance (and other tabs) in sync. `hydrated` is false on the server and the
 * first client paint so the UI can avoid an SSR mismatch / flash.
 */
export function useSelectedCountry() {
  const [selection, setSelection] = useState<SelectedCountry | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setSelection(read());
    setHydrated(true);
    const sync = () => setSelection(read());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const persist = useCallback((next: SelectedCountry | null) => {
    if (next) window.localStorage.setItem(KEY, JSON.stringify(next));
    else window.localStorage.removeItem(KEY);
    window.dispatchEvent(new Event(EVENT));
    setSelection(next);
  }, []);

  /** Choose a country (resets the reveal so the forecast animation plays again). */
  const select = useCallback(
    (team_id: number, team: string) =>
      persist({
        team_id,
        team,
        // Date.now isn't available in some sandboxes; new Date() is fine in the browser.
        selected_at: new Date().toISOString(),
        prediction_revealed: false,
      }),
    [persist],
  );

  /** Mark the current country's forecast as revealed (after the animation). */
  const reveal = useCallback(() => {
    setSelection((prev) => {
      if (!prev) return prev;
      const next = { ...prev, prediction_revealed: true };
      window.localStorage.setItem(KEY, JSON.stringify(next));
      window.dispatchEvent(new Event(EVENT));
      return next;
    });
  }, []);

  /** Forget the selection entirely (back to the country chooser). */
  const clear = useCallback(() => persist(null), [persist]);

  return { selection, hydrated, select, reveal, clear };
}
