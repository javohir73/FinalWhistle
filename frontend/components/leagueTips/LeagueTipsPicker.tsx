"use client";

import { useCallback, useEffect, useState } from "react";
import { Flag } from "@/components/Flag";
import { Empty, ErrorState, Loading } from "@/components/States";
import { getMyLeagueTips, submitLeagueTip } from "@/lib/leagueTips";
import { formatScore } from "@/lib/format";
import { kickoffDate, kickoffTime } from "@/lib/datetime";
import { useTimezone } from "@/lib/useTimezone";
import { ApiError, getOrCreateDeviceId, pingDailyActivity } from "@/lib/session";
import { cn } from "@/lib/utils";
import type { LeagueTipsMineMatch, LeagueTipsMineResponse, LeagueTipsMineYourPrediction } from "@/lib/types";

const MIN_GOALS = 0;
const MAX_GOALS = 15;

function clampGoals(n: number): number {
  return Math.min(MAX_GOALS, Math.max(MIN_GOALS, n));
}

// Per-(league, matchweek) local cache: paints last-confirmed predictions
// instantly on a repeat visit instead of waiting on /tips/mine. Only ever
// written from a CONFIRMED (server-accepted) submit -- see submit() below --
// so a stale/rejected optimistic value never persists. Mirrors PlayRound's
// CACHE_PREFIX idiom (components/nrl/PlayRound.tsx).
const CACHE_PREFIX = "finalwhistle:league-tips:v1:";

interface CachedPrediction {
  predicted_home: number;
  predicted_away: number;
}

function readCache(league: string, matchweek: number): Record<number, CachedPrediction> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(`${CACHE_PREFIX}${league}:${matchweek}`);
    return raw ? (JSON.parse(raw) as Record<number, CachedPrediction>) : {};
  } catch {
    return {}; // corrupt -- start fresh
  }
}

function writeCache(league: string, matchweek: number, matchId: number, pred: CachedPrediction): void {
  try {
    const next = { ...readCache(league, matchweek), [matchId]: pred };
    window.localStorage.setItem(`${CACHE_PREFIX}${league}:${matchweek}`, JSON.stringify(next));
  } catch {
    /* storage unavailable (private mode / quota) -- non-fatal */
  }
}

function kickoffLabel(iso: string | null, tz: string): string {
  if (!iso) return "Kickoff TBC";
  return `${kickoffDate(iso, tz)} · ${kickoffTime(iso, tz)}`;
}

/** "Beat the AI's scoreline" (design doc: League Score Predictions,
 *  2026-07-24) -- the football-league port of components/nrl/PlayRound.tsx.
 *  Unlike NRL there is no separate public tipsheet endpoint: /tips/mine is
 *  device-scoped (no-store) and carries both the AI's frozen scoreline and
 *  the device's own prediction in one payload, so this component owns the
 *  whole fixture list, not just the picker half. `league` comes from a prop
 *  (Phase 1's one config entry lives in lib/leagueConfig.ts, not here) so
 *  Phase 2's extra leagues need no changes here.
 *
 *  Matchweek is unknown until the first successful load resolves it
 *  server-side (`_current_matchweek`) -- there is no client-side list of
 *  valid matchweeks, so prev/next re-request an adjacent number and treat a
 *  `matchweek_not_found` 404 as "there is nothing there", not an error.
 *
 *  Nothing here renders server-side with user-specific data -- every fetch
 *  happens client-side after mount (deviceId starts null during SSR/
 *  hydration), same guard as PlayRound, so /tips stays an ISR-cacheable shell. */
export function LeagueTipsPicker({
  league,
  onMatchweekChange,
}: {
  league: string;
  onMatchweekChange?: (matchweek: number) => void;
}) {
  const { tz } = useTimezone();
  const [deviceId, setDeviceId] = useState<string | null>(null);
  useEffect(() => setDeviceId(getOrCreateDeviceId()), []);

  // Local clock so a row freezes into its locked state the moment kickoff
  // passes, even if the tab has been open since before it did (mirrors
  // PlayRound's always-on tick).
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);

  const [requested, setRequested] = useState<number | null>(null); // explicit nav target; null = "let the server resolve current"
  const [current, setCurrent] = useState<LeagueTipsMineResponse | null>(null);
  const [seasonNotStarted, setSeasonNotStarted] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [navError, setNavError] = useState<string | null>(null);
  const [boundary, setBoundary] = useState({ prev: false, next: false });
  const [attempt, setAttempt] = useState(0);
  const [pending, setPending] = useState<Record<number, boolean>>({});
  const [rowError, setRowError] = useState<Record<number, string>>({});
  const [draftHome, setDraftHome] = useState<Record<number, string>>({});
  const [draftAway, setDraftAway] = useState<Record<number, string>>({});

  useEffect(() => {
    if (!deviceId) return;
    let live = true;
    setLoadError(null);
    setNavError(null);
    getMyLeagueTips(league, deviceId, requested ?? undefined)
      .then((res) => {
        if (!live) return;
        // Fill in any locally-cached prediction the server doesn't know
        // about yet (e.g. a submit that raced this load) -- server truth
        // wins per match. Mirrors PlayRound's merge-on-load.
        const cache = readCache(league, res.matchweek);
        const merged = res.matches.map((m) => {
          if (m.your_prediction || !cache[m.id]) return m;
          const c = cache[m.id];
          const your_prediction: LeagueTipsMineYourPrediction = {
            predicted_home: c.predicted_home, predicted_away: c.predicted_away,
            points: null, exact: null, graded_at: null, updated_at: null,
          };
          return { ...m, your_prediction };
        });
        setCurrent({ ...res, matches: merged });
        setSeasonNotStarted(false);
        setBoundary({ prev: false, next: false });
        onMatchweekChange?.(res.matchweek);
      })
      .catch((err) => {
        if (!live) return;
        if (err instanceof ApiError && ["league_not_found", "league_inactive", "no_matchweek_data"].includes(err.code)) {
          setSeasonNotStarted(true);
          return;
        }
        if (err instanceof ApiError && err.code === "matchweek_not_found" && requested != null && current) {
          // Nav ran off the end of the loaded fixtures -- keep showing the
          // last good matchweek and just flag that direction as exhausted.
          setBoundary((b) => ({ ...b, [requested < current.matchweek ? "prev" : "next"]: true }));
          setNavError(`No ${league} matches loaded for that matchweek yet.`);
          return;
        }
        setLoadError(err instanceof ApiError ? err.message : "Couldn't load this matchweek's tips.");
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceId, league, requested, attempt]);

  const submit = useCallback(
    async (matchId: number, predicted_home: number, predicted_away: number) => {
      if (!deviceId || !current) return;
      const prevMatches = current.matches;

      setRowError((e) => {
        const next = { ...e };
        delete next[matchId];
        return next;
      });
      setPending((p) => ({ ...p, [matchId]: true }));
      // Optimistic paint -- reverted below if the server rejects it.
      setCurrent((cur) =>
        cur && {
          ...cur,
          matches: cur.matches.map((m) =>
            m.id === matchId
              ? {
                  ...m,
                  your_prediction: {
                    predicted_home, predicted_away, points: null, exact: null,
                    graded_at: null, updated_at: new Date().toISOString(),
                  },
                }
              : m,
          ),
        },
      );

      try {
        const res = await submitLeagueTip(league, {
          device_id: deviceId, match_id: matchId, predicted_home, predicted_away,
        });
        setCurrent((cur) =>
          cur && {
            ...cur,
            handle: res.handle,
            matches: cur.matches.map((m) =>
              m.id === matchId
                ? {
                    ...m,
                    your_prediction: {
                      predicted_home: res.prediction.predicted_home,
                      predicted_away: res.prediction.predicted_away,
                      points: null, exact: null, graded_at: null,
                      updated_at: res.prediction.updated_at,
                    },
                  }
                : m,
            ),
          },
        );
        writeCache(league, current.matchweek, matchId, {
          predicted_home: res.prediction.predicted_home,
          predicted_away: res.prediction.predicted_away,
        });
        // Retention instrumentation (same best-effort call ActivityPing
        // fires on every page load, not a new analytics path).
        pingDailyActivity().catch(() => {});
      } catch (err) {
        setCurrent((cur) => cur && { ...cur, matches: prevMatches }); // never claim a rejected score was saved
        setDraftHome((d) => {
          const next = { ...d };
          delete next[matchId];
          return next;
        });
        setDraftAway((d) => {
          const next = { ...d };
          delete next[matchId];
          return next;
        });
        setRowError((e) => ({
          ...e,
          [matchId]: err instanceof ApiError ? err.message : "Couldn't save your prediction — try again.",
        }));
      } finally {
        setPending((p) => {
          const next = { ...p };
          delete next[matchId];
          return next;
        });
      }
    },
    [deviceId, current, league],
  );

  if (seasonNotStarted) {
    return (
      <section>
        <h2 className="mb-2.5 px-0.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
          Beat the AI
        </h2>
        <Empty label="The season hasn't kicked off yet — check back once fixtures are loaded to start beating the AI." />
      </section>
    );
  }
  if (loadError) return <ErrorState message={loadError} onRetry={() => setAttempt((a) => a + 1)} />;
  if (!current) return <Loading label="Loading this matchweek's tips…" />;

  const prevWeek = current.matchweek - 1;
  const nextWeek = current.matchweek + 1;

  return (
    <section>
      <div className="mb-2.5 flex items-center justify-between gap-3 px-0.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted">Beat the AI</h2>
        {current.handle ? <span className="text-xs text-muted">Playing as {current.handle}</span> : null}
      </div>

      <div className="mb-3 flex items-center justify-between gap-2">
        {prevWeek >= 1 && !boundary.prev ? (
          <button
            type="button"
            onClick={() => setRequested(prevWeek)}
            className="text-sm font-semibold text-lime-deep"
          >
            ← Matchweek {prevWeek}
          </button>
        ) : (
          <span />
        )}
        <span className="font-display text-lg font-extrabold">Matchweek {current.matchweek}</span>
        {!boundary.next ? (
          <button
            type="button"
            onClick={() => setRequested(nextWeek)}
            className="text-sm font-semibold text-lime-deep"
          >
            Matchweek {nextWeek} →
          </button>
        ) : (
          <span />
        )}
      </div>
      {navError ? <p className="mb-3 text-center text-xs text-muted">{navError}</p> : null}

      <p className="mb-3 text-center text-xs text-muted">
        Every AI scoreline below is frozen at kickoff, exactly like yours.
      </p>

      {current.matches.length === 0 ? (
        <Empty label="No fixtures for this matchweek." />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {current.matches.map((m) => (
            <PredictionRow
              key={m.id}
              match={m}
              now={now}
              tz={tz}
              pending={!!pending[m.id]}
              error={rowError[m.id]}
              draftHome={draftHome[m.id]}
              draftAway={draftAway[m.id]}
              onDraftHome={(v) => setDraftHome((d) => ({ ...d, [m.id]: v }))}
              onDraftAway={(v) => setDraftAway((d) => ({ ...d, [m.id]: v }))}
              onSubmit={(home, away) => submit(m.id, home, away)}
            />
          ))}
        </div>
      )}

      <p className="mt-4 text-center text-xs leading-relaxed text-muted">{current.disclaimer}</p>
    </section>
  );
}

function PredictionRow({
  match,
  now,
  tz,
  pending,
  error,
  draftHome,
  draftAway,
  onDraftHome,
  onDraftAway,
  onSubmit,
}: {
  match: LeagueTipsMineMatch;
  now: Date;
  tz: string;
  pending: boolean;
  error?: string;
  draftHome?: string;
  draftAway?: string;
  onDraftHome: (value: string) => void;
  onDraftAway: (value: string) => void;
  onSubmit: (home: number, away: number) => void;
}) {
  const locked =
    match.status === "finished" ||
    (match.kickoff_utc != null && now.getTime() >= new Date(match.kickoff_utc).getTime());
  const your = match.your_prediction;
  const home = match.home ?? "Home";
  const away = match.away ?? "Away";

  const committedHome = your?.predicted_home ?? 0;
  const committedAway = your?.predicted_away ?? 0;
  const homeValue = draftHome ?? String(committedHome);
  const awayValue = draftAway ?? String(committedAway);

  function commit(side: "home" | "away", raw: string) {
    if (raw === "") return; // leave a mid-edit blank alone -- no premature submit
    const n = Number(raw);
    if (!Number.isFinite(n)) return;
    const clamped = clampGoals(Math.trunc(n));
    const otherHome = side === "home" ? clamped : Number(homeValue) || 0;
    const otherAway = side === "away" ? clamped : Number(awayValue) || 0;
    onSubmit(otherHome, otherAway);
  }

  function delta(side: "home" | "away", step: 1 | -1) {
    const nextHome = side === "home" ? clampGoals((Number(homeValue) || 0) + step) : Number(homeValue) || 0;
    const nextAway = side === "away" ? clampGoals((Number(awayValue) || 0) + step) : Number(awayValue) || 0;
    onSubmit(nextHome, nextAway);
  }

  return (
    <div className="glass rounded-2xl p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
          {match.status === "finished" ? "Full time" : locked ? "Locked" : kickoffLabel(match.kickoff_utc, tz)}
        </span>
        {match.model ? (
          <span className="inline-flex items-center rounded-md bg-surface-2 px-2 py-0.5 font-display text-xs font-bold tabular-nums text-foreground">
            <span className="mr-1.5 align-middle text-[10px] font-semibold uppercase tracking-wide text-muted">
              ML model
            </span>
            {formatScore(match.model.predicted_home, match.model.predicted_away)}
          </span>
        ) : null}
      </div>

      <div className="mt-2 flex items-center justify-center gap-2 text-sm font-semibold">
        <Flag team={home} />
        <span>{home}</span>
        <span className="text-muted">vs</span>
        <span>{away}</span>
        <Flag team={away} />
      </div>

      {locked ? (
        <p className="mt-3 text-center text-sm">
          {your ? (
            <>
              You predicted{" "}
              <strong>
                {your.predicted_home}–{your.predicted_away}
              </strong>
              {match.score_home != null && match.score_away != null ? (
                <span className="text-muted"> · Final {formatScore(match.score_home, match.score_away)}</span>
              ) : null}
              {your.graded_at ? (
                <span className={your.points && your.points > 0 ? "text-lime-deep" : "text-loss"}>
                  {" "}
                  — {your.exact ? "exact score!" : your.points ? "correct result" : "missed"}
                </span>
              ) : (
                <span className="text-muted"> — awaiting full time</span>
              )}
            </>
          ) : (
            <span className="text-muted">No prediction submitted</span>
          )}
        </p>
      ) : (
        <div className="mt-3 flex items-center justify-center gap-3" role="group" aria-label={`Your score prediction for ${home} vs ${away}`}>
          <GoalStepper
            label={home}
            value={homeValue}
            disabled={pending}
            onDelta={(step) => delta("home", step)}
            onChange={(v) => onDraftHome(v)}
            onBlur={() => commit("home", homeValue)}
          />
          <span className="pt-4 text-lg font-bold text-muted">–</span>
          <GoalStepper
            label={away}
            value={awayValue}
            disabled={pending}
            onDelta={(step) => delta("away", step)}
            onChange={(v) => onDraftAway(v)}
            onBlur={() => commit("away", awayValue)}
          />
        </div>
      )}

      {error ? <p className="mt-2 text-center text-xs font-medium text-loss">{error}</p> : null}
    </div>
  );
}

function GoalStepper({
  label,
  value,
  disabled,
  onDelta,
  onChange,
  onBlur,
}: {
  label: string;
  value: string;
  disabled: boolean;
  onDelta: (step: 1 | -1) => void;
  onChange: (value: string) => void;
  onBlur: () => void;
}) {
  const n = Number(value) || 0;
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="max-w-[72px] truncate text-[11px] font-semibold text-muted">{label}</span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label={`Decrease ${label} goals`}
          disabled={disabled || n <= MIN_GOALS}
          onClick={() => onDelta(-1)}
          className={cn(
            "grid h-7 w-7 place-items-center rounded-lg border border-border bg-surface-2/50 text-sm font-bold text-muted transition",
            "hover:border-win/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40",
          )}
        >
          −
        </button>
        <input
          type="number"
          min={MIN_GOALS}
          max={MAX_GOALS}
          inputMode="numeric"
          aria-label={`${label} goals`}
          disabled={disabled}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onBlur}
          className="w-10 rounded-lg border border-border bg-surface-2/50 px-1 py-1 text-center font-display text-lg font-bold tabular-nums text-foreground"
        />
        <button
          type="button"
          aria-label={`Increase ${label} goals`}
          disabled={disabled || n >= MAX_GOALS}
          onClick={() => onDelta(1)}
          className={cn(
            "grid h-7 w-7 place-items-center rounded-lg border border-border bg-surface-2/50 text-sm font-bold text-muted transition",
            "hover:border-win/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40",
          )}
        >
          +
        </button>
      </div>
    </div>
  );
}
