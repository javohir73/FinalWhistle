"use client";

import { useState } from "react";
import Link from "next/link";
import { useAuth } from "@/components/AuthProvider";
import { saveBracket, getMyBracket, joinLeaderboard, type BracketPayload } from "@/lib/session";
import { trackEvent } from "@/lib/analytics";
import type { SavedBracket } from "@/lib/types";

/** Order-independent fingerprint of a bracket's picks. Both the local payload
 *  and the saved bracket share these field shapes, so comparing signatures tells
 *  us whether a restore would actually overwrite different in-progress picks. */
function bracketSignature(b: {
  group_picks: { match_id: number; pick: string }[];
  knockout_picks: { match_no: number; picked_team_id: number }[];
  champion_team_id: number | null;
}): string {
  const g = [...b.group_picks]
    .sort((x, y) => x.match_id - y.match_id)
    .map((p) => `${p.match_id}:${p.pick}`)
    .join(",");
  const k = [...b.knockout_picks]
    .sort((x, y) => x.match_no - y.match_no)
    .map((p) => `${p.match_no}:${p.picked_team_id}`)
    .join(",");
  return `${g}|${k}|${b.champion_team_id ?? ""}`;
}

/** Account actions on the My Bracket page. Sign-in gates save/publish only —
 *  never playing. Anonymous players keep their bracket on this device. */
export function AccountPanel({
  getPayload,
  onRestore,
}: {
  getPayload: () => BracketPayload;
  onRestore: (b: SavedBracket) => void;
}) {
  const { user, openSignIn } = useAuth();
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showJoin, setShowJoin] = useState(false);
  const [name, setName] = useState("");
  // The saved bracket fetched by "Load saved", held pending an explicit confirm
  // because restoring it would discard different picks already made on this device.
  const [pendingRestore, setPendingRestore] = useState<SavedBracket | null>(null);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setStatus(null);
    try {
      await fn();
    } catch {
      const offline = typeof navigator !== "undefined" && !navigator.onLine;
      setStatus(
        offline
          ? "You're offline — couldn't reach the server. Your picks stay saved on this device."
          : "Something went wrong — please try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  const save = () =>
    run(async () => {
      await saveBracket(getPayload());
      trackEvent("bracket_saved");
      setStatus("Saved to your account ✓");
    });

  const load = () =>
    run(async () => {
      const saved = await getMyBracket();
      if (!saved) {
        setStatus("No saved bracket on your account yet.");
        return;
      }
      const local = getPayload();
      const localHasPicks =
        local.group_picks.length > 0 || local.knockout_picks.length > 0;
      // Only ask first when restoring would actually discard different local
      // picks; an empty or already-identical local bracket restores straight away.
      if (localHasPicks && bracketSignature(local) !== bracketSignature(saved)) {
        setPendingRestore(saved);
        return;
      }
      onRestore(saved);
      setStatus("Loaded your saved bracket.");
    });

  const confirmRestore = () => {
    if (!pendingRestore) return;
    onRestore(pendingRestore);
    setPendingRestore(null);
    setStatus("Loaded your saved bracket.");
  };

  const join = () =>
    run(async () => {
      await saveBracket(getPayload()); // publish the current bracket
      await joinLeaderboard({ display_name: name.trim() || "Player", visibility: "public" });
      trackEvent("bracket_published");
      setShowJoin(false);
      setStatus("You're on the leaderboard! 🏆");
    });

  const btn =
    "rounded-lg border border-border bg-surface px-3 py-1.5 text-sm font-medium text-foreground transition hover:bg-surface-2 disabled:opacity-50";

  return (
    <section className="glass rounded-2xl p-5">
      <h2 className="mb-2 font-display text-sm font-bold uppercase tracking-[0.2em] text-muted">
        Your account
      </h2>

      {!user ? (
        <>
          <p className="text-sm text-foreground">
            Save your bracket across devices and join the leaderboard — free, and your picks
            stay yours.
          </p>
          <div className="mt-3 flex items-center gap-3">
            <button
              type="button"
              onClick={() => openSignIn({ onSuccess: save })}
              className="rounded-lg bg-win px-4 py-2 text-sm font-bold text-pitch transition hover:brightness-110"
            >
              Save across devices →
            </button>
            <span className="text-xs text-muted">Right now it&apos;s saved on this device.</span>
          </div>
        </>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={save} disabled={busy} className={btn}>Sync now</button>
            <button type="button" onClick={load} disabled={busy} className={btn}>Restore from cloud</button>
            <button type="button" onClick={() => setShowJoin((v) => !v)} disabled={busy} className={btn}>
              Join leaderboard
            </button>
            <Link href="/leaderboard" className="text-sm font-semibold text-lime-deep underline-offset-2 hover:underline">
              View leaderboard →
            </Link>
          </div>
          {showJoin && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={40}
                placeholder="Display name (public)"
                aria-label="Leaderboard display name"
                className="rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-foreground outline-none focus:border-win"
              />
              <button type="button" onClick={join} disabled={busy || !name.trim()} className={btn}>
                Publish to leaderboard
              </button>
            </div>
          )}
        </>
      )}

      {pendingRestore && (
        <div className="mt-3 rounded-xl border border-loss/40 bg-loss/[0.06] p-3.5">
          <p className="text-sm font-medium text-foreground">
            Replace your current picks with your saved bracket? The changes you&apos;ve made on
            this device will be lost.
          </p>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={confirmRestore}
              className="rounded-lg border border-loss bg-loss/10 px-3 py-1.5 text-sm font-bold text-loss transition hover:bg-loss/15"
            >
              Replace my picks
            </button>
            <button type="button" onClick={() => setPendingRestore(null)} className={btn}>
              Keep current
            </button>
          </div>
        </div>
      )}

      {status && <p className="mt-3 text-sm font-medium text-lime-deep">{status}</p>}
    </section>
  );
}
