"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { getMyBracket, saveBracket, type BracketPayload } from "@/lib/session";
import type { SavedBracket } from "@/lib/types";

/** Minimal structural view of the useMyBracket() return that this hook needs. */
interface SyncableBracket {
  groupPicks: Record<number, unknown>;
  koPicks: Record<number, unknown>;
  toBracketPayload: () => BracketPayload;
  loadFromServer: (b: SavedBracket) => void;
  reset: () => void;
}

export type SyncStatus = "idle" | "saving" | "saved";

/** Which account the picks on this device belong to. Recorded whenever a
 *  signed-in user's bracket is reconciled (loaded, claimed, or saved); read on
 *  sign-in so one account's leftover local picks are never pushed into a
 *  different account on a shared device. */
const OWNER_KEY = "finalwhistle:mybracket:owner:v1";

function loadOwner(): number | null {
  try {
    const raw = window.localStorage.getItem(OWNER_KEY);
    if (!raw) return null;
    const id = Number(raw);
    return Number.isFinite(id) ? id : null;
  } catch {
    return null;
  }
}

function saveOwner(id: number): void {
  try {
    window.localStorage.setItem(OWNER_KEY, String(id));
  } catch {
    /* storage unavailable — non-fatal */
  }
}

/** Keeps a signed-in user's bracket persisted server-side and restores it across
 *  sessions/devices:
 *   - On sign-in / return: empty local picks → load the saved bracket; local
 *     picks owned by this account (or made anonymously) → keep them and push;
 *     local picks owned by a DIFFERENT account → the saved bracket wins.
 *   - While signed in, debounce-save changes so the bracket is always kept.
 *   - Pending changes are flushed BEFORE sign-out revokes the session, and on
 *     unmount (navigation) — signing out must never lose data.
 *  Anonymous users are untouched (localStorage-only, as before).
 *
 *  Sync model: `syncedKeyRef` holds the picks snapshot last known to be on the
 *  server; a save is due whenever the current snapshot differs. Saving the
 *  user's own state twice is a harmless idempotent upsert — what must never
 *  happen (and can't, via the reconcile gate) is pushing someone ELSE's picks. */
export function useBracketSync(b: SyncableBracket, ready: boolean): {
  status: SyncStatus;
  signedIn: boolean;
} {
  const { user, registerLogoutFlush } = useAuth();
  const [status, setStatus] = useState<SyncStatus>("idle");

  // Which user.id reconcile has COMPLETED for. The debounced saver stays off
  // until then, so a half-finished reconcile can never push foreign picks.
  const reconciledForRef = useRef<number | null>(null);
  // Picks snapshot last persisted to (or loaded from) the account; null = none.
  const syncedKeyRef = useRef<string | null>(null);

  const hasPicks =
    Object.keys(b.groupPicks).length > 0 || Object.keys(b.koPicks).length > 0;
  const picksKey = JSON.stringify([b.groupPicks, b.koPicks]);

  // Latest values, readable from stable callbacks without re-registering.
  const bRef = useRef(b);
  bRef.current = b;
  const hasPicksRef = useRef(hasPicks);
  hasPicksRef.current = hasPicks;
  const picksKeyRef = useRef(picksKey);
  picksKeyRef.current = picksKey;
  const userRef = useRef(user);
  userRef.current = user;

  /** Persist any unsaved changes NOW (sign-out and unmount paths). */
  const flush = useCallback(async () => {
    const u = userRef.current;
    if (!u || reconciledForRef.current !== u.id) return;
    if (!hasPicksRef.current || syncedKeyRef.current === picksKeyRef.current) return;
    const keyAtSave = picksKeyRef.current;
    try {
      await saveBracket(bRef.current.toBracketPayload());
      syncedKeyRef.current = keyAtSave;
      saveOwner(u.id);
    } catch {
      /* still unsaved — the next debounce/flush retries */
    }
  }, []);

  // Reconcile once per signed-in account (re-runs when the account changes).
  useEffect(() => {
    if (!user || !ready || reconciledForRef.current === user.id) return;
    reconciledForRef.current = null; // saver off while we decide
    syncedKeyRef.current = null;

    const owner = loadOwner();
    const foreign = owner !== null && owner !== user.id;
    if (hasPicks && !foreign) {
      // Local picks belong to this account (or were made anonymously and are
      // claimed by signing in): keep local; the saver will push them.
      saveOwner(user.id);
      reconciledForRef.current = user.id;
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const saved = await getMyBracket();
        if (cancelled) return;
        if (saved && (saved.group_picks.length || saved.knockout_picks.length)) {
          b.loadFromServer(saved);
        } else if (hasPicksRef.current) {
          // Another account's picks and nothing saved here: start clean rather
          // than inheriting someone else's bracket.
          b.reset();
        }
        // Treat the post-load state as the account's state. (If loadFromServer
        // re-rendered, the saver may echo-save the just-loaded picks once —
        // harmless idempotent write of the user's OWN data.)
        syncedKeyRef.current = picksKeyRef.current;
        saveOwner(user.id);
        reconciledForRef.current = user.id;
      } catch {
        // Offline / cold start. With foreign local picks stay safe (saver off);
        // otherwise let the user's own new picks save normally.
        if (!cancelled && !foreign) reconciledForRef.current = user.id;
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, ready]);

  // Debounced auto-save for signed-in users whenever picks drift from the last
  // synced snapshot.
  useEffect(() => {
    if (!user || !ready || reconciledForRef.current !== user.id) return;
    if (!hasPicks || syncedKeyRef.current === picksKey) return;
    setStatus("saving");
    const id = setTimeout(async () => {
      try {
        await saveBracket(bRef.current.toBracketPayload());
        syncedKeyRef.current = picksKey;
        saveOwner(user.id);
        setStatus("saved");
      } catch {
        setStatus("idle"); // still unsynced; retried on next change or flush
      }
    }, 1200);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [picksKey, user, ready]);

  // Sign-out must never lose data: flush pending changes while the session is
  // still valid (logout() awaits this before revoking the cookie).
  useEffect(() => {
    if (!user || !ready) return;
    return registerLogoutFlush(flush);
  }, [user, ready, registerLogoutFlush, flush]);

  // Same guarantee for client-side navigation: a pick made <1.2s before leaving
  // the page must not be dropped with the debounce timer.
  useEffect(() => {
    return () => {
      void flush();
    };
  }, [flush]);

  return { status, signedIn: !!user };
}
