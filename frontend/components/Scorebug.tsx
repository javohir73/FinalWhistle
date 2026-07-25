import Link from "next/link";
import { Flag } from "@/components/Flag";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { Eyebrow } from "@/components/Eyebrow";
import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Probabilities } from "@/lib/types";

/** TV-style broadcast scorebug for the match centre (prototype match-detail
 *  lines 211-232): a centred stack of competition eyebrow → status line →
 *  crest/score row → team names → the W/D/L bar and its printed labels, under a
 *  "floodlight" glow wash.
 *
 *  Presentational only — MatchScoreboard owns the live poll/summary state and
 *  feeds derived values in, so this same island reads identically under both the
 *  WC26 (`/match/[id]`) and per-competition football detail routes.
 *
 *  Status decides the middle: `upcoming` shows the most-likely predicted score
 *  (lime) with an amber kickoff·venue line; `live` shows the actual score with a
 *  pulsing rose LIVE clock·venue; `ft` shows the final score under a muted
 *  FULL TIME·venue. */
export function Scorebug({
  competitionLabel,
  home,
  away,
  homeTeamId,
  awayTeamId,
  status,
  liveLabel,
  statusLine,
  venue,
  score,
  predictedScore,
  probabilities,
}: {
  competitionLabel: string;
  home: string;
  away: string;
  homeTeamId?: number | null;
  awayTeamId?: number | null;
  status: "upcoming" | "live" | "ft";
  /** Live clock/phase (e.g. "63'", "HT", "PENS"); null unless live. */
  liveLabel?: string | null;
  /** Pre-match kickoff·venue line; null when unknown. */
  statusLine?: string | null;
  /** Venue, appended to the live/ft status line (the prototype keeps it under
   *  the lights after kickoff, mirroring the upcoming line's venue). */
  venue?: string | null;
  /** Actual scoreline once the match is live/finished; null before. */
  score?: string | null;
  /** Model's most-likely scoreline, shown as the upcoming centrepiece. */
  predictedScore?: string | null;
  probabilities: Probabilities;
}) {
  const upcoming = status === "upcoming";
  const { home_win, draw, away_win } = probabilities;

  return (
    <section className="relative overflow-hidden border-b border-border px-[18px] pb-4 pt-2 text-center">
      {/* The prototype's radial "under the lights" wash behind the scorebug. */}
      <div className="floodlight-glow-top pointer-events-none absolute inset-0" aria-hidden />

      <div className="relative">
        <Eyebrow tone="muted">{competitionLabel}</Eyebrow>

        {/* Status line — the middle changes voice per state, colour AND label. */}
        {status === "live" ? (
          <div className="mt-2 flex items-center justify-center gap-[7px] text-[11px] font-bold uppercase tracking-[0.14em] text-loss">
            {/* Rose dot + pulsing ring; both reduced-motion-gated in globals. */}
            <span className="status-live-dot status-live-ring h-[7px] w-[7px] rounded-full bg-current" aria-hidden />
            LIVE{liveLabel ? ` · ${liveLabel}` : ""}{venue ? ` · ${venue}` : ""}
          </div>
        ) : status === "ft" ? (
          <div className="mt-2 text-[11px] font-bold uppercase tracking-[0.14em] text-muted">
            FULL TIME{venue ? ` · ${venue}` : ""}
          </div>
        ) : (
          statusLine && (
            <div className="mt-2 text-[11px] font-bold uppercase tracking-[0.14em] text-amber-ink">
              {statusLine}
            </div>
          )
        )}

        {/* Crests + score. Live/FT centre the actual score; upcoming shows the
            model's most-likely scoreline in lime. */}
        <div className="mt-2.5 flex items-center justify-center gap-[18px]">
          <Crest team={home} teamId={homeTeamId} />
          <span
            className={cn(
              "font-display font-extrabold tracking-[-0.03em] tabular-nums",
              upcoming ? "text-[40px] text-lime-deep" : "text-[44px]",
            )}
          >
            {upcoming ? predictedScore : score}
          </span>
          <Crest team={away} teamId={awayTeamId} />
        </div>
        {upcoming && (
          <div className="mt-0.5 text-[11px] tracking-[0.1em] text-muted">MOST LIKELY SCORE</div>
        )}

        <div className="mt-1.5 flex justify-center gap-[26px] font-display text-[13px] font-bold">
          <span>{home}</span>
          <span className="text-muted">{away}</span>
        </div>

        {/* The W/D/L bar — its role="img" aria-label carries the printed %s and is
            the single accessible source of truth for the numbers below it. */}
        <div className="mt-3">
          <ProbabilityBar
            size="hero"
            showLabels={false}
            probabilities={probabilities}
            homeLabel={home}
            awayLabel={away}
          />
        </div>
        <div className="mt-[5px] flex justify-between text-[11px] font-semibold tabular-nums">
          <span className="text-lime-deep">{home} {pct(home_win)}</span>
          <span className="text-draw">Draw {pct(draw)}</span>
          <span className="text-loss">{away} {pct(away_win)}</span>
        </div>
      </div>
    </section>
  );
}

/** A crest chip, linked to the team page when we have the id (mirrors the match
 *  scoreboard's TeamHead linking). The 44px flag is itself the >=44px tap target. */
function Crest({ team, teamId }: { team: string; teamId?: number | null }) {
  const flag = <Flag team={team} size={44} />;
  if (teamId == null) return flag;
  return (
    <Link href={`/team/${teamId}`} className="inline-flex rounded-full transition hover:opacity-80">
      {flag}
    </Link>
  );
}
