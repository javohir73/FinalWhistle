"use client";

import { useEffect, useState } from "react";
import { Empty, ErrorState, Loading } from "@/components/States";
import { ShareButton } from "@/components/ShareButton";
import { SITE_URL } from "@/lib/constants";
import { getLeagueTipsSummary } from "@/lib/leagueTips";
import { ApiError, getOrCreateDeviceId } from "@/lib/session";
import type { LeagueTipsSummaryResponse } from "@/lib/types";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; data: LeagueTipsSummaryResponse };

/** "You vs the AI" running record for the league loop (design doc: League
 *  Score Predictions, 2026-07-24) -- league-generic port of components/nrl/
 *  YouVsAi.tsx. Per-matchweek and season-long points, graded under the
 *  identical scoring rule on both sides so the two numbers are directly
 *  comparable. Anonymous, device-id keyed; fetches client-side only, same as
 *  LeagueTipsPicker, so /tips never carries user-specific server HTML. */
export function LeagueYouVsAi({ league }: { league: string }) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const deviceId = getOrCreateDeviceId();
    if (!deviceId) {
      setState({ status: "error", message: "Local storage isn't available in this browser." });
      return;
    }
    let live = true;
    setState({ status: "loading" });
    getLeagueTipsSummary(league, deviceId)
      .then((data) => live && setState({ status: "success", data }))
      .catch(
        (err) =>
          live &&
          setState({
            status: "error",
            message: err instanceof ApiError ? err.message : "Couldn't load your record.",
          }),
      );
    return () => {
      live = false;
    };
  }, [league, attempt]);

  return (
    <section>
      <h2 className="mb-2.5 px-0.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
        You vs the AI
      </h2>
      {state.status === "loading" && <Loading label="Loading your record…" />}
      {state.status === "error" && (
        <ErrorState message={state.message} onRetry={() => setAttempt((a) => a + 1)} />
      )}
      {state.status === "success" &&
        (state.data.matchweeks.length === 0 ? (
          <Empty label="Predict this matchweek to start your record against the model." />
        ) : (
          <div className="glass rounded-2xl p-4">
            <div className="flex items-center justify-center gap-6">
              <Stat label="You" value={state.data.totals.your_points} />
              <span className="text-xs font-semibold text-muted">vs</span>
              <Stat label="ML model" value={state.data.totals.model_points} />
            </div>
            <p className="mt-2 text-center text-xs text-muted">
              {state.data.totals.matchweeks_played} matchweek{state.data.totals.matchweeks_played === 1 ? "" : "s"} graded
            </p>
            <StreakChips data={state.data} />
            <div className="mt-3 space-y-1.5 border-t border-border pt-3">
              {state.data.matchweeks.map((w) => {
                // Own share-page URL, built from the player's handle -- never
                // from anything the client already has other than that handle.
                const handle = state.data.handle;
                const shareUrl =
                  handle && w.matchweek != null
                    ? `${SITE_URL}/tips/share/${league}/${w.matchweek}/${encodeURIComponent(handle)}`
                    : null;
                return (
                  <div key={w.matchweek ?? "unknown"} className="flex items-center justify-between text-xs">
                    <span className="text-muted">Matchweek {w.matchweek ?? "—"}</span>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold tabular-nums">
                        {w.your_points} – {w.model_points}
                      </span>
                      {shareUrl && (
                        <ShareButton
                          label="Share"
                          title={`${handle} went ${w.your_points}/${w.matches_played} vs the AI — Matchweek ${w.matchweek}`}
                          url={shareUrl}
                          className="gap-1 px-2 py-1 text-[11px]"
                        />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
    </section>
  );
}

/** Personal streak/best-matchweek stats -- null-safe: each chip only renders
 *  when it has something to say, and the whole strip disappears rather than
 *  showing a row of zeroes (mirrors components/nrl/YouVsAi.tsx). */
function StreakChips({ data }: { data: LeagueTipsSummaryResponse }) {
  if (data.current_streak <= 0 && data.best_streak <= 0 && !data.best_matchweek) return null;
  return (
    <div className="mt-3 flex flex-wrap justify-center gap-1.5">
      {data.current_streak > 0 && (
        <span className="rounded-full bg-win/15 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-lime-deep">
          {data.current_streak}-prediction streak
        </span>
      )}
      {data.best_streak > 0 && (
        <span className="rounded-full bg-surface-2 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
          Best streak {data.best_streak}
        </span>
      )}
      {data.best_matchweek && (
        <span className="rounded-full bg-surface-2 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
          Best matchweek MW{data.best_matchweek.matchweek} · {data.best_matchweek.points}
        </span>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <span className="text-center">
      <span className="block font-display text-2xl font-extrabold tabular-nums">{value}</span>
      <span className="block text-[11px] font-semibold text-muted">{label}</span>
    </span>
  );
}
