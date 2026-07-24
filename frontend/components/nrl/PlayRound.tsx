"use client";

import { useCallback, useEffect, useState } from "react";
import { ClubBadge } from "@/components/ClubBadge";
import { ErrorState, Loading } from "@/components/States";
import { kickoffLabel } from "@/components/nrl/TipsheetBlock";
import { getMyNrlTips, submitNrlTip } from "@/lib/nrlTips";
import { ApiError, getOrCreateDeviceId, pingDailyActivity } from "@/lib/session";
import { cn } from "@/lib/utils";
import type { NrlMyTipsMatch, NrlMyTipYourTip } from "@/lib/types";

type Pick = "home" | "draw" | "away";

// Per-round local cache: paints last-confirmed picks instantly on a repeat
// visit instead of waiting on /tips/mine, mirrors useMatchPicks' localStorage
// idiom. Only ever written from a CONFIRMED (server-accepted) submit --
// see submit() below -- so a stale/rejected optimistic value never persists.
const CACHE_PREFIX = "finalwhistle:nrl-tips:v1:";

interface CachedTip {
  pick: Pick;
  margin: number | null;
}

function readCache(season: number, round: number): Record<number, CachedTip> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(`${CACHE_PREFIX}${season}:${round}`);
    return raw ? (JSON.parse(raw) as Record<number, CachedTip>) : {};
  } catch {
    return {}; // corrupt -- start fresh
  }
}

function writeCache(season: number, round: number, matchId: number, tip: CachedTip): void {
  try {
    const next = { ...readCache(season, round), [matchId]: tip };
    window.localStorage.setItem(`${CACHE_PREFIX}${season}:${round}`, JSON.stringify(next));
  } catch {
    /* storage unavailable (private mode / quota) -- non-fatal */
  }
}

function pickLabel(pick: Pick, match: NrlMyTipsMatch): string {
  return pick === "home" ? (match.home ?? "Home") : pick === "away" ? (match.away ?? "Away") : "a draw";
}

/** "Play this round" (design doc: NRL Round Tips, Slice 2): tap-to-pick per
 *  game plus a margin guess on the featured match, submitted anonymously via
 *  the device id. `season`/`round` come from the already-rendered tipsheet
 *  so this can never disagree with what the page above it is showing.
 *
 *  Nothing here renders server-side with user-specific data -- the ISR page
 *  stays cacheable because every fetch below happens client-side after
 *  mount (deviceId starts null during SSR/hydration, same guard as
 *  ActivityPing/useMatchPicks). */
export function PlayRound({ season, round }: { season: number; round: number }) {
  const [deviceId, setDeviceId] = useState<string | null>(null);
  useEffect(() => setDeviceId(getOrCreateDeviceId()), []);

  // Local clock so a row freezes into its locked state the moment kickoff
  // passes, even if the tab has been open since before it did (mirrors
  // MatchesClient's always-on tick).
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);

  const [matches, setMatches] = useState<NrlMyTipsMatch[] | null>(null);
  const [handle, setHandle] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [pending, setPending] = useState<Record<number, boolean>>({});
  const [rowError, setRowError] = useState<Record<number, string>>({});
  const [marginDraft, setMarginDraft] = useState<Record<number, string>>({});

  useEffect(() => {
    if (!deviceId) return;
    let live = true;
    setLoadError(null);
    getMyNrlTips(deviceId, season, round)
      .then((res) => {
        if (!live) return;
        // Fill in any locally-cached pick the server doesn't know about yet
        // (e.g. a submit that raced this load) -- server truth wins per match.
        const cache = readCache(season, round);
        const merged = res.matches.map((m) => {
          if (m.your_tip || !cache[m.id]) return m;
          const c = cache[m.id];
          const your_tip: NrlMyTipYourTip = {
            pick: c.pick, margin: c.margin, points: null, round_margin: null,
            graded_at: null, updated_at: null,
          };
          return { ...m, your_tip };
        });
        setMatches(merged);
        setHandle(res.handle);
      })
      .catch((err) => {
        if (!live) return;
        setLoadError(err instanceof ApiError ? err.message : "Couldn't load this round's tips.");
      });
    return () => {
      live = false;
    };
  }, [deviceId, season, round, attempt]);

  const submit = useCallback(
    async (matchId: number, pick: Pick, marginOverride?: number) => {
      if (!deviceId) return;
      const prevMatches = matches;
      const prevTip = matches?.find((m) => m.id === matchId)?.your_tip ?? null;
      const margin = marginOverride !== undefined ? marginOverride : (prevTip?.margin ?? null);

      setRowError((e) => {
        const next = { ...e };
        delete next[matchId];
        return next;
      });
      setPending((p) => ({ ...p, [matchId]: true }));
      // Optimistic paint -- reverted below if the server rejects it.
      setMatches(
        (cur) =>
          cur?.map((m) =>
            m.id === matchId
              ? { ...m, your_tip: { pick, margin, points: null, round_margin: null, graded_at: null, updated_at: new Date().toISOString() } }
              : m,
          ) ?? cur,
      );

      try {
        const res = await submitNrlTip({ device_id: deviceId, match_id: matchId, pick, margin });
        setMatches(
          (cur) =>
            cur?.map((m) =>
              m.id === matchId
                ? { ...m, your_tip: { pick: res.tip.pick, margin: res.tip.margin, points: null, round_margin: null, graded_at: null, updated_at: res.tip.updated_at } }
                : m,
            ) ?? cur,
        );
        writeCache(season, round, matchId, { pick: res.tip.pick, margin: res.tip.margin });
        setHandle(res.handle);
        // Retention instrumentation (design doc: "tips-locked ... ride the
        // existing activity-ping client") -- reuse the same best-effort call
        // ActivityPing fires on every page load, not a new analytics path.
        pingDailyActivity().catch(() => {});
      } catch (err) {
        setMatches(prevMatches ?? null); // never claim a rejected pick was saved
        setRowError((e) => ({
          ...e,
          [matchId]: err instanceof ApiError ? err.message : "Couldn't save your tip — try again.",
        }));
      } finally {
        setPending((p) => {
          const next = { ...p };
          delete next[matchId];
          return next;
        });
      }
    },
    [deviceId, matches, season, round],
  );

  if (loadError) return <ErrorState message={loadError} onRetry={() => setAttempt((a) => a + 1)} />;
  if (!matches) return <Loading label="Loading this round's tips…" />;
  if (matches.length === 0) return null;

  return (
    <section>
      <div className="mb-2.5 flex items-center justify-between gap-3 px-0.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted">Play this round</h2>
        {handle ? <span className="text-xs text-muted">Playing as {handle}</span> : null}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {matches.map((m) => (
          <PlayRow
            key={m.id}
            match={m}
            now={now}
            pending={!!pending[m.id]}
            error={rowError[m.id]}
            marginDraft={marginDraft[m.id]}
            onPick={(pick) => submit(m.id, pick)}
            onMarginChange={(v) => setMarginDraft((d) => ({ ...d, [m.id]: v }))}
            onMarginCommit={(pick, margin) => submit(m.id, pick, margin)}
          />
        ))}
      </div>
    </section>
  );
}

function PlayRow({
  match,
  now,
  pending,
  error,
  marginDraft,
  onPick,
  onMarginChange,
  onMarginCommit,
}: {
  match: NrlMyTipsMatch;
  now: Date;
  pending: boolean;
  error?: string;
  marginDraft?: string;
  onPick: (pick: Pick) => void;
  onMarginChange: (value: string) => void;
  onMarginCommit: (pick: Pick, margin: number) => void;
}) {
  const locked = match.kickoff_utc != null && now.getTime() >= new Date(match.kickoff_utc).getTime();
  const tip = match.your_tip;

  return (
    <div className="glass rounded-2xl p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
          {locked ? "Locked" : kickoffLabel(match.kickoff_utc)}
        </span>
        {match.is_featured ? (
          <span className="rounded-full bg-gold/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-ink">
            Featured match — margin for tiebreaks
          </span>
        ) : null}
      </div>

      <div className="mt-2 flex items-center justify-center gap-2 text-sm font-semibold">
        <ClubBadge name={match.home} />
        <span>{match.home ?? "TBC"}</span>
        <span className="text-muted">vs</span>
        <span>{match.away ?? "TBC"}</span>
        <ClubBadge name={match.away} />
      </div>

      {locked ? (
        <p className="mt-3 text-center text-sm">
          {tip ? (
            <>
              You picked <strong>{pickLabel(tip.pick, match)}</strong>
              {tip.points != null ? (
                <span className={tip.points > 0 ? "text-lime-deep" : "text-loss"}>
                  {" "}
                  — {tip.points > 0 ? "scored" : "missed"}
                </span>
              ) : (
                <span className="text-muted"> — awaiting full time</span>
              )}
            </>
          ) : (
            <span className="text-muted">No tip submitted</span>
          )}
        </p>
      ) : (
        <>
          <div
            className="mt-3 grid grid-cols-3 gap-2"
            role="group"
            aria-label={`Your pick for ${match.home ?? "home"} vs ${match.away ?? "away"}`}
          >
            {(["home", "draw", "away"] as const).map((side) => {
              const label = side === "home" ? (match.home ?? "Home") : side === "away" ? (match.away ?? "Away") : "Draw";
              const active = tip?.pick === side;
              return (
                <button
                  key={side}
                  type="button"
                  aria-pressed={active}
                  disabled={pending}
                  onClick={() => onPick(side)}
                  className={cn(
                    "truncate rounded-lg border px-2 py-2 text-xs font-semibold transition disabled:opacity-60",
                    active
                      ? "border-win/60 bg-win/15 text-foreground"
                      : "border-border bg-surface-2/50 text-muted hover:border-win/40 hover:text-foreground",
                  )}
                >
                  {label}
                </button>
              );
            })}
          </div>

          {match.is_featured ? (
            <label className="mt-3 flex items-center justify-between gap-2 text-xs text-muted">
              <span>Margin guess</span>
              <input
                type="number"
                min={0}
                max={100}
                inputMode="numeric"
                disabled={!tip?.pick || pending}
                value={marginDraft ?? tip?.margin ?? ""}
                onChange={(e) => onMarginChange(e.target.value)}
                onBlur={(e) => {
                  const n = Number(e.target.value);
                  if (tip?.pick && e.target.value !== "" && Number.isFinite(n)) onMarginCommit(tip.pick, n);
                }}
                className="w-16 rounded-lg border border-border bg-surface-2/50 px-2 py-1 text-right text-foreground"
              />
            </label>
          ) : null}
        </>
      )}

      {error ? <p className="mt-2 text-center text-xs font-medium text-loss">{error}</p> : null}
    </div>
  );
}
