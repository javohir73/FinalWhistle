import { Suspense } from "react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  getNrlConditionalProjectionsServer,
  getNrlLadderServer,
  getNrlMatchesServer,
} from "@/lib/api";
import { LadderTable } from "@/components/LadderTable";
import { RunHomePredictor } from "@/components/nrl/RunHomePredictor";
import { ShareButton } from "@/components/ShareButton";
import { Empty, ErrorState, Loading } from "@/components/States";

export const revalidate = 300;

export const metadata: Metadata = {
  title: "Predict the run home — NRL finals odds — FinalWhistle",
  description:
    "Force your own result on any remaining NRL fixture and watch every club's top 8, top 4 and minor premiership chances move inside the same finals simulation that powers the nightly projections.",
  alternates: { canonical: "/nrl/run-home" },
};

/** The finals-race machine (design doc: NRL Round Tips, Slice 3 "Approach C"):
 *  current ladder + remaining fixtures, with an interactive predictor letting
 *  a visitor force picks into the same Monte Carlo the nightly
 *  `nrl_projections` job runs. Server shell stays static/ISR (no searchParams
 *  read here) -- the interactive half owns the URL client-side via
 *  RunHomePredictor's router.replace, matching the /verify-email precedent
 *  for useSearchParams needing its own Suspense boundary. */
export default async function NrlRunHomePage() {
  const [ladder, fixtures] = await Promise.all([
    getNrlLadderServer().catch(() => null),
    getNrlMatchesServer().catch(() => null),
  ]);
  if (!ladder || !fixtures) notFound();

  const remaining = fixtures.rounds
    .map((r) => ({ round: r.round, matches: r.matches.filter((m) => m.status === "scheduled") }))
    .filter((r) => r.matches.length > 0);

  const baseline =
    remaining.length > 0
      ? await getNrlConditionalProjectionsServer(fixtures.season).catch(() => null)
      : null;

  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-extrabold">Predict your run home</h1>
        <ShareButton label="Share my run home" title={`FinalWhistle run home — NRL ${fixtures.season}`} />
      </div>
      <p className="mt-1 text-sm text-muted">
        Force a result on any remaining game and watch every club&apos;s top 8, top 4 and minor
        premiership chances move inside the model&apos;s own finals simulation.
      </p>

      <div className="glass mt-6 rounded-2xl p-4">
        <LadderTable rows={ladder.rows} />
      </div>

      <div className="mt-6">
        {remaining.length === 0 ? (
          <Empty label="The regular season is done — no remaining fixtures left to predict." />
        ) : baseline ? (
          <Suspense fallback={<Loading label="Loading the run-home predictor…" />}>
            <RunHomePredictor season={fixtures.season} rounds={remaining} baseline={baseline} />
          </Suspense>
        ) : (
          <ErrorState
            message="Couldn't load the run-home simulation right now."
            hint="The prediction service may be waking up — try refreshing in a moment."
          />
        )}
      </div>

      <p className="mt-6 text-center text-xs leading-relaxed text-muted">{fixtures.disclaimer}</p>
    </div>
  );
}
