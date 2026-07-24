"use client";

import { useEffect, useState } from "react";
import { Empty, ErrorState, Loading } from "@/components/States";
import { ShareButton } from "@/components/ShareButton";
import { SITE_URL } from "@/lib/constants";
import { getNrlTipsSummary } from "@/lib/nrlTips";
import { ApiError, getOrCreateDeviceId } from "@/lib/session";
import type { NrlTipsSummaryResponse } from "@/lib/types";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; data: NrlTipsSummaryResponse };

/** "You vs the AI" running record (design doc: NRL Round Tips, Slice 2) --
 *  per-round and season-long points, graded under the identical
 *  draw-scores-everyone rule on both sides so the two numbers are directly
 *  comparable. Anonymous, device-id keyed; fetches client-side only, same
 *  as PlayRound, so the ISR page never carries user-specific server HTML. */
export function YouVsAi() {
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
    getNrlTipsSummary(deviceId)
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
  }, [attempt]);

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
        (state.data.rounds.length === 0 ? (
          <Empty label="Play this round to start your record against the model." />
        ) : (
          <div className="glass rounded-2xl p-4">
            <div className="flex items-center justify-center gap-6">
              <Stat label="You" value={state.data.totals.your_points} />
              <span className="text-xs font-semibold text-muted">vs</span>
              <Stat label="ML model" value={state.data.totals.model_points} />
            </div>
            <p className="mt-2 text-center text-xs text-muted">
              {state.data.totals.rounds_played} round{state.data.totals.rounds_played === 1 ? "" : "s"} graded
            </p>
            <StreakChips data={state.data} />
            <div className="mt-3 space-y-1.5 border-t border-border pt-3">
              {state.data.rounds.map((r) => {
                // Own share-page URL, built from the player's handle -- never
                // from anything the client already has other than that handle.
                const handle = state.data.handle;
                const shareUrl = handle
                  ? `${SITE_URL}/nrl/tips/share/${r.season}/${r.round}/${encodeURIComponent(handle)}`
                  : null;
                return (
                  <div key={`${r.season}-${r.round}`} className="flex items-center justify-between text-xs">
                    <span className="text-muted">Round {r.round}</span>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold tabular-nums">
                        {r.your_points} – {r.model_points}
                      </span>
                      {shareUrl && (
                        <ShareButton
                          label="Share"
                          title={`${handle} went ${r.your_points}/${r.matches_played} vs the AI — NRL Round ${r.round}`}
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

/** Personal streak/best-round stats (Slice 2.5, season-scoped) -- null-safe:
 *  each chip only renders when it has something to say, and the whole strip
 *  disappears rather than showing a row of zeroes. */
function StreakChips({ data }: { data: NrlTipsSummaryResponse }) {
  if (data.current_streak <= 0 && data.best_streak <= 0 && !data.best_round) return null;
  return (
    <div className="mt-3 flex flex-wrap justify-center gap-1.5">
      {data.current_streak > 0 && (
        <span className="rounded-full bg-win/15 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-lime-deep">
          {data.current_streak}-pick streak
        </span>
      )}
      {data.best_streak > 0 && (
        <span className="rounded-full bg-surface-2 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
          Best streak {data.best_streak}
        </span>
      )}
      {data.best_round && (
        <span className="rounded-full bg-surface-2 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
          Best round Rd {data.best_round.round} · {data.best_round.points}
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
