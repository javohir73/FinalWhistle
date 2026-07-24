"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ChanceChip } from "@/components/ChanceChip";
import { ClubBadge } from "@/components/ClubBadge";
import { kickoffLabel } from "@/components/nrl/TipsheetBlock";
import { getNrlConditionalProjections } from "@/lib/nrlRunHome";
import { encodePicks, parsePicksParam, type PickOutcome, type Picks } from "@/lib/nrlRunHomePicks";
import { ApiError } from "@/lib/session";
import { cn } from "@/lib/utils";
import type { NrlConditionalProjectionsResponse, NrlMatch } from "@/lib/types";

const DEBOUNCE_MS = 400;
const RUN_HOME_PATH = "/nrl/run-home";

/** Movement vs the unconditioned baseline, in percentage points -- the
 *  small up/down delta the odds panel shows next to each chance. */
function movement(current: number, base: number): { text: string | null; tone: "up" | "down" | "muted" } {
  const deltaPts = Math.round((current - base) * 100);
  if (deltaPts === 0) return { text: null, tone: "muted" };
  return {
    text: `${deltaPts > 0 ? "+" : ""}${deltaPts}pt${Math.abs(deltaPts) === 1 ? "" : "s"}`,
    tone: deltaPts > 0 ? "up" : "down",
  };
}

/** The finals-race machine (design doc: NRL Round Tips, Slice 3): tap a
 *  three-state toggle per remaining fixture (model / home win / away win) and
 *  every club's top-8/top-4/minor-premiership odds recompute inside the SAME
 *  Monte Carlo that powers the nightly `nrl_projections` job -- the pick
 *  becomes a forced outcome, unpicked matches keep sampling from the model.
 *
 *  Pick state lives in the URL (`?picks=`, backend's exact encoding) via
 *  `router.replace` -- shareable, no history spam, restored on load. `season`/
 *  `rounds`/`baseline` all come from the already-rendered server page so this
 *  can never disagree with what's shown above it. */
export function RunHomePredictor({
  season,
  rounds,
  baseline,
}: {
  season: number;
  rounds: { round: number | null; matches: NrlMatch[] }[];
  baseline: NrlConditionalProjectionsResponse;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const remainingIds = useMemo(
    () => new Set(rounds.flatMap((r) => r.matches.map((m) => m.id))),
    [rounds],
  );
  const matchesById = useMemo(
    () => new Map(rounds.flatMap((r) => r.matches).map((m) => [m.id, m])),
    [rounds],
  );

  // Seed once from ?picks= on first render only -- this component owns the
  // URL from here on (see the router.replace effect below), so re-reading
  // searchParams on every render would fight the user's own taps.
  const initial = useMemo(
    () => parsePicksParam(searchParams.get("picks"), remainingIds),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const [picks, setPicks] = useState<Picks>(initial.picks);
  const [notice, setNotice] = useState<string | null>(
    initial.dropped ? "Some picks in that link weren't valid — showing the ones that were." : null,
  );

  const [odds, setOdds] = useState<NrlConditionalProjectionsResponse>(baseline);
  const [loadingOdds, setLoadingOdds] = useState(false);
  const [oddsError, setOddsError] = useState<string | null>(null);

  // Local clock so a fixture freezes into "Locked" the instant kickoff
  // passes, mirroring PlayRound's always-on tick.
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);

  // A pick on a match that has since kicked off is no longer "remaining"
  // server-side (it would 422 as match_not_remaining) -- drop it quietly the
  // moment the clock says it's locked, rather than let a stale forced
  // outcome linger in the URL.
  useEffect(() => {
    setPicks((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const id of Object.keys(next).map(Number)) {
        const m = matchesById.get(id);
        if (m?.kickoff_utc && now.getTime() >= new Date(m.kickoff_utc).getTime()) {
          delete next[id];
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [now, matchesById]);

  // Keep the URL in sync with the current picks: replace (never push), so
  // tapping through picks doesn't spam browser history.
  useEffect(() => {
    const qs = encodePicks(picks);
    router.replace(qs ? `${RUN_HOME_PATH}?picks=${qs}` : RUN_HOME_PATH, { scroll: false });
  }, [picks, router]);

  // Debounced conditional fetch. `active` (set false on cleanup, same guard
  // as lib/useFetch.ts) discards a resolution that arrives after a newer
  // pick has already superseded it -- an out-of-order-response guard without
  // a separate request-id counter, since only one timer is ever live at once.
  useEffect(() => {
    if (Object.keys(picks).length === 0) {
      setOdds(baseline);
      setOddsError(null);
      setLoadingOdds(false);
      return;
    }
    let active = true;
    setLoadingOdds(true);
    const timer = setTimeout(() => {
      getNrlConditionalProjections(season, encodePicks(picks))
        .then((res) => {
          if (!active) return;
          setOdds(res);
          setOddsError(null);
        })
        .catch((err) => {
          if (!active) return;
          setOddsError(
            err instanceof ApiError ? err.message : "Couldn't update odds — showing the last known simulation.",
          );
        })
        .finally(() => {
          if (active) setLoadingOdds(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [picks, season, baseline]);

  const toggle = useCallback((matchId: number, next: "model" | PickOutcome) => {
    setNotice(null);
    setPicks((prev) => {
      const copy = { ...prev };
      if (next === "model") delete copy[matchId];
      else copy[matchId] = next;
      return copy;
    });
  }, []);

  const reset = useCallback(() => setPicks({}), []);

  const baselineByTeam = useMemo(
    () => Object.fromEntries(baseline.teams.map((t) => [t.team, t])),
    [baseline],
  );
  const picksApplied = Object.keys(picks).length;

  return (
    <div className="mt-6 space-y-6">
      <section className="glass rounded-2xl p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-display text-[11px] font-semibold uppercase tracking-wider text-muted">
            Finals odds · from {odds.n_sims.toLocaleString()} simulations
          </span>
          <div className="flex items-center gap-3 text-xs text-muted">
            <span>
              {picksApplied} pick{picksApplied === 1 ? "" : "s"} applied
            </span>
            <button
              type="button"
              onClick={reset}
              disabled={picksApplied === 0}
              className="rounded-lg border border-border px-2.5 py-1 font-semibold text-foreground transition disabled:opacity-40"
            >
              Reset
            </button>
          </div>
        </div>

        {notice ? <p className="mt-2 text-xs text-amber-ink">{notice}</p> : null}
        {oddsError ? <p className="mt-2 text-xs text-loss">{oddsError}</p> : null}

        <div className={cn("mt-3 overflow-x-auto", loadingOdds && "animate-pulse opacity-70")}>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left font-display text-[11px] uppercase tracking-wider text-muted">
                <th className="py-1.5 pr-2 font-semibold">Club</th>
                <th className="py-1.5 text-right font-semibold">Top 8</th>
                <th className="py-1.5 text-right font-semibold">Top 4</th>
                <th className="py-1.5 text-right font-semibold">Minor prem.</th>
              </tr>
            </thead>
            <tbody>
              {odds.teams.map((row) => {
                const base = baselineByTeam[row.team];
                const top8Move = base ? movement(row.top8, base.top8) : { text: null, tone: "muted" as const };
                const top4Move = base ? movement(row.top4, base.top4) : { text: null, tone: "muted" as const };
                const premMove = base
                  ? movement(row.minor_premiership, base.minor_premiership)
                  : { text: null, tone: "muted" as const };
                return (
                  <tr key={row.team} className="border-t border-border">
                    <td className="flex items-center gap-2 py-2 pr-2">
                      <ClubBadge name={row.team} size={20} />
                      <span className="font-medium">{row.team}</span>
                    </td>
                    <td className="py-2 text-right">
                      <ChanceChip prob={row.top8} deltaText={top8Move.text} tone={top8Move.tone} />
                    </td>
                    <td className="py-2 text-right">
                      <ChanceChip prob={row.top4} deltaText={top4Move.text} tone={top4Move.tone} />
                    </td>
                    <td className="py-2 text-right">
                      <ChanceChip prob={row.minor_premiership} deltaText={premMove.text} tone={premMove.tone} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <div className="space-y-5">
        {rounds.map((r) => (
          <section key={r.round ?? "unknown"}>
            <h2 className="mb-2.5 px-0.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
              Round {r.round ?? "—"}
            </h2>
            <div className="grid gap-4 sm:grid-cols-2">
              {r.matches.map((m) => (
                <FixtureRow key={m.id} match={m} pick={picks[m.id] ?? null} now={now} onPick={(p) => toggle(m.id, p)} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function FixtureRow({
  match,
  pick,
  now,
  onPick,
}: {
  match: NrlMatch;
  pick: PickOutcome | null;
  now: Date;
  onPick: (next: "model" | PickOutcome) => void;
}) {
  const locked = match.kickoff_utc != null && now.getTime() >= new Date(match.kickoff_utc).getTime();
  const p = match.prediction;
  const modelFavors = p ? (p.p_home >= p.p_away ? "home" : "away") : null;
  const modelProb = p ? Math.max(p.p_home, p.p_away) : null;

  return (
    <div className="glass rounded-2xl p-4">
      <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
        {locked ? "Locked" : kickoffLabel(match.kickoff_utc)}
      </span>

      <div className="mt-2 flex items-center justify-center gap-2 text-sm font-semibold">
        <ClubBadge name={match.home} />
        <span>{match.home ?? "TBC"}</span>
        <span className="text-muted">vs</span>
        <span>{match.away ?? "TBC"}</span>
        <ClubBadge name={match.away} />
      </div>

      <div
        className="mt-3 grid grid-cols-3 gap-2"
        role="group"
        aria-label={`Your run-home pick for ${match.home ?? "home"} vs ${match.away ?? "away"}`}
      >
        {(["model", "home", "away"] as const).map((side) => {
          const active = side === "model" ? pick === null : pick === side;
          const label = side === "model" ? "Model" : side === "home" ? match.home ?? "Home" : match.away ?? "Away";
          const sub =
            side === "model" && modelFavors && modelProb != null
              ? `${modelFavors === "home" ? match.home : match.away} ${Math.round(modelProb * 100)}%`
              : null;
          return (
            <button
              key={side}
              type="button"
              aria-pressed={active}
              disabled={locked}
              onClick={() => onPick(side)}
              className={cn(
                "truncate rounded-lg border px-2 py-2 text-xs font-semibold transition disabled:opacity-60",
                active
                  ? "border-win/60 bg-win/15 text-foreground"
                  : "border-border bg-surface-2/50 text-muted hover:border-win/40 hover:text-foreground",
              )}
            >
              {label}
              {sub ? <small className="block text-[9px] font-normal normal-case text-muted">{sub}</small> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}
