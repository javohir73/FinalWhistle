"use client";

import { useEffect, useState } from "react";
import { ErrorState, Loading } from "@/components/States";
import { getNrlTipsLeaderboard } from "@/lib/nrlTips";
import { ApiError } from "@/lib/session";
import { cn } from "@/lib/utils";
import type { NrlTipsLeaderboardResponse } from "@/lib/types";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; data: NrlTipsLeaderboardResponse };

/** Weekly (per-round) leaderboard for the beat-the-AI loop (design doc: NRL
 *  Round Tips, Slice 2). Hidden below _LEADERBOARD_MIN_PARTICIPANTS -- an
 *  empty leaderboard advertises an empty room, so below the gate this shows
 *  only a quiet participant count, never an empty table. Mirrors
 *  LeaderboardClient's table look for the football leaderboard. */
export function NrlTipsLeaderboard({ season, round }: { season: number; round: number }) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    getNrlTipsLeaderboard(season, round)
      .then((data) => live && setState({ status: "success", data }))
      .catch(
        (err) =>
          live &&
          setState({
            status: "error",
            message: err instanceof ApiError ? err.message : "Couldn't load the leaderboard.",
          }),
      );
    return () => {
      live = false;
    };
  }, [season, round, attempt]);

  return (
    <section>
      <h2 className="mb-2.5 px-0.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
        Leaderboard
      </h2>
      {state.status === "loading" && <Loading label="Loading leaderboard…" />}
      {state.status === "error" && (
        <ErrorState message={state.message} onRetry={() => setAttempt((a) => a + 1)} />
      )}
      {state.status === "success" &&
        (state.data.entries.length === 0 ? (
          <p className="glass rounded-2xl p-4 text-center text-sm text-muted">
            {state.data.participant_count} playing this round
          </p>
        ) : (
          <div className="glass overflow-x-auto rounded-2xl p-2 sm:p-4">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[11px] uppercase tracking-wider text-muted">
                  <th className="px-2 pb-2 text-left font-medium">#</th>
                  <th className="px-2 pb-2 text-left font-medium">Player</th>
                  <th className="px-2 pb-2 text-right font-medium">Points</th>
                  <th className="px-2 pb-2 text-right font-medium">Margin</th>
                </tr>
              </thead>
              <tbody>
                {state.data.entries.map((row, i) => (
                  <tr key={row.handle} className="border-t border-border">
                    <td
                      className={cn(
                        "px-2 py-2.5 font-semibold tabular-nums",
                        i === 0 ? "text-gold" : "text-muted",
                      )}
                    >
                      {i + 1}
                    </td>
                    <td className="px-2 py-2.5 font-medium">{row.handle}</td>
                    <td className="px-2 py-2.5 text-right font-display font-bold tabular-nums">
                      {row.points}
                    </td>
                    <td className="px-2 py-2.5 text-right tabular-nums text-muted">
                      {row.round_margin ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </section>
  );
}
