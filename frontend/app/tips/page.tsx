import type { Metadata } from "next";
import { DEFAULT_LEAGUE, leagueLabel } from "@/lib/leagueConfig";
import { LeagueTipsPlaySection } from "@/components/leagueTips/LeagueTipsPlaySection";

// Same ISR posture as /nrl/tips -- there is nothing user-specific in this
// shell (the fixture list, AI scorelines and picker all load client-side via
// LeagueTipsPicker, since /tips/mine is device-scoped and has no public
// tipsheet-only counterpart), so the revalidate here is mostly a no-op today
// but keeps this page's config consistent with the design doc's ISR bullet.
export const revalidate = 300;

export const metadata: Metadata = {
  title: "Beat the AI's scoreline — Premier League tips",
  description:
    "Predict every Premier League fixture's scoreline against the model, matchweek by matchweek, and see how you stack up on the leaderboard.",
  alternates: { canonical: "/tips" },
};

/** "Beat the AI's scoreline" (design doc: 2026-07-24-league-score-predictions
 *  -design.md) -- the football-league port of /nrl/tips. Phase 1 hardcodes
 *  the one configured league (lib/leagueConfig.ts); every component below
 *  this takes `league` as a prop, so Phase 2's league switcher only touches
 *  this file. */
export default function LeagueTipsPage() {
  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-extrabold">Beat the AI</h1>
        <span className="text-sm text-muted">{leagueLabel(DEFAULT_LEAGUE)}</span>
      </div>
      <p className="mt-1.5 text-sm text-muted">
        Predict every fixture&apos;s scoreline against the model — 5 points for an exact score, 2 for the
        right result.
      </p>

      <LeagueTipsPlaySection league={DEFAULT_LEAGUE} />
    </div>
  );
}
