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
 *  The switcher only renders when ACTIVE_LEAGUES has more than one entry --
 *  today's EPL-only config renders neither the switcher nor its wrapping row,
 *  so /tips stays pixel-for-pixel what it is today.
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
 *  fixes, the remount. */
export function LeagueTipsPlaySection({ defaultLeague }: { defaultLeague: string }) {
  const [league, setLeague] = useState(defaultLeague);
  const [matchweek, setMatchweek] = useState<number | null>(null);

  function selectLeague(next: string) {
    setLeague(next);
    setMatchweek(null);
  }

  return (
    <div className="mt-8 space-y-6">
      {ACTIVE_LEAGUES.length > 1 && (
        <div className="flex justify-end">
          <LeagueSwitcher leagues={ACTIVE_LEAGUES} value={league} onChange={selectLeague} />
        </div>
      )}
      <ClaimDeviceLeagueTips />
      <LeagueTipsPicker key={`picker-${league}`} league={league} onMatchweekChange={setMatchweek} />
      <LeagueYouVsAi key={`you-vs-ai-${league}`} league={league} />
      {matchweek != null && <LeagueTipsLeaderboard league={league} matchweek={matchweek} />}
    </div>
  );
}
