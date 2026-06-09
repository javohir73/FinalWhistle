"use client";

import Link from "next/link";
import { getLeaderboard } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Loading, ErrorState, Empty } from "@/components/States";
import { Flag } from "@/components/Flag";
import { CLERK_ENABLED } from "@/lib/auth";
import { MyRankCard } from "@/components/MyRankCard";

export default function LeaderboardPage() {
  const state = useFetch(getLeaderboard, []);

  return (
    <div>
      <header className="fade-up mb-6">
        <h1 className="font-display text-3xl font-extrabold tracking-tight sm:text-4xl">
          Leaderboard
        </h1>
        <p className="mt-2 max-w-xl text-muted">
          Public brackets ranked by points (group 3 · knockout 5 · finalist 10 · champion 20).
          Build yours on the{" "}
          <Link href="/my-bracket" className="text-win underline underline-offset-2">My Bracket</Link>{" "}
          page, then join.
        </p>
      </header>

      {CLERK_ENABLED && <MyRankCard />}

      {state.status === "loading" && <Loading label="Loading leaderboard…" />}
      {state.status === "error" && <ErrorState message={state.message} />}
      {state.status === "success" &&
        (state.data.length === 0 ? (
          <Empty label="No public brackets yet — be the first to join from My Bracket." />
        ) : (
          <div className="glass overflow-x-auto rounded-2xl p-2 sm:p-4">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[11px] uppercase tracking-wider text-muted">
                  <th className="px-2 pb-2 text-left font-medium">#</th>
                  <th className="px-2 pb-2 text-left font-medium">Player</th>
                  <th className="px-2 pb-2 text-left font-medium">Champion pick</th>
                  <th className="px-2 pb-2 text-right font-medium">Points</th>
                  <th className="hidden px-2 pb-2 text-right font-medium sm:table-cell">Top</th>
                </tr>
              </thead>
              <tbody>
                {state.data.map((row, i) => (
                  <tr key={`${row.display_name}-${i}`} className="border-t border-border/50">
                    <td className="px-2 py-2.5 font-semibold tabular-nums text-muted">
                      {row.rank ?? i + 1}
                    </td>
                    <td className="px-2 py-2.5 font-medium">{row.display_name}</td>
                    <td className="px-2 py-2.5">
                      {row.champion ? (
                        <span className="flex items-center gap-2">
                          <Flag team={row.champion} size={18} />
                          <span className="min-w-0 truncate">{row.champion}</span>
                        </span>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                    <td className="px-2 py-2.5 text-right font-display font-bold tabular-nums">
                      {row.total_points}
                    </td>
                    <td className="hidden px-2 py-2.5 text-right tabular-nums text-muted sm:table-cell">
                      {row.percentile != null ? `${row.percentile}%` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </div>
  );
}
