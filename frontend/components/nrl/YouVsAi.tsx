"use client";

import { useEffect, useState } from "react";
import { Empty, ErrorState, Loading } from "@/components/States";
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
            <div className="mt-3 space-y-1.5 border-t border-border pt-3">
              {state.data.rounds.map((r) => (
                <div key={`${r.season}-${r.round}`} className="flex items-center justify-between text-xs">
                  <span className="text-muted">Round {r.round}</span>
                  <span className="font-semibold tabular-nums">
                    {r.your_points} – {r.model_points}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
    </section>
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
