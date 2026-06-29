import { pct } from "@/lib/format";
import type { GoalMarkets as GoalMarketsData, TeamGoalBands } from "@/lib/types";

/** Below this, the "4+ goals" row is hidden to keep even contests uncluttered. */
const NOTABLE_4PLUS = 0.1;

/** Goal-total markets for a match: per-team bands + match over/under + BTTS.
 *  All numbers come from the same Poisson distribution as the predicted score. */
export function GoalMarkets({
  home,
  away,
  markets,
}: {
  home: string;
  away: string;
  markets: GoalMarketsData;
}) {
  return (
    <section className="glass rounded-2xl p-6">
      <h2 className="mb-4 font-display text-lg font-bold text-foreground">Goals</h2>
      <div className="grid gap-5 sm:grid-cols-2">
        <TeamBands team={home} bands={markets.home} />
        <TeamBands team={away} bands={markets.away} />
      </div>
      <div className="mt-5 grid grid-cols-3 gap-2 border-t border-border pt-4">
        <Stat label="Over 2.5" value={markets.total.over_2_5} />
        <Stat label="Over 3.5" value={markets.total.over_3_5} />
        <Stat label="Both score" value={markets.btts} />
      </div>
    </section>
  );
}

function TeamBands({ team, bands }: { team: string; bands: TeamGoalBands }) {
  const rows: [string, number][] = [
    ["To score", bands.to_score],
    ["2+ goals", bands.p2],
    ["3+ goals", bands.p3],
  ];
  if (bands.p4 >= NOTABLE_4PLUS) rows.push(["4+ goals", bands.p4]);
  return (
    <div>
      <p className="mb-2 font-display text-sm font-bold">{team}</p>
      <ul className="space-y-1.5">
        {rows.map(([label, v]) => (
          <li key={label} className="flex items-center justify-between text-sm">
            <span className="text-muted">{label}</span>
            <span className="font-display font-bold tabular-nums text-lime-deep">{pct(v)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl bg-win/[0.06] px-2 py-3 text-center">
      <p className="font-display text-lg font-extrabold tabular-nums text-lime-deep">{pct(value)}</p>
      <p className="mt-0.5 text-[11px] font-semibold text-muted">{label}</p>
    </div>
  );
}
