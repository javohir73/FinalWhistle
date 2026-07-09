import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getNrlLadderServer, getNrlRoundServer } from "@/lib/api";
import { APP_NAME } from "@/lib/constants";
import { pct } from "@/lib/format";
import { ClubBadge } from "@/components/ClubBadge";
import { LadderTable } from "@/components/LadderTable";
import { LocalKickoff } from "@/components/LocalKickoff";
import { ShareButton } from "@/components/ShareButton";
import type { NrlMatch } from "@/lib/types";

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

  const home = match.home ?? "TBC";
  const away = match.away ?? "TBC";
  const p = match.prediction;
  const finished = match.status === "finished";
  const hasScore = match.score_home != null && match.score_away != null;
  const favoured = p ? (p.p_home >= p.p_away ? home : away) : null;
  const favouredProb = p ? Math.max(p.p_home, p.p_away) : null;
  // Post-match verdict: did the model's favoured side win? (A drawn game with
  // no draw lean counts as a miss, same as the football cards.)
  const called =
    finished && p && match.score_home != null && match.score_away != null
      ? (p.p_home > p.p_away && match.score_home > match.score_away) ||
        (p.p_away > p.p_home && match.score_away > match.score_home)
      : null;
  const clubRows = (ladder?.rows ?? []).filter(
    (r) => r.name === match.home || r.name === match.away,
  );

  return (
    <div className="fade-up mx-auto max-w-2xl space-y-6">
      <div className="flex items-center justify-between gap-3">
        <Link
          href="/nrl/matches"
          className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground"
        >
          <span aria-hidden>←</span> All fixtures
        </Link>
        <span className="font-display text-[13px] font-semibold text-muted">
          Round {ids.round} · {ids.season}
        </span>
        <ShareButton title={`${home} vs ${away} — NRL round ${ids.round} prediction`} />
      </div>

      <LocalKickoff iso={match.kickoff_utc} venue={match.venue} />

      {/* Matchup scoreboard: badges + score (or "vs"), then the AI's call. */}
      <section className="glass rounded-2xl p-6">
        {finished && (
          <p className="mb-4 text-center">
            <span className="rounded-full bg-surface-2/70 px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide text-muted">
              Full time
            </span>
          </p>
        )}
        <div className="flex items-center justify-center gap-6">
          <TeamCol name={home} teamId={match.home_team_id ?? null} />
          <span className="font-display text-2xl font-extrabold tabular-nums text-muted">
            {finished && hasScore ? `${match.score_home}–${match.score_away}` : "vs"}
          </span>
          <TeamCol name={away} teamId={match.away_team_id ?? null} />
        </div>

        {p && (
          <>
            {!finished && favoured && (
              <p className="mt-5 text-center text-sm font-semibold text-lime-deep">
                {favoured} to win · {pct(favouredProb)}
              </p>
            )}
            {called != null && (
              <p
                className={`mt-5 text-center text-xs font-semibold ${
                  called ? "text-lime-deep" : "text-loss"
                }`}
              >
                <span aria-hidden>{called ? "✓" : "✕"}</span>{" "}
                {called ? "Called it" : "Upset — we missed it"}
              </p>
            )}

            <div className="mt-4 flex h-2 gap-0.5" aria-hidden="true">
              <i className="rounded-full bg-win" style={{ width: `${p.p_home * 100}%` }} />
              <i className="rounded-full bg-draw" style={{ width: `${p.p_draw * 100}%` }} />
              <i className="rounded-full bg-loss" style={{ width: `${p.p_away * 100}%` }} />
            </div>
            <div className="mt-2 flex items-center justify-between text-xs tabular-nums text-muted">
              <span>
                {home} <strong className="font-bold text-foreground">{pct(p.p_home)}</strong>
              </span>
              <span>Draw {pct(p.p_draw)}</span>
              <span>
                {away} <strong className="font-bold text-foreground">{pct(p.p_away)}</strong>
              </span>
            </div>

            {p.expected_margin != null && !finished && (
              <p className="mt-4 text-center">
                <span className="rounded-lg bg-surface-2 px-2.5 py-1 text-xs font-bold tabular-nums text-foreground">
                  <span className="mr-1.5 font-semibold text-muted">ML model margin</span>
                  {marginLabel(p.expected_margin, home, away)}
                </span>
              </p>
            )}
          </>
        )}
      </section>

      {/* A fixture the model hasn't frozen yet (predictions freeze in the
          lead-up to each round) — matchup renders above, never a 404. */}
      {!p && !finished && (
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

      {/* Season context: the two clubs' ladder rows. */}
      {clubRows.length > 0 && (
        <section className="glass rounded-2xl p-6">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-display text-lg font-bold">Season so far</h2>
            <Link href="/nrl/ladder" className="text-xs font-semibold text-lime-deep">
              Full ladder →
            </Link>
          </div>
          <LadderTable rows={clubRows} />
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
  );
}

/** Badge + name column; links to the club profile when the id is known
 *  (an old cached payload may predate team ids — degrade to plain text). */
function TeamCol({ name, teamId }: { name: string; teamId: number | null }) {
  const inner = (
    <>
      <ClubBadge name={name} size={48} />
      <span className="font-display text-sm font-bold">{name}</span>
    </>
  );
  return teamId != null ? (
    <Link
      href={`/nrl/team/${teamId}`}
      className="flex flex-col items-center gap-2 text-center underline-offset-2 hover:underline"
    >
      {inner}
    </Link>
  ) : (
    <div className="flex flex-col items-center gap-2 text-center">{inner}</div>
  );
}

/** expected_margin is home-minus-away points; read it out as the favoured side. */
function marginLabel(margin: number, home: string, away: string): string {
  if (margin === 0) return "dead level";
  return `${margin > 0 ? home : away} by ${Math.abs(margin).toFixed(1)}`;
}
