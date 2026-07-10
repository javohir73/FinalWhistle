import type { NrlVenueSplit } from "@/lib/types";

export function VenueSplits({ splits }: { splits: NrlVenueSplit[] }) {
  if (splits.length === 0) return null;
  return (
    <section className="glass rounded-2xl p-6">
      <h2 className="font-display text-sm font-semibold uppercase tracking-wider text-muted">
        Venue splits
      </h2>
      <ul className="mt-4 space-y-2">
        {splits.map((s) => (
          <li key={s.venue} className="flex items-baseline justify-between gap-3">
            <span className="truncate text-sm text-foreground">{s.venue}</span>
            <span className="whitespace-nowrap text-sm tabular-nums text-muted">
              <strong className="font-extrabold text-foreground">
                {s.wins}-{s.draws}-{s.losses}
              </strong>{" "}
              ·{" "}
              <span>
                {s.avg_for.toFixed(1)} for / {s.avg_against.toFixed(1)} against
              </span>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[11px] text-muted">W-D-L and per-game averages this season.</p>
    </section>
  );
}
