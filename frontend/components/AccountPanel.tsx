"use client";

import { useState } from "react";
import Link from "next/link";
import { SignedIn, SignedOut, SignInButton, useAuth } from "@clerk/clerk-react";
import { saveBracket, getMyBracket, joinLeaderboard, type BracketPayload } from "@/lib/auth";
import { trackEvent } from "@/lib/analytics";
import type { SavedBracket } from "@/lib/types";

/** Account actions on the My Bracket page. Only mounted when Clerk is configured
 *  (so the Clerk hooks always have a provider). Sign-in gates save/publish only —
 *  never playing. */
export function AccountPanel({
  getPayload,
  onRestore,
}: {
  getPayload: () => BracketPayload;
  onRestore: (b: SavedBracket) => void;
}) {
  const { getToken } = useAuth();
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showJoin, setShowJoin] = useState(false);
  const [name, setName] = useState("");

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setStatus(null);
    try {
      await fn();
    } catch {
      setStatus("Something went wrong — please try again.");
    } finally {
      setBusy(false);
    }
  };

  const save = () =>
    run(async () => {
      await saveBracket(await getToken(), getPayload());
      trackEvent("bracket_saved");
      setStatus("Saved to your account ✓");
    });

  const load = () =>
    run(async () => {
      const b = await getMyBracket(await getToken());
      if (b) {
        onRestore(b);
        setStatus("Loaded your saved bracket.");
      } else {
        setStatus("No saved bracket on your account yet.");
      }
    });

  const join = () =>
    run(async () => {
      const token = await getToken();
      await saveBracket(token, getPayload()); // publish the current bracket
      await joinLeaderboard(token, { display_name: name.trim() || "Player", visibility: "public" });
      trackEvent("bracket_published");
      setShowJoin(false);
      setStatus("You're on the leaderboard! 🏆");
    });

  const btn =
    "rounded-lg border border-border px-3 py-1.5 text-sm font-medium transition hover:text-foreground disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-win/50";

  return (
    <section className="glass rounded-2xl p-5">
      <h2 className="mb-2 font-display text-sm font-bold uppercase tracking-[0.2em] text-muted">
        Your account
      </h2>

      <SignedOut>
        <p className="text-sm text-foreground/90">
          Save your bracket across devices and join the leaderboard — free, and your picks
          stay yours.
        </p>
        <div className="mt-3 flex items-center gap-3">
          <SignInButton mode="modal">
            <button
              type="button"
              className="rounded-lg bg-win/15 px-4 py-2 text-sm font-semibold text-win ring-1 ring-win/30 transition hover:bg-win/25"
            >
              Save across devices →
            </button>
          </SignInButton>
          <span className="text-xs text-muted">Right now it&apos;s saved on this device.</span>
        </div>
      </SignedOut>

      <SignedIn>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={save} disabled={busy} className={btn}>Save now</button>
          <button type="button" onClick={load} disabled={busy} className={btn}>Load saved</button>
          <button type="button" onClick={() => setShowJoin((v) => !v)} disabled={busy} className={btn}>
            Join leaderboard
          </button>
          <Link href="/leaderboard" className="text-sm font-semibold text-win underline-offset-2 hover:underline">
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
              className="rounded-lg border border-border bg-surface/60 px-3 py-1.5 text-sm outline-none focus:border-win/50 focus:ring-2 focus:ring-win/20"
            />
            <button type="button" onClick={join} disabled={busy || !name.trim()} className={btn}>
              Publish to leaderboard
            </button>
          </div>
        )}
      </SignedIn>

      {status && <p className="mt-3 text-sm text-win">{status}</p>}
    </section>
  );
}
