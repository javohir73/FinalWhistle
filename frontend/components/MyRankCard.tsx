"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { getMyBracket } from "@/lib/session";
import type { SavedBracket } from "@/lib/types";

/** Signed-in user's standing on the leaderboard page. Renders nothing when
 *  signed out. */
export function MyRankCard() {
  const { user, loading } = useAuth();
  const [bracket, setBracket] = useState<SavedBracket | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!user) {
      setDone(true);
      return;
    }
    let live = true;
    setDone(false);
    (async () => {
      try {
        const b = await getMyBracket();
        if (live) setBracket(b);
      } catch {
        /* ignore */
      } finally {
        if (live) setDone(true);
      }
    })();
    return () => {
      live = false;
    };
  }, [user]);

  if (loading || !user || !done) return null;

  const score = bracket?.score;
  return (
    <div className="glass mb-5 rounded-2xl bg-win/[0.06] p-4 ring-1 ring-win/25">
      {!bracket ? (
        <p className="text-sm text-muted">
          Save a bracket and join the leaderboard to get ranked.
        </p>
      ) : score?.rank ? (
        <p className="text-sm">
          <span className="font-display font-bold text-lime-deep">You are #{score.rank}</span>{" "}
          <span className="text-muted">· {score.total_points} pts</span>
        </p>
      ) : bracket.visibility !== "public" ? (
        <p className="text-sm text-muted">
          Your bracket is private — join the leaderboard to get ranked.
        </p>
      ) : (
        <p className="text-sm text-muted">
          You&apos;re in — ranks appear once matches start scoring.
        </p>
      )}
    </div>
  );
}
