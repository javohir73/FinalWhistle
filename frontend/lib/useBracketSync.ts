"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { getMyBracket, saveBracket, type BracketPayload } from "@/lib/session";
import type { SavedBracket } from "@/lib/types";

/** Minimal structural view of the useMyBracket() return that this hook needs. */
interface SyncableBracket {
  groupPicks: Record<number, unknown>;
  koPicks: Record<number, unknown>;
  toBracketPayload: () => BracketPayload;
  loadFromServer: (b: SavedBracket) => void;
}

export type SyncStatus = "idle" | "saving" | "saved";

/** Keeps a signed-in user's bracket persisted server-side and restores it across
 *  sessions/devices:
 *   - On sign-in / return, if there are no local picks, load the saved bracket.
 *   - While signed in, debounce-save changes so the bracket is always kept.
 *  Anonymous users are untouched (localStorage-only, as before). */
export function useBracketSync(b: SyncableBracket, ready: boolean): {
  status: SyncStatus;
  signedIn: boolean;
} {
  const { user } = useAuth();
  const [status, setStatus] = useState<SyncStatus>("idle");
  const loadedRef = useRef(false);
  const skipNextSaveRef = useRef(false);

  const hasPicks =
    Object.keys(b.groupPicks).length > 0 || Object.keys(b.koPicks).length > 0;

  // Auto-load the saved bracket once, when signed in and the page is ready — but
  // never clobber in-progress local picks (those get saved via "Save across
  // devices" on sign-in instead).
  useEffect(() => {
    if (!user || !ready || loadedRef.current) return;
    loadedRef.current = true;
    if (hasPicks) return;
    (async () => {
      try {
        const saved = await getMyBracket();
        if (saved && (saved.group_picks.length || saved.knockout_picks.length)) {
          skipNextSaveRef.current = true; // the load mutates picks; don't echo-save it
          b.loadFromServer(saved);
        }
      } catch {
        /* offline / no saved bracket — keep local */
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, ready]);

  // Debounced auto-save for signed-in users on any pick change.
  const picksKey = JSON.stringify([b.groupPicks, b.koPicks]);
  useEffect(() => {
    if (!user || !ready || !loadedRef.current) return;
    if (skipNextSaveRef.current) {
      skipNextSaveRef.current = false;
      return;
    }
    if (!hasPicks) return;
    setStatus("saving");
    const id = setTimeout(async () => {
      try {
        await saveBracket(b.toBracketPayload());
        setStatus("saved");
      } catch {
        setStatus("idle");
      }
    }, 1200);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [picksKey, user, ready]);

  return { status, signedIn: !!user };
}
