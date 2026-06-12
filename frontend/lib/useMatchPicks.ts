"use client";

import { useCallback, useEffect, useState } from "react";
import { recordEngagement } from "./engagement";

/** A user's anonymous per-match prediction: which side they think wins. */
export type Pick = "home" | "draw" | "away";
export type MatchPicks = Record<number, Pick>;

const KEY = "finalwhistle:match-picks:v1";
const EVENT = "finalwhistle:match-picks-changed";

function read(): MatchPicks {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return {};
    const p = JSON.parse(raw);
    if (p && typeof p === "object") {
      const out: MatchPicks = {};
      for (const [k, v] of Object.entries(p)) {
        const id = Number(k);
        if (Number.isFinite(id) && (v === "home" || v === "draw" || v === "away")) {
          out[id] = v;
        }
      }
      return out;
    }
  } catch {
    /* corrupt — start fresh */
  }
  return {};
}

/**
 * Local store of the user's match predictions, keyed by match id. Persisted so
 * picks survive a refresh and synced across mounted components/tabs. Anonymous —
 * no account required.
 */
export function useMatchPicks() {
  const [picks, setPicks] = useState<MatchPicks>({});
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setPicks(read());
    setHydrated(true);
    const sync = () => setPicks(read());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const setPick = useCallback((matchId: number, pick: Pick) => {
    recordEngagement("pick"); // user action — gates the install prompt
    setPicks((prev) => {
      const next = { ...prev, [matchId]: pick };
      window.localStorage.setItem(KEY, JSON.stringify(next));
      window.dispatchEvent(new Event(EVENT));
      return next;
    });
  }, []);

  return { picks, hydrated, setPick };
}
