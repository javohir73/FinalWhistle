import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getNrlLadderServer, getNrlMatchDetailServer, getNrlProbHistoryServer, getNrlRoundServer,
} from "@/lib/api";
import { APP_NAME } from "@/lib/constants";
import { pct } from "@/lib/format";
import { StandingsTable } from "@/components/StandingsTable";
import { ladderRowsToStandings } from "@/lib/nrlAdapters";
import { LocalKickoff } from "@/components/LocalKickoff";
import { ShareButton } from "@/components/ShareButton";
import { LiveMatchProvider } from "./LiveMatchProvider";
import { MatchIntelClient } from "./MatchIntelClient";
import { NrlMatchHero } from "./NrlMatchHero";
import type { NrlMatch } from "@/lib/types";

export const revalidate = 300;

/** NRL match detail: /nrl/match/{season}/{round}/{match_no} — the triple is the
 *  match identity (sports.py keys matches on it; there is no per-match endpoint,
 *  so the page reads the round payload and picks its match out). Mirrors the
 *  World Cup /match/[id] page, scaled to the data the NRL vertical has. */

interface RouteParams {
  season: string;
  round: string;
  no: string;
}

function parseIds(p: RouteParams): { season: number; round: number; no: number } | null {
  const int = (s: string) => (/^\d+$/.test(s) ? Number(s) : NaN);
  const season = int(p.season);
  const round = int(p.round);
  const no = int(p.no);
  if ([season, round, no].some(Number.isNaN)) return null;
  return { season, round, no };
}

async function loadMatch(
  season: number,
  round: number,
  no: number,
): Promise<{ match: NrlMatch; disclaimer: string } | null> {
  const data = await getNrlRoundServer(season, round);
  const match =
    data?.rounds.flatMap((r) => r.matches).find((m) => m.match_no === no) ?? null;
  return match && data ? { match, disclaimer: data.disclaimer } : null;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<RouteParams>;
}): Promise<Metadata> {
  const ids = parseIds(await params);
  if (!ids) return { title: `NRL match — ${APP_NAME}` };
  const found = await loadMatch(ids.season, ids.round, ids.no).catch(() => null);
  if (!found?.match.home || !found.match.away) {
    return { title: `NRL match — ${APP_NAME}` };
  }
  const { match } = found;
  const p = match.prediction;
  const title = `${match.home} vs ${match.away} — NRL prediction | ${APP_NAME}`;
  const description = p
    ? `ML model prediction for ${match.home} vs ${match.away} (NRL round ${ids.round}): ` +
      `${match.home} ${pct(p.p_home)}, draw ${pct(p.p_draw)}, ${match.away} ${pct(p.p_away)}.`
    : `NRL round ${ids.round}: ${match.home} vs ${match.away} — ML model prediction, kickoff and ladder context.`;
  return {
    title,
    description,
    alternates: { canonical: `/nrl/match/${ids.season}/${ids.round}/${ids.no}` },
    openGraph: { title, description },
  };
}

export default async function NrlMatchDetailPage({
  params,
}: {
  params: Promise<RouteParams>;
}) {
  const ids = parseIds(await params);
  if (!ids) notFound();
  const [found, ladder] = await Promise.all([
    loadMatch(ids.season, ids.round, ids.no),
    // Ladder context is secondary — a hiccup must not take down the page.
    getNrlLadderServer().catch(() => null),
  ]);
  if (!found) notFound();
  const { match, disclaimer } = found;

  // Match Intelligence sections are additive — a hiccup must not take down
  // the existing matchup/ladder content above. `match.id` comes straight out
  // of the round payload just fetched by loadMatch (NrlMatch now carries the
  // SportMatch id), so this needs no extra round lookup.
  const [detail, probHistory] = await Promise.all([
    getNrlMatchDetailServer(match.id).catch(() => null),
    getNrlProbHistoryServer(match.id).catch(() => null),
  ]);

  const home = match.home ?? "TBC";
  const away = match.away ?? "TBC";
  const p = match.prediction;
  const clubRows = (ladder?.rows ?? []).filter(
    (r) => r.name === match.home || r.name === match.away,
  );

  return (
    <LiveMatchProvider match={match}>
      <div className="fade-up mx-auto max-w-2xl space-y-6">
        <div className="flex items-center justify-between gap-3">
          <Link
            href="/nrl/matches"
            className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground"
          >
            <span aria-hidden>←</span> All fixtures
          </Link>
          <span className="font-display text-body font-semibold text-muted">
            Round {ids.round} · {ids.season}
          </span>
          <ShareButton title={`${home} vs ${away} — NRL round ${ids.round} prediction`} />
        </div>

        <LocalKickoff iso={match.kickoff_utc} venue={match.venue} />

        <NrlMatchHero match={match} home={home} away={away} />

        {/* A fixture the model hasn't frozen yet (predictions freeze in the
            lead-up to each round) — matchup renders above, never a 404. */}
        {!p && match.status !== "finished" && (
          <section className="glass rounded-2xl p-6 text-center">
            <h2 className="font-display text-base font-bold text-foreground">
              ML model prediction on the way
            </h2>
            <p className="mx-auto mt-1.5 max-w-md text-sm leading-relaxed text-muted">
              The model freezes its call for this match in the lead-up to the round.
              Check back closer to kickoff.
            </p>
          </section>
        )}

        {detail && (
          <MatchIntelClient detail={detail} probHistory={probHistory} />
        )}

        {/* Season context: the two clubs' ladder rows. */}
        {clubRows.length > 0 && (
          <section className="glass rounded-2xl p-6">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-display text-lg font-bold">Season so far</h2>
              <Link href="/nrl/ladder" className="text-xs font-semibold text-lime-deep">
                Full ladder →
              </Link>
            </div>
            <StandingsTable
              standings={ladderRowsToStandings(clubRows)}
              zones={[]}
              badge="club"
              teamBasePath="/nrl/team"
              teamHeader="Club"
              columns={["wl", "diff", "pts"]}
            />
          </section>
        )}

        <p className="text-center text-xs leading-relaxed text-muted">
          {p ? (
            <>
              Prediction frozen at kickoff · graded after full time · model {p.model_version} ·{" "}
            </>
          ) : null}
          {disclaimer}
        </p>
      </div>
    </LiveMatchProvider>
  );
}
