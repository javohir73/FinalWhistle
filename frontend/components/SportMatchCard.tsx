import Link from "next/link";
import { ClubBadge } from "@/components/ClubBadge";
import { ChanceChip } from "@/components/ChanceChip";
import type { NrlMatch } from "@/lib/types";

function kickoffLabel(iso: string | null): string {
  if (!iso) return "TBC";
  return new Date(iso).toLocaleString("en-AU", {
    weekday: "short", hour: "numeric", minute: "2-digit",
    timeZone: "Australia/Sydney", timeZoneName: "short",
  });
}

/** NRL fixture card: club badges + market-style chance chips + W/D/L bar.
 *  Mirrors MatchCard's anatomy; the draw segment is naturally small.
 *  With `season` and `round` the card links to the match detail page — the
 *  detail URL needs the full (season, round, match_no) triple, so a fixture
 *  whose round is still TBC renders as a plain card. */
export function SportMatchCard({
  match,
  eyebrow,
  season,
  round,
}: {
  match: NrlMatch;
  eyebrow: string;
  season?: number;
  round?: number | null;
}) {
  const p = match.prediction;
  const finished = match.status === "finished";
  const href =
    season != null && round != null
      ? `/nrl/match/${season}/${round}/${match.match_no}`
      : null;
  const body = (
    <>
      <div className="flex items-center justify-between">
        <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
          {eyebrow}
        </span>
        <span className={
          finished
            ? "rounded-full bg-surface-2/70 px-2.5 py-0.5 text-[11px] font-semibold text-muted"
            : "rounded-full bg-draw/15 px-2.5 py-0.5 text-[11px] font-semibold text-amber-ink"
        }>
          {finished ? "Full time" : kickoffLabel(match.kickoff_utc)}
        </span>
      </div>

      {(["home", "away"] as const).map((side) => {
        const name = side === "home" ? match.home : match.away;
        const score = side === "home" ? match.score_home : match.score_away;
        const prob = side === "home" ? p?.p_home : p?.p_away;
        const other = side === "home" ? p?.p_away : p?.p_home;
        return (
          <div key={side} className="mt-2 flex items-center gap-2.5">
            <ClubBadge name={name} />
            <span className="flex-1 font-display text-[15px] font-semibold">
              {name ?? "TBC"}
            </span>
            {finished ? (
              <span className="text-lg font-extrabold tabular-nums">{score}</span>
            ) : prob !== undefined && other !== undefined ? (
              <ChanceChip prob={prob} deltaText={null}
                          tone={prob >= other ? "up" : "muted"} />
            ) : null}
          </div>
        );
      })}

      {p ? (
        <div className="mt-3 flex h-2 gap-0.5" aria-hidden="true">
          <i className="rounded-full bg-win" style={{ width: `${p.p_home * 100}%` }} />
          <i className="rounded-full bg-draw" style={{ width: `${p.p_draw * 100}%` }} />
          <i className="rounded-full bg-loss" style={{ width: `${p.p_away * 100}%` }} />
        </div>
      ) : null}

      {p?.expected_margin != null && !finished ? (
        <div className="mt-3 flex items-center justify-between border-t border-border pt-2.5 text-xs text-muted">
          <span>Frozen at kickoff · graded after full time</span>
          <span className="rounded-lg bg-surface-2 px-2 py-0.5 font-bold tabular-nums text-foreground">
            <span className="mr-1 font-semibold text-muted">ML model</span>
            margin {p.expected_margin > 0 ? "+" : ""}{p.expected_margin.toFixed(1)}
          </span>
        </div>
      ) : null}
    </>
  );

  return href ? (
    <Link href={href} className="card-hover glass group block rounded-2xl p-4">
      {body}
    </Link>
  ) : (
    <div className="glass rounded-2xl p-4">{body}</div>
  );
}
