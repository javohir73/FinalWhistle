import Link from "next/link";
import { ClubBadge } from "@/components/ClubBadge";
import { ChanceChip } from "@/components/ChanceChip";
import { ShareButton } from "@/components/ShareButton";
import { pct } from "@/lib/format";
import { isNrlLiveNow } from "@/lib/nrlLive";
import { cn } from "@/lib/utils";
import type { NrlTipsheet, NrlTipsheetMatch } from "@/lib/types";

export function kickoffLabel(iso: string | null): string {
  if (!iso) return "TBC";
  return new Date(iso).toLocaleString("en-AU", {
    weekday: "short", hour: "numeric", minute: "2-digit",
    timeZone: "Australia/Sydney", timeZoneName: "short",
  });
}

/** Same tz/locale convention as kickoffLabel, but a date is included --
 *  unlike a kickoff (always the next occurrence of that weekday), a
 *  prediction's created_at can be days old and "Mon 9:35am" alone would be
 *  ambiguous about which Monday. */
function updatedLabel(iso: string | null): string {
  if (!iso) return "not yet frozen";
  return new Date(iso).toLocaleString("en-AU", {
    day: "numeric", month: "short", hour: "numeric", minute: "2-digit",
    timeZone: "Australia/Sydney", timeZoneName: "short",
  });
}

function pickLabel(match: NrlTipsheetMatch): string | null {
  const p = match.prediction;
  if (!p) return null;
  return p.pick === "home" ? match.home : p.pick === "away" ? match.away : "Draw";
}

/** Round tipsheet: model pick, win probability, expected margin, kickoff and
 *  venue per game; the round's biggest lock and closest call flagged; a
 *  season record strip (never accuracy without its N); last round's worst
 *  miss stated plainly when there is one. Reused by /nrl/tips (evergreen
 *  current round) and /nrl/round/[n] (permalinks) -- design doc: NRL Round
 *  Tips, Slice 1.
 *
 *  `is_shadow` flows through each prediction but, matching every other NRL
 *  page today, isn't surfaced as distinct UI -- there is nothing to mirror. */
export function TipsheetBlock({ tipsheet }: { tipsheet: NrlTipsheet }) {
  const { matches, record, worst_miss, disclaimer, season, round } = tipsheet;

  const withPick = matches.filter((m) => m.prediction != null);
  const biggestLock = withPick.length
    ? withPick.reduce((a, b) => (b.prediction!.pick_confidence > a.prediction!.pick_confidence ? b : a))
    : null;
  const closestCall = withPick.length
    ? withPick.reduce((a, b) => (b.prediction!.pick_confidence < a.prediction!.pick_confidence ? b : a))
    : null;

  return (
    <div className="space-y-5">
      <section className="glass rounded-2xl p-4">
        <div className="flex items-center justify-between gap-3">
          <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
            Model record · Round {round}
          </span>
          <ShareButton label="Screenshot this" title={`NRL Round ${round} tips — ${season}`} />
        </div>
        {record.evaluated_matches === 0 ? (
          <p className="mt-2 text-sm text-muted">
            No graded matches yet this season — the record fills in as rounds finish.
          </p>
        ) : (
          <>
            <p className="mt-2 font-display text-2xl font-extrabold tabular-nums">
              {pct(record.winner_accuracy)}{" "}
              <span className="text-sm font-medium text-muted">
                ({record.evaluated_matches} graded
                {record.winner_accuracy_ci95
                  ? ` · 95% CI ${pct(record.winner_accuracy_ci95[0])}–${pct(record.winner_accuracy_ci95[1])}`
                  : ""}
                )
              </span>
            </p>
            <p className="mt-1 text-xs text-muted">
              Log loss {record.avg_log_loss?.toFixed(3) ?? "—"} · Brier{" "}
              {record.avg_brier?.toFixed(3) ?? "—"} · Best streak {record.best_streak}
              {record.last_updated ? ` · updated ${updatedLabel(record.last_updated)}` : ""}
            </p>
          </>
        )}
        <Link href="/nrl/record" className="mt-2 inline-block text-xs font-semibold text-lime-deep">
          Full model record →
        </Link>
      </section>

      {worst_miss ? (
        <p className="rounded-2xl border border-gold/20 bg-gold/[0.04] p-4 text-sm leading-relaxed text-muted">
          {/* worst_miss is the highest-confidence wrong pick in the most
           *  recently graded round overall, not necessarily the round this
           *  page is showing (see nrl_tips.py:_worst_miss) -- the label names
           *  worst_miss.round explicitly rather than saying "last round's",
           *  which would misattribute the miss on an archived permalink. */}
          <strong className="text-foreground">Round {worst_miss.round} worst miss:</strong> picked{" "}
          {worst_miss.pick_team ?? "a draw"} ({pct(worst_miss.pick_probability)}) in {worst_miss.home} vs{" "}
          {worst_miss.away} — {worst_miss.winner_team ?? "it drew"} won {worst_miss.score_home}
          {"–"}
          {worst_miss.score_away}.
        </p>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        {matches.map((m) => (
          <TipsheetRow
            key={m.match_no}
            match={m}
            flag={m === biggestLock ? "Biggest lock" : m === closestCall && closestCall !== biggestLock ? "Closest call" : null}
          />
        ))}
      </div>

      <p className="text-center text-xs leading-relaxed text-muted">{disclaimer}</p>
    </div>
  );
}

function TipsheetRow({
  match,
  flag,
}: {
  match: NrlTipsheetMatch;
  flag: "Biggest lock" | "Closest call" | null;
}) {
  const p = match.prediction;
  const finished = match.status === "finished";
  const live = !finished && isNrlLiveNow(match);
  const hasScore = match.score_home != null && match.score_away != null;
  const pickCorrect =
    finished && p && hasScore
      ? (p.pick === "home" && match.score_home! > match.score_away!) ||
        (p.pick === "away" && match.score_away! > match.score_home!) ||
        (p.pick === "draw" && match.score_home === match.score_away)
      : null;

  return (
    <div className="glass rounded-2xl p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
          {match.venue ?? "Venue TBC"}
        </span>
        {live ? (
          <span
            className="inline-flex items-center gap-1.5 rounded-full bg-loss/15 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-loss"
            aria-label="Live"
          >
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-loss" aria-hidden />
            Live
          </span>
        ) : (
          <span
            className={cn(
              "rounded-full px-2.5 py-0.5 text-[11px] font-semibold",
              finished ? "bg-surface-2/70 text-muted" : "bg-draw/15 text-amber-ink",
            )}
          >
            {finished ? "Full time" : kickoffLabel(match.kickoff_utc)}
          </span>
        )}
      </div>

      {flag ? (
        <span className="mt-2 inline-block rounded-full bg-win/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-lime-deep">
          {flag}
        </span>
      ) : null}

      {(["home", "away"] as const).map((side) => {
        const name = side === "home" ? match.home : match.away;
        const score = side === "home" ? match.score_home : match.score_away;
        const prob = side === "home" ? p?.p_home : p?.p_away;
        const other = side === "home" ? p?.p_away : p?.p_home;
        return (
          <div key={side} className="mt-2 flex items-center gap-2.5">
            <ClubBadge name={name} />
            <span className="flex-1 font-display text-[15px] font-semibold">{name ?? "TBC"}</span>
            {finished ? (
              <span className="text-lg font-extrabold tabular-nums">{score}</span>
            ) : prob !== undefined && other !== undefined ? (
              <ChanceChip prob={prob} deltaText={null} tone={prob >= other ? "up" : "muted"} />
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

      {!p ? (
        <p className="mt-3 rounded-lg bg-surface-2/50 px-3 py-2 text-center text-xs text-muted">
          Prediction arriving before kickoff.
        </p>
      ) : finished ? (
        <p className={cn("mt-3 text-center text-xs font-semibold", pickCorrect ? "text-lime-deep" : "text-loss")}>
          <span aria-hidden>{pickCorrect ? "✓" : "✕"}</span> Picked {pickLabel(match)} ({pct(p.pick_confidence)}) —{" "}
          {pickCorrect ? "called it" : "missed it"}
        </p>
      ) : (
        <p className="mt-3 text-center text-sm font-semibold text-lime-deep">
          Pick: {pickLabel(match)} · {pct(p.pick_confidence)}
        </p>
      )}

      {p?.expected_margin != null && !finished ? (
        <div className="mt-3 flex items-center justify-between border-t border-border pt-2.5 text-xs text-muted">
          <span>Margin</span>
          <span className="rounded-lg bg-surface-2 px-2 py-0.5 font-bold tabular-nums text-foreground">
            {p.expected_margin > 0 ? "+" : ""}
            {p.expected_margin.toFixed(1)}
          </span>
        </div>
      ) : null}

      {p ? (
        <p className="mt-3 border-t border-border pt-2.5 text-xs leading-relaxed text-muted">
          Locks at kickoff · updated {updatedLabel(p.created_at)} ·{" "}
          <Link href="/nrl/record" className="font-semibold text-lime-deep">
            Full model record →
          </Link>
        </p>
      ) : null}
    </div>
  );
}
