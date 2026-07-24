import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getLeagueTipsShareServer } from "@/lib/api";
import { leagueLabel } from "@/lib/leagueConfig";
import { APP_NAME } from "@/lib/constants";

// Matches getLeagueTipsShareServer's fetch revalidate (lib/api.ts) -- kept
// short so a pre-grading 404 (see that comment) can't pin the route render
// itself for the full hour a graded result's own longer-lived data would
// otherwise tolerate.
export const revalidate = 60;

type Params = { league: string; matchweek: string; handle: string };

function parseIntParam(s: string): number | null {
  return /^\d+$/.test(s) ? Number(s) : null;
}

/** Public, unfakeable per-matchweek share card (design doc: League Score
 *  Predictions, 2026-07-24) -- league-generic port of /nrl/tips/share. Every
 *  number on this page comes straight from the graded LeagueScorePrediction
 *  rows the leaderboard already trusts (see getLeagueTipsShareServer); there
 *  is no client-supplied score anywhere in this contract. A handle with no
 *  graded prediction that matchweek -- unknown handle, never played it, or
 *  not graded yet -- all notFound() identically (the backend 404s with the
 *  same code/message in every case, by design). */
export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const { league, matchweek: matchweekParam, handle } = await params;
  const matchweek = parseIntParam(matchweekParam);
  if (matchweek == null) return { title: `${leagueLabel(league)} tips result — ${APP_NAME}` };

  const share = await getLeagueTipsShareServer(league, matchweek, handle).catch(() => null);
  if (!share) return { title: `${leagueLabel(league)} tips result — ${APP_NAME}` };

  const title = `${share.handle_display} went ${share.player_points}/${share.player_of} vs the AI — ${leagueLabel(league)} Matchweek ${matchweek} | ${APP_NAME}`;
  const description = `${share.handle_display} scored ${share.player_points}/${share.player_of} in ${leagueLabel(league)} Matchweek ${matchweek} — the AI scored ${share.model_points}/${share.model_of}. Play against the AI at ${APP_NAME}.`;
  return {
    title,
    description,
    alternates: { canonical: `/tips/share/${league}/${matchweek}/${encodeURIComponent(handle)}` },
    openGraph: { title, description },
  };
}

export default async function LeagueTipsShareCardPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { league, matchweek: matchweekParam, handle } = await params;
  const matchweek = parseIntParam(matchweekParam);
  if (matchweek == null) notFound();

  const share = await getLeagueTipsShareServer(league, matchweek, handle).catch(() => null);
  if (!share) notFound();

  // Grading runs per finished match, not per whole matchweek, so
  // matchweek_complete can be false for days while player_of/model_of are
  // only what's graded so far -- "so far" keeps the verdict honest about an
  // in-progress matchweek instead of framing it as final.
  const verdict = share.matchweek_complete
    ? share.player_points > share.model_points
      ? `${share.handle_display} beat the AI this matchweek`
      : share.player_points < share.model_points
        ? "The AI came out on top this matchweek"
        : `${share.handle_display} drew with the AI this matchweek`
    : share.player_points > share.model_points
      ? `${share.handle_display} is ahead of the AI so far this matchweek`
      : share.player_points < share.model_points
        ? "The AI is ahead so far this matchweek"
        : `${share.handle_display} is tied with the AI so far this matchweek`;

  return (
    <div className="fade-up mx-auto max-w-md space-y-6 text-center">
      <div className="glass rounded-2xl p-8">
        <p className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
          {leagueLabel(share.league)} Matchweek {share.matchweek}
        </p>
        <p className="mt-3 font-display text-2xl font-extrabold leading-snug tracking-tight">
          {share.handle_display} went {share.player_points}/{share.player_of} — the AI went{" "}
          {share.model_points}/{share.model_of}
        </p>
        <p className="mt-2 text-sm font-semibold text-lime-deep">{verdict}</p>
        {!share.matchweek_complete && (
          <p className="mt-1 text-[11px] text-muted">Matchweek still in progress — more matches to come.</p>
        )}
      </div>

      <Link
        href="/tips"
        className="inline-block rounded-lg bg-win px-6 py-3 text-sm font-bold text-pitch transition hover:brightness-110"
      >
        Play against the AI →
      </Link>

      <p className="text-xs leading-relaxed text-muted">{share.disclaimer}</p>
    </div>
  );
}
