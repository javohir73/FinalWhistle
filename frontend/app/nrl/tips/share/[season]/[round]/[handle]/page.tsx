import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getNrlTipsShareServer } from "@/lib/api";
import { APP_NAME } from "@/lib/constants";

export const revalidate = 3600;

type Params = { season: string; round: string; handle: string };

function parseIntParam(s: string): number | null {
  return /^\d+$/.test(s) ? Number(s) : null;
}

/** Public, unfakeable per-round share card (design doc: NRL Round Tips,
 *  Slice 2.5) -- every number on this page comes straight from the graded
 *  UserTip rows the leaderboard already trusts (see getNrlTipsShareServer);
 *  there is no client-supplied score anywhere in this contract. A handle
 *  with no graded tip that round -- unknown handle, never played it, or the
 *  round isn't graded yet -- all notFound() identically (see the backend's
 *  tips_share, which 404s with the same code/message in every case). */
export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const { season: seasonParam, round: roundParam, handle } = await params;
  const season = parseIntParam(seasonParam);
  const round = parseIntParam(roundParam);
  if (season == null || round == null) return { title: `NRL tips result — ${APP_NAME}` };

  const share = await getNrlTipsShareServer(season, round, handle).catch(() => null);
  if (!share) return { title: `NRL tips result — ${APP_NAME}` };

  const title = `${share.handle_display} went ${share.player_points}/${share.player_of} vs the AI — NRL Round ${round} | ${APP_NAME}`;
  const description = `${share.handle_display} scored ${share.player_points}/${share.player_of} in NRL Round ${round} (${season}) — the AI scored ${share.model_points}/${share.model_of}. Play against the AI at ${APP_NAME}.`;
  return {
    title,
    description,
    alternates: { canonical: `/nrl/tips/share/${season}/${round}/${encodeURIComponent(handle)}` },
    openGraph: { title, description },
  };
}

export default async function NrlTipsShareCardPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { season: seasonParam, round: roundParam, handle } = await params;
  const season = parseIntParam(seasonParam);
  const round = parseIntParam(roundParam);
  if (season == null || round == null) notFound();

  const share = await getNrlTipsShareServer(season, round, handle).catch(() => null);
  if (!share) notFound();

  const verdict =
    share.player_points > share.model_points
      ? `${share.handle_display} beat the AI this round`
      : share.player_points < share.model_points
        ? "The AI came out on top this round"
        : `${share.handle_display} drew with the AI this round`;

  return (
    <div className="fade-up mx-auto max-w-md space-y-6 text-center">
      <div className="glass rounded-2xl p-8">
        <p className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
          NRL Round {share.round} · {share.season}
        </p>
        <p className="mt-3 font-display text-2xl font-extrabold leading-snug tracking-tight">
          {share.handle_display} went {share.player_points}/{share.player_of} — the AI went{" "}
          {share.model_points}/{share.model_of}
        </p>
        <p className="mt-2 text-sm font-semibold text-lime-deep">{verdict}</p>
        {share.margin_note && <p className="mt-3 text-xs text-muted">{share.margin_note}</p>}
      </div>

      <Link
        href="/nrl/tips"
        className="inline-block rounded-lg bg-win px-6 py-3 text-sm font-bold text-pitch transition hover:brightness-110"
      >
        Play against the AI →
      </Link>

      <p className="text-xs leading-relaxed text-muted">{share.disclaimer}</p>
    </div>
  );
}
