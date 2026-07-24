import type { Metadata } from "next";
import { ACTIVE_LEAGUES, DEFAULT_LEAGUE, leagueLabel } from "@/lib/leagueConfig";
import { LeagueTipsPlaySection } from "@/components/leagueTips/LeagueTipsPlaySection";

// Same ISR posture as /nrl/tips -- there is nothing user-specific in this
// shell (the fixture list, AI scorelines and picker all load client-side via
// LeagueTipsPicker, since /tips/mine is device-scoped and has no public
// tipsheet-only counterpart), so the revalidate here is mostly a no-op today
// but keeps this page's config consistent with the design doc's ISR bullet.
export const revalidate = 300;

// Static -- Next.js can't template this per-request off a client-selected
// league (unlike the share route's generateMetadata, which has a `league`
// path param to key off). Naming the Premier League by name here is honest
// while ACTIVE_LEAGUES stays EPL-only; revisit this copy (generic wording, or
// a dynamic route) when a second league actually goes active.
export const metadata: Metadata = {
  title: "Beat the AI's scoreline — Premier League tips",
  description:
    "Predict every Premier League fixture's scoreline against the model, matchweek by matchweek, and see how you stack up on the leaderboard.",
  alternates: { canonical: "/tips" },
};

/** "Beat the AI's scoreline" (design doc: 2026-07-24-league-score-predictions
 *  -design.md) -- the football-league port of /nrl/tips. This page stays a
 *  plain server component (its static `metadata` above requires one); the
 *  league switcher itself -- and the state it drives -- lives inside
 *  LeagueTipsPlaySection, one level down, since that's the nearest common
 *  client ancestor of everything that needs to agree on which league is
 *  selected. With ACTIVE_LEAGUES at its current single entry the switcher
 *  never mounts, so the static label below is exactly what renders today. */
export default function LeagueTipsPage() {
  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-extrabold">Beat the AI</h1>
        {ACTIVE_LEAGUES.length <= 1 && (
          <span className="text-sm text-muted">{leagueLabel(DEFAULT_LEAGUE)}</span>
        )}
      </div>
      <p className="mt-1.5 text-sm text-muted">
        Predict every fixture&apos;s scoreline against the model — 5 points for an exact score, 2 for the
        right result.
      </p>

      <LeagueTipsPlaySection defaultLeague={DEFAULT_LEAGUE} />
    </div>
  );
}
