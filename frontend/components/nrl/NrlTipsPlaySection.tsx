"use client";

import { ClaimDeviceTips } from "@/components/nrl/ClaimDeviceTips";
import { PlayRound } from "@/components/nrl/PlayRound";
import { YouVsAi } from "@/components/nrl/YouVsAi";
import { NrlTipsLeaderboard } from "@/components/nrl/NrlTipsLeaderboard";

/** The beat-the-AI loop's client half (design doc: NRL Round Tips, Slice 2)
 *  -- play, "you vs the AI", and the weekly leaderboard, all "living under
 *  /nrl/tips" per the design doc (not the round permalink pages: those stay
 *  read-only history). One import keeps /nrl/tips/page.tsx's server
 *  component free of client-only concerns (device id, auth context). */
export function NrlTipsPlaySection({ season, round }: { season: number; round: number }) {
  return (
    <div className="mt-8 space-y-6">
      <ClaimDeviceTips />
      <PlayRound season={season} round={round} />
      <YouVsAi />
      <NrlTipsLeaderboard season={season} round={round} />
    </div>
  );
}
