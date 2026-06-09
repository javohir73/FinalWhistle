"use client";

import { useEffect, useState } from "react";
import { SignedIn, useAuth } from "@clerk/clerk-react";
import { getMyBracket } from "@/lib/auth";
import type { SavedBracket } from "@/lib/types";

function Inner() {
  const { getToken } = useAuth();
  const [bracket, setBracket] = useState<SavedBracket | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const b = await getMyBracket(await getToken());
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
  }, [getToken]);

  if (!done) return null;

  const score = bracket?.score;
  return (
    <div className="glass sticky top-20 z-10 mb-5 rounded-2xl border-win/30 bg-win/[0.05] p-4">
      {!bracket ? (
        <p className="text-sm text-muted">
          Save a bracket and join the leaderboard to get ranked.
        </p>
      ) : score?.rank ? (
        <p className="text-sm">
          <span className="font-display font-bold">You are #{score.rank}</span>{" "}
          <span className="text-muted">· {score.total_points} pts</span>
        </p>
      ) : (
        <p className="text-sm text-muted">
          You&apos;re in — ranks appear once matches start scoring.
        </p>
      )}
    </div>
  );
}

/** Signed-in user's standing. Renders nothing when signed out. */
export function MyRankCard() {
  return (
    <SignedIn>
      <Inner />
    </SignedIn>
  );
}
