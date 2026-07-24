"use client";

import { useEffect, useState } from "react";
import { ErrorState, Loading } from "@/components/States";
import { getNrlSeasonLeaderboard, getNrlTipsLeaderboard } from "@/lib/nrlTips";
import { ApiError } from "@/lib/session";
import { cn } from "@/lib/utils";
import type { NrlSeasonLeaderboardEntry, NrlSeasonLeaderboardResponse, NrlTipsLeaderboardEntry, NrlTipsLeaderboardResponse } from "@/lib/types";

type WeeklyState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; data: NrlTipsLeaderboardResponse };

type SeasonState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; data: NrlSeasonLeaderboardResponse };

/** Weekly (per-round) leaderboard for the beat-the-AI loop (design doc: NRL
 *  Round Tips, Slice 2), plus a Season tab (Slice 2.5) over the season-long
 *  totals endpoint. Both share the same reveal rule: below
 *  _LEADERBOARD_MIN_PARTICIPANTS an empty leaderboard advertises an empty
 *  room, so this shows only a quiet participant count, never an empty table.
 *  Mirrors LeaderboardClient's table look for the football leaderboard. */
export function NrlTipsLeaderboard({ season, round }: { season: number; round: number }) {
  const [tab, setTab] = useState<"weekly" | "season">("weekly");
  const [weeklyState, setWeeklyState] = useState<WeeklyState>({ status: "loading" });
  const [weeklyAttempt, setWeeklyAttempt] = useState(0);
  const [seasonState, setSeasonState] = useState<SeasonState>({ status: "loading" });
  const [seasonAttempt, setSeasonAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setWeeklyState({ status: "loading" });
    getNrlTipsLeaderboard(season, round)
      .then((data) => live && setWeeklyState({ status: "success", data }))
      .catch(
        (err) =>
          live &&
          setWeeklyState({
            status: "error",
            message: err instanceof ApiError ? err.message : "Couldn't load the leaderboard.",
          }),
      );
    return () => {
      live = false;
    };
  }, [season, round, weeklyAttempt]);

  // Season tab is fetched lazily -- a visitor who never leaves the default
  // Weekly view never costs the season endpoint a request.
  useEffect(() => {
    if (tab !== "season") return;
    let live = true;
    setSeasonState({ status: "loading" });
    getNrlSeasonLeaderboard(season)
      .then((data) => live && setSeasonState({ status: "success", data }))
      .catch(
        (err) =>
          live &&
          setSeasonState({
            status: "error",
            message: err instanceof ApiError ? err.message : "Couldn't load the season leaderboard.",
          }),
      );
    return () => {
      live = false;
    };
  }, [tab, season, seasonAttempt]);

  return (
    <section>
      <div className="mb-2.5 flex items-center justify-between px-0.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted">Leaderboard</h2>
        <div className="flex gap-1 rounded-lg bg-surface-2 p-0.5 text-[11px] font-semibold">
          <button
            type="button"
            onClick={() => setTab("weekly")}
            aria-pressed={tab === "weekly"}
            className={cn("rounded-md px-2 py-1", tab === "weekly" ? "bg-win text-pitch" : "text-muted")}
          >
            Weekly
          </button>
          <button
            type="button"
            onClick={() => setTab("season")}
            aria-pressed={tab === "season"}
            className={cn("rounded-md px-2 py-1", tab === "season" ? "bg-win text-pitch" : "text-muted")}
          >
            Season
          </button>
        </div>
      </div>

      {tab === "weekly" ? (
        <>
          {weeklyState.status === "loading" && <Loading label="Loading leaderboard…" />}
          {weeklyState.status === "error" && (
            <ErrorState message={weeklyState.message} onRetry={() => setWeeklyAttempt((a) => a + 1)} />
          )}
          {weeklyState.status === "success" &&
            (weeklyState.data.entries.length === 0 ? (
              <p className="glass rounded-2xl p-4 text-center text-sm text-muted">
                {weeklyState.data.participant_count} playing this round
              </p>
            ) : (
              <WeeklyTable entries={weeklyState.data.entries} />
            ))}
        </>
      ) : (
        <>
          {seasonState.status === "loading" && <Loading label="Loading season leaderboard…" />}
          {seasonState.status === "error" && (
            <ErrorState message={seasonState.message} onRetry={() => setSeasonAttempt((a) => a + 1)} />
          )}
          {seasonState.status === "success" &&
            (seasonState.data.entries.length === 0 ? (
              <p className="glass rounded-2xl p-4 text-center text-sm text-muted">
                {seasonState.data.participant_count} playing this season
              </p>
            ) : (
              <SeasonTable entries={seasonState.data.entries} />
            ))}
        </>
      )}
    </section>
  );
}

function WeeklyTable({ entries }: { entries: NrlTipsLeaderboardEntry[] }) {
  return (
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
          {entries.map((row, i) => (
            <tr key={row.handle} className="border-t border-border">
              <td
                className={cn("px-2 py-2.5 font-semibold tabular-nums", i === 0 ? "text-gold" : "text-muted")}
              >
                {i + 1}
              </td>
              <td className="px-2 py-2.5 font-medium">{row.handle}</td>
              <td className="px-2 py-2.5 text-right font-display font-bold tabular-nums">{row.points}</td>
              <td className="px-2 py-2.5 text-right tabular-nums text-muted">{row.round_margin ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Same table idiom as WeeklyTable, plus the season's Rounds column and a
 *  cumulative Margin (total_margin, summed across the season's rounds). */
function SeasonTable({ entries }: { entries: NrlSeasonLeaderboardEntry[] }) {
  return (
    <div className="glass overflow-x-auto rounded-2xl p-2 sm:p-4">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[11px] uppercase tracking-wider text-muted">
            <th className="px-2 pb-2 text-left font-medium">#</th>
            <th className="px-2 pb-2 text-left font-medium">Player</th>
            <th className="px-2 pb-2 text-right font-medium">Points</th>
            <th className="px-2 pb-2 text-right font-medium">Margin</th>
            <th className="px-2 pb-2 text-right font-medium">Rounds</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((row, i) => (
            <tr key={row.handle} className="border-t border-border">
              <td
                className={cn("px-2 py-2.5 font-semibold tabular-nums", i === 0 ? "text-gold" : "text-muted")}
              >
                {i + 1}
              </td>
              <td className="px-2 py-2.5 font-medium">{row.handle}</td>
              <td className="px-2 py-2.5 text-right font-display font-bold tabular-nums">{row.points}</td>
              <td className="px-2 py-2.5 text-right tabular-nums text-muted">{row.total_margin ?? "—"}</td>
              <td className="px-2 py-2.5 text-right tabular-nums text-muted">{row.rounds_played}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
