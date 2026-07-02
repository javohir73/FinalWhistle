import { pct } from "@/lib/format";

/** Per-team qualification probability bar for the group tables. */
export function QualificationBar({ prob }: { prob: number | null }) {
  const value = prob ?? 0;
  const strong = value >= 0.5;
  return (
    <div className="flex items-center gap-2 sm:gap-2.5">
      <div className="h-1.5 w-10 overflow-hidden rounded-full bg-surface-2 sm:w-24">
        <div
          className="h-full rounded-full transition-[width]"
          style={{
            width: `${value * 100}%`,
            background: strong ? "hsl(var(--win))" : "hsl(var(--draw))",
          }}
        />
      </div>
      <span className="w-9 text-right text-xs font-bold tabular-nums text-foreground">
        {pct(prob)}
      </span>
    </div>
  );
}
