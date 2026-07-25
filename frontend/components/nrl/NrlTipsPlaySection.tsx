"use client";

import { ClaimDeviceTips } from "@/components/nrl/ClaimDeviceTips";
import { PlayRound } from "@/components/nrl/PlayRound";
import { YouVsAi } from "@/components/nrl/YouVsAi";
import { NrlTipsLeaderboard } from "@/components/nrl/NrlTipsLeaderboard";

/** The beat-the-AI loop's client half (design doc: NRL Round Tips, Slice 2)
 *  -- play, "you vs the AI", and the weekly leaderboard, all "living under
 *  /nrl/tips" per the design doc (not the round permalink pages: those stay
 *  read-only history). One import keeps /nrl/tips/page.tsx's server
 *  component free of client-only concerns (device id, auth context).
 *
 *  `showLeaderboard` (default true) is the Play-hub opt-out (Floodlight P5,
 *  p5-s4): the hub hoists every section's leaderboard into one unified,
 *  competition-filtered board, so it passes false to suppress this section's
 *  own NrlTipsLeaderboard. Default true leaves /nrl/tips pixel-identical.
 *
 *  `showConfidence` (default false, p5-s5) opts each play row into the shared
 *  ConfidenceRing beside the model's call. Only the Play hub passes true; the
 *  /nrl/tips call site leaves it off, keeping that route unchanged. */
export function NrlTipsPlaySection({
  season,
  round,
  showLeaderboard = true,
  showConfidence = false,
}: {
  season: number;
  round: number;
  showLeaderboard?: boolean;
  showConfidence?: boolean;
}) {
  return (
    <div className="mt-8 space-y-6">
      <ClaimDeviceTips />
      <PlayRound season={season} round={round} showConfidence={showConfidence} />
      <YouVsAi />
      {showLeaderboard && <NrlTipsLeaderboard season={season} round={round} />}
    </div>
  );
}
