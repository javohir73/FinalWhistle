"use client";

import Link from "next/link";
import { Flag } from "@/components/Flag";
import type { Pick } from "@/lib/useMatchPicks";
import type { MatchSummary } from "@/lib/types";
import { kickoffTime, dayHeading, tzAbbrev } from "@/lib/datetime";
import { liveLabel } from "@/lib/liveLabel";
import { cn } from "@/lib/utils";

type Outcome = "home" | "draw" | "away";

function argmax(p: { home_win: number; draw: number; away_win: number }): Outcome {
  const entries: [Outcome, number][] = [
    ["home", p.home_win],
    ["draw", p.draw],
    ["away", p.away_win],
  ];
  return entries.sort((a, b) => b[1] - a[1])[0][0];
}

/** A short, human read on how the user's pick lines up with the model. */
function verdict(pick: Outcome, p: { home_win: number; draw: number; away_win: number }) {
  const ai = argmax(p);
  if (pick === ai) return { label: "You agree with the AI", tone: "win" as const };

  const vals = [p.home_win, p.draw, p.away_win].sort((a, b) => b - a);
  const picked = pick === "home" ? p.home_win : pick === "away" ? p.away_win : p.draw;
  if (picked <= vals[2] + 1e-9) return { label: "You’re calling an upset", tone: "loss" as const };
  if (vals[0] - vals[1] < 0.1) return { label: "The model thinks this is close", tone: "draw" as const };
  return { label: "You’re backing the bolder choice", tone: "draw" as const };
}

const TONE: Record<"win" | "draw" | "loss", string> = {
  win: "border-win/40 bg-win/10 text-win",
  draw: "border-draw/40 bg-draw/10 text-draw",
  loss: "border-loss/40 bg-loss/10 text-loss",
};

function Bar({ label, value, highlight }: { label: string; value: number; highlight?: "ai" | "you" | "both" }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[11px]">
        <span className="flex items-center gap-1.5 font-medium text-foreground">
          {label}
          {highlight && (
            <span className="rounded bg-surface-2 px-1 text-[9px] font-bold uppercase tracking-wide text-muted">
              {highlight === "both" ? "You · AI" : highlight === "ai" ? "AI" : "You"}
            </span>
          )}
        </span>
        <span className="tabular-nums text-muted">{Math.round(value * 100)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-surface-2">
        <div
          className={cn("h-full rounded-full transition-[width] duration-700 ease-out", highlight ? "bg-win" : "bg-win/30")}
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </div>
    </div>
  );
}

/**
 * One upcoming fixture for the followed country: pick the winner, then see an
 * animated comparison of your call against the AI's lean. Anonymous + local.
 */
export function UserPredictionCard({
  match,
  country,
  pick,
  onPick,
  tz,
}: {
  match: MatchSummary;
  country: string;
  pick: Pick | undefined;
  onPick: (pick: Pick) => void;
  tz: string;
}) {
  const countryIsHome = match.teams.home === country;
  const opponent = countryIsHome ? match.teams.away : match.teams.home;
  const countrySide: Outcome = countryIsHome ? "home" : "away";
  const oppSide: Outcome = countryIsHome ? "away" : "home";
  const p = match.probabilities;

  const options: { side: Outcome; label: string }[] = [
    { side: countrySide, label: country },
    { side: "draw", label: "Draw" },
    { side: oppSide, label: opponent },
  ];

  const aiPick = p ? argmax(p) : null;
  const labelFor = (s: Outcome) =>
    s === "home" ? match.teams.home : s === "away" ? match.teams.away : "Draw";

  const live = match.status === "in_play";
  const finished = match.status === "finished";
  const hasScore = match.score_home != null && match.score_away != null;

  return (
    <div
      className={cn(
        "rounded-2xl border bg-surface/50 p-4",
        live ? "border-loss/40 ring-1 ring-loss/30" : "border-border",
      )}
    >
      {/* Matchup header — live/final score shown in the middle when available */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Flag team={match.teams.home} size={24} />
          <span className="truncate text-sm font-semibold">{match.teams.home}</span>
        </div>
        {(live || finished) && hasScore ? (
          <span className="flex shrink-0 flex-col items-center">
            <span className="font-display text-lg font-extrabold leading-none tabular-nums">
              {match.score_home}
              <span className="px-1 text-muted">–</span>
              {match.score_away}
            </span>
            {live ? (
              <span
                className="mt-1 inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide text-loss"
                aria-label={`Live, ${liveLabel(match)}`}
              >
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-loss" aria-hidden />
                {liveLabel(match)}
              </span>
            ) : (
              <span className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-muted">FT</span>
            )}
          </span>
        ) : (
          <span className="shrink-0 text-xs font-bold text-muted">vs</span>
        )}
        <div className="flex min-w-0 flex-1 items-center justify-end gap-2">
          <span className="truncate text-sm font-semibold">{match.teams.away}</span>
          <Flag team={match.teams.away} size={24} />
        </div>
      </div>

      <div className="mt-1.5 flex items-center justify-center gap-1.5 text-[11px] text-muted">
        {/* match.group is already "Group A" from the API — no extra prefix */}
        {match.group && <span>{match.group}</span>}
        {/* Live/FT status sits under the score above; here we only add the
            kickoff for upcoming fixtures. */}
        {!live && !finished &&
          (match.kickoff_utc ? (
            <>
              {match.group && <span aria-hidden>·</span>}
              <span>
                {dayHeading(match.kickoff_utc, tz)} · {kickoffTime(match.kickoff_utc, tz)}{" "}
                {tzAbbrev(match.kickoff_utc, tz)}
              </span>
            </>
          ) : (
            <>
              {match.group && <span aria-hidden>·</span>}
              <span>Date to be confirmed</span>
            </>
          ))}
      </div>

      {/* Pick buttons */}
      <div className="mt-3.5 grid grid-cols-3 gap-2" role="group" aria-label={`Your prediction for ${country} vs ${opponent}`}>
        {options.map((o) => {
          const active = pick === o.side;
          return (
            <button
              key={o.side}
              type="button"
              aria-pressed={active}
              onClick={() => onPick(o.side)}
              className={cn(
                "truncate rounded-lg border px-2 py-2 text-xs font-semibold transition",
                active
                  ? "border-win/60 bg-win/15 text-foreground"
                  : "border-border bg-surface-2/50 text-muted hover:border-win/40 hover:text-foreground",
              )}
            >
              {o.label}
            </button>
          );
        })}
      </div>

      {/* Comparison (after a pick) */}
      {pick && p ? (
        <div className="mt-4 space-y-3 border-t border-border/60 pt-4">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="text-muted">
              You picked{" "}
              <span className="font-semibold text-foreground">
                {pick === "draw" ? "a draw" : labelFor(pick)}
              </span>
              {aiPick && (
                <>
                  {" · AI leans "}
                  <span className="font-semibold text-foreground">
                    {aiPick === "draw" ? "a draw" : labelFor(aiPick)}
                  </span>
                </>
              )}
            </span>
            {(() => {
              const v = verdict(pick, p);
              return (
                <span className={cn("rounded-full border px-2.5 py-0.5 text-[11px] font-semibold", TONE[v.tone])}>
                  {v.label}
                </span>
              );
            })()}
          </div>
          <div className="space-y-2">
            <Bar
              label={match.teams.home}
              value={p.home_win}
              highlight={hi("home", pick, aiPick)}
            />
            <Bar label="Draw" value={p.draw} highlight={hi("draw", pick, aiPick)} />
            <Bar
              label={match.teams.away}
              value={p.away_win}
              highlight={hi("away", pick, aiPick)}
            />
          </div>
          <Link
            href={`/match/${match.match_id}`}
            className="inline-block text-[11px] font-medium text-win underline-offset-2 hover:underline"
          >
            See full match analysis →
          </Link>
        </div>
      ) : pick && !p ? (
        <p className="mt-3 border-t border-border/60 pt-3 text-center text-xs text-muted">
          AI forecast for this fixture is coming soon.
        </p>
      ) : null}
    </div>
  );
}

/** Which marker (if any) a given outcome bar should carry. */
function hi(side: Outcome, pick: Outcome, ai: Outcome | null): "ai" | "you" | "both" | undefined {
  const isYou = side === pick;
  const isAi = side === ai;
  if (isYou && isAi) return "both";
  if (isAi) return "ai";
  if (isYou) return "you";
  return undefined;
}
