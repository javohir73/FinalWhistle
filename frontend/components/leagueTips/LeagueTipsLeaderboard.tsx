"use client";

import { useEffect, useState } from "react";
import { ErrorState, Loading } from "@/components/States";
import { getLeagueSeasonLeaderboard, getLeagueTipsLeaderboard } from "@/lib/leagueTips";
import { ApiError } from "@/lib/session";
import { cn } from "@/lib/utils";
import type {
  LeagueSeasonLeaderboardEntry,
  LeagueSeasonLeaderboardResponse,
  LeagueTipsLeaderboardEntry,
  LeagueTipsLeaderboardResponse,
} from "@/lib/types";

type WeeklyState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; data: LeagueTipsLeaderboardResponse };

type SeasonState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "success"; data: LeagueSeasonLeaderboardResponse };

/** Weekly (per-matchweek) leaderboard for the league beat-the-AI loop (design
 *  doc: League Score Predictions, 2026-07-24), plus a Season tab over the
 *  season-long totals endpoint -- league-generic port of components/nrl/
 *  NrlTipsLeaderboard.tsx. Both share the same reveal rule: below
 *  _LEADERBOARD_MIN_PARTICIPANTS an empty leaderboard advertises an empty
 *  room, so this shows only a quiet participant count, never an empty table.
 *  Tiebreak is exact-count (replacing NRL's margin) -- the natural
 *  score-prediction tiebreak per the design doc. */
export function LeagueTipsLeaderboard({ league, matchweek }: { league: string; matchweek: number }) {
  const [tab, setTab] = useState<"weekly" | "season">("weekly");
  const [weeklyState, setWeeklyState] = useState<WeeklyState>({ status: "loading" });
  const [weeklyAttempt, setWeeklyAttempt] = useState(0);
  const [seasonState, setSeasonState] = useState<SeasonState>({ status: "loading" });
  const [seasonAttempt, setSeasonAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setWeeklyState({ status: "loading" });
    getLeagueTipsLeaderboard(league, matchweek)
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
  }, [league, matchweek, weeklyAttempt]);

  // Season tab is fetched lazily -- a visitor who never leaves the default
  // Weekly view never costs the season endpoint a request.
  useEffect(() => {
    if (tab !== "season") return;
    let live = true;
    setSeasonState({ status: "loading" });
    getLeagueSeasonLeaderboard(league)
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
  }, [tab, league, seasonAttempt]);

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
                {weeklyState.data.participant_count} playing this matchweek
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

function WeeklyTable({ entries }: { entries: LeagueTipsLeaderboardEntry[] }) {
  return (
    <div className="glass overflow-x-auto rounded-2xl p-2 sm:p-4">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[11px] uppercase tracking-wider text-muted">
            <th className="px-2 pb-2 text-left font-medium">#</th>
            <th className="px-2 pb-2 text-left font-medium">Player</th>
            <th className="px-2 pb-2 text-right font-medium">Points</th>
            <th className="px-2 pb-2 text-right font-medium">Exact</th>
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
              <td className="px-2 py-2.5 text-right tabular-nums text-muted">{row.exact_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Same table idiom as WeeklyTable, plus the season's Matchweeks column. */
function SeasonTable({ entries }: { entries: LeagueSeasonLeaderboardEntry[] }) {
  return (
    <div className="glass overflow-x-auto rounded-2xl p-2 sm:p-4">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[11px] uppercase tracking-wider text-muted">
            <th className="px-2 pb-2 text-left font-medium">#</th>
            <th className="px-2 pb-2 text-left font-medium">Player</th>
            <th className="px-2 pb-2 text-right font-medium">Points</th>
            <th className="px-2 pb-2 text-right font-medium">Exact</th>
            <th className="px-2 pb-2 text-right font-medium">MWs</th>
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
              <td className="px-2 py-2.5 text-right tabular-nums text-muted">{row.exact_count}</td>
              <td className="px-2 py-2.5 text-right tabular-nums text-muted">{row.matchweeks_played}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
