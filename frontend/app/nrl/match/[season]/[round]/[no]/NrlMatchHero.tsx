"use client";

import Link from "next/link";
import { ClubBadge } from "@/components/ClubBadge";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { pct } from "@/lib/format";
import { isNrlLiveNow } from "@/lib/nrlLive";
import type { NrlMatch } from "@/lib/types";
import { useLiveMatch } from "./LiveMatchProvider";

export function NrlMatchHero({
  match,
  home,
  away,
}: {
  match: NrlMatch;
  home: string;
  away: string;
}) {
  const state = useLiveMatch();
  const liveState = state.status === "success" ? state.data : null;
  const isFinal = liveState?.status === "final" || match.status === "finished";
  // Mutually exclusive with isFinal (a graded match row + a stale live row
  // must not stack LIVE over Full time), and bounded by the kickoff window
  // like every other NRL surface -- a poller that died mid-match leaves /live
  // answering "live" with a frozen minute indefinitely.
  const isLive = !isFinal && liveState?.status === "live" && isNrlLiveNow(match);
  const scoreHome =
    isLive || liveState?.status === "final" ? liveState.score_home : match.score_home;
  const scoreAway =
    isLive || liveState?.status === "final" ? liveState.score_away : match.score_away;
  const score = `${scoreHome ?? "–"}–${scoreAway ?? "–"}`;
  const p = match.prediction;
  const favoured = p ? (p.p_home >= p.p_away ? home : away) : null;
  const favouredProb = p ? Math.max(p.p_home, p.p_away) : null;
  // Post-match verdict: did the model's favoured side win? (A drawn game with
  // no draw lean counts as a miss, same as the football cards.)
  const called =
    isFinal && p && scoreHome != null && scoreAway != null
      ? (p.p_home > p.p_away && scoreHome > scoreAway) ||
        (p.p_away > p.p_home && scoreAway > scoreHome)
      : null;

  return (
    <section className="glass rounded-2xl p-6">
      {isLive && (
        <p className="mb-4 text-center">
          <span
            role="status"
            aria-label={
              `Live match: ${home} ${score} ${away}` +
              (liveState.minute != null ? `, ${liveState.minute}′` : "")
            }
            className="inline-flex items-center gap-1.5 rounded-full bg-loss/10 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-loss"
          >
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" aria-hidden />
            LIVE{liveState.minute != null ? ` · ${liveState.minute}′` : ""}
          </span>
        </p>
      )}
      {isFinal && (
        <p className="mb-4 text-center">
          <span className="rounded-full bg-surface-2/70 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-muted">
            Full time
          </span>
        </p>
      )}
      <div className="flex items-center justify-center gap-6">
        <TeamCol name={home} teamId={match.home_team_id ?? null} />
        <span className="font-display text-2xl font-extrabold tabular-nums text-muted">
          {isLive || isFinal ? score : "vs"}
        </span>
        <TeamCol name={away} teamId={match.away_team_id ?? null} />
      </div>

      {p && (
        <>
          {!isLive && !isFinal && favoured && (
            <p className="mt-5 text-center text-sm font-semibold text-lime-deep">
              {favoured} to win · {pct(favouredProb)}
            </p>
          )}
          {isLive && favoured && (
            <p className="mt-5 text-center text-sm font-semibold text-lime-deep">
              Pre-match model pick · {favoured} {pct(favouredProb)}
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

          {/* Shared W/D/L bar — the role="img" aria-label prints the three
              percentages (a11y floor). Two-way NRL contests keep the 3-way
              bar; the draw segment naturally renders small. */}
          <div className="mt-4">
            <ProbabilityBar
              probabilities={{ home_win: p.p_home, draw: p.p_draw, away_win: p.p_away }}
              homeLabel={home}
              awayLabel={away}
              showLabels
            />
          </div>

          {p.expected_margin != null && !isLive && !isFinal && (
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
