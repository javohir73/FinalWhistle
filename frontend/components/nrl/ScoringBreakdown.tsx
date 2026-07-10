import type { NrlMatchStatsResponse, NrlTeamMatchStats } from "@/lib/types";

/** Wave 2 stats section: home/away comparison rows for the frozen
 *  /api/nrl/matches/{id}/stats contract. Pure/presentational -- no fetching. */
const ROWS: { key: keyof NrlTeamMatchStats; label: string; pct?: boolean }[] = [
  { key: "tries", label: "Tries" },
  { key: "conversions", label: "Conversions" },
  { key: "penalties_conceded", label: "Penalties conceded" },
  { key: "errors", label: "Errors" },
  { key: "set_restarts", label: "Set restarts" },
  { key: "run_metres", label: "Run metres" },
  { key: "line_breaks", label: "Line breaks" },
  { key: "tackles", label: "Tackles" },
  { key: "tackle_efficiency", label: "Tackle efficiency", pct: true },
];

function fmt(value: number, pct?: boolean): string {
  return pct ? `${value.toFixed(1)}%` : value.toLocaleString("en-AU");
}

export function ScoringBreakdown({ stats }: { stats: NrlMatchStatsResponse }) {
  return (
    <div className="glass rounded-2xl p-6">
      <h3 className="font-display text-sm font-semibold uppercase tracking-wider text-muted">
        Scoring breakdown
      </h3>
      <ul className="mt-4 space-y-2">
        {ROWS.map(({ key, label, pct }) => {
          const home = stats.home[key];
          const away = stats.away[key];
          const total = home + away;
          const homeShare = total > 0 ? (home / total) * 100 : 50;
          return (
            <li key={key} className="grid grid-cols-[64px_1fr_64px] items-center gap-3">
              <span className="text-right text-sm font-extrabold tabular-nums text-foreground">
                {fmt(home, pct)}
              </span>
              <div>
                <div className="text-center text-xs text-muted">{label}</div>
                <div className="mt-1 flex h-1.5 overflow-hidden rounded-full bg-surface-2">
                  <div className="bg-win/60" style={{ width: `${homeShare}%` }} />
                  <div className="bg-loss/60" style={{ width: `${100 - homeShare}%` }} />
                </div>
              </div>
              <span className="text-left text-sm font-extrabold tabular-nums text-foreground">
                {fmt(away, pct)}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
