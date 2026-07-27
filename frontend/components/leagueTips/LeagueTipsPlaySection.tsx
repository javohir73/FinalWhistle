"use client";

import { useState } from "react";
import { ClaimDeviceLeagueTips } from "@/components/leagueTips/ClaimDeviceLeagueTips";
import { LeagueSwitcher } from "@/components/leagueTips/LeagueSwitcher";
import { LeagueTipsPicker } from "@/components/leagueTips/LeagueTipsPicker";
import { LeagueYouVsAi } from "@/components/leagueTips/LeagueYouVsAi";
import { LeagueTipsLeaderboard } from "@/components/leagueTips/LeagueTipsLeaderboard";
import { ACTIVE_LEAGUES } from "@/lib/leagueConfig";

/** The league beat-the-AI loop's client half (design doc: League Score
 *  Predictions, 2026-07-24) -- league-generic port of components/nrl/
 *  NrlTipsPlaySection.tsx: predict, "you vs the AI", and the weekly/season
 *  leaderboard, all living under /tips. `league` state lives here (not one
 *  level up in app/tips/page.tsx, which stays a plain server component for
 *  its static metadata export) and flows down as a prop everywhere below;
 *  lib/leagueConfig.ts's DEFAULT_LEAGUE seeds the initial value.
 *
 *  The switcher renders when more than one league is active; fixed-league
 *  parents such as the Play hub can suppress it.
 *
 *  The matchweek shown isn't known until LeagueTipsPicker's first load
 *  resolves it server-side (there is no public tipsheet endpoint to seed it
 *  from, unlike NRL) -- the leaderboard only mounts once that's known, so it
 *  never has to guess which matchweek "current" means. Switching leagues
 *  clears it immediately so the leaderboard never flashes the old league's
 *  matchweek while the picker resolves the new one.
 *
 *  A league-scoped `key` on the picker/you-vs-ai below forces a full remount
 *  on switch -- without it, LeagueTipsPicker's internal nav state
 *  (`requested`, `current`, `boundary`) survives the prop swap, so a switch
 *  can re-request the PREVIOUS league's matchweek number and, if that 404s,
 *  fall back to showing the previous league's stale fixtures under the new
 *  league's label (Opus review: League Score Predictions Phase 2 multi-
 *  league switcher). The two keys are prefixed per-component (not just
 *  `league`) -- React reconciles siblings in ONE children array by key
 *  regardless of element type, so giving the picker and you-vs-ai the exact
 *  same key string for the same league is itself a duplicate-key collision
 *  ("Encountered two children with the same key") that corrupts, rather than
 *  fixes, the remount.
 *
 *  `showLeaderboard` and `onMatchweekResolved` (both optional) are the Play-hub
 *  hooks (Floodlight P5, p5-s4): the hub hoists this section's leaderboard into
 *  one unified, competition-filtered board, so it passes showLeaderboard={false}
 *  to suppress the in-section LeagueTipsLeaderboard and onMatchweekResolved to
 *  learn the same resolved matchweek the hoisted board needs. Both default to
 *  the shipped behavior, leaving /tips pixel-identical. */
export function LeagueTipsPlaySection({
  defaultLeague,
  showLeaderboard = true,
  showLeagueSwitcher = true,
  showClaim = true,
  onMatchweekResolved,
}: {
  defaultLeague: string;
  showLeaderboard?: boolean;
  showLeagueSwitcher?: boolean;
  showClaim?: boolean;
  onMatchweekResolved?: (matchweek: number | null) => void;
}) {
  const [league, setLeague] = useState(defaultLeague);
  const [matchweek, setMatchweek] = useState<number | null>(null);

  // Single writer for the matchweek so the hub (via onMatchweekResolved) always
  // learns exactly what the in-section leaderboard would use -- both the
  // picker's resolved number and the switch-time reset to null.
  function applyMatchweek(next: number | null) {
    setMatchweek(next);
    onMatchweekResolved?.(next);
  }

  function selectLeague(next: string) {
    setLeague(next);
    applyMatchweek(null);
  }

  return (
    <div className="mt-8 space-y-6">
      {showLeagueSwitcher && ACTIVE_LEAGUES.length > 1 && (
        <div className="flex justify-end">
          <LeagueSwitcher leagues={ACTIVE_LEAGUES} value={league} onChange={selectLeague} />
        </div>
      )}
      {showClaim && <ClaimDeviceLeagueTips />}
      <LeagueTipsPicker key={`picker-${league}`} league={league} onMatchweekChange={applyMatchweek} />
      <LeagueYouVsAi key={`you-vs-ai-${league}`} league={league} />
      {showLeaderboard && matchweek != null && (
        <LeagueTipsLeaderboard league={league} matchweek={matchweek} />
      )}
    </div>
  );
}
